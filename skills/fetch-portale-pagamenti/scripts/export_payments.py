from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import ssl
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

CANONICAL_DATASET_ID = "78vt-im2v"
SUPPORTED_DATASET_IDS = {"78vt-im2v", "dr3m-v3by", "ne5i-i4a8"}
EXPORTER_VERSION = "1.0.0"
OUTPUT_FIELDS = (
    "id", "psp_id", "psp_desc", "ente_cf", "ente_desc",
    "ente_cap", "ente_prov", "pag_importo", "pag_data", "tipo_dovuto",
)
DEFAULT_ENDPOINT = "https://www.dati.lombardia.it/resource/78vt-im2v.json"
SYSTEM_CA_BUNDLES = (
    "/etc/ssl/cert.pem",
    "/etc/ssl/certs/ca-certificates.crt",
)


class ExportError(Exception):
    """Base class for user-facing export failures."""


class InputError(ExportError):
    """Raised for invalid user input."""


class VerificationError(ExportError):
    """Raised when source and exported data do not reconcile."""


def create_ssl_context() -> ssl.SSLContext:
    if ssl.get_default_verify_paths().cafile:
        return ssl.create_default_context()
    for cafile in SYSTEM_CA_BUNDLES:
        if os.path.isfile(cafile):
            return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


@dataclass(frozen=True)
class DayResult:
    day: date
    status: str
    transactions: int
    filename: str
    sha256: str
    source_count_observed: int


@dataclass(frozen=True)
class ExportConfig:
    start: date
    end: date
    output: Path
    requested_dataset: str | None
    today: date


@dataclass(frozen=True)
class ExportSummary:
    root: Path
    zip_path: Path
    days: tuple[DayResult, ...]
    transactions: int


def resolve_dataset(value: str | None) -> str:
    if value is None:
        return CANONICAL_DATASET_ID
    if value in SUPPORTED_DATASET_IDS:
        return CANONICAL_DATASET_ID
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "dati.lombardia.it", "www.dati.lombardia.it"
    }:
        raise InputError(f"Unsupported Portale Pagamenti dataset: {value}")
    matches = [segment for segment in parsed.path.split("/") if segment in SUPPORTED_DATASET_IDS]
    if len(matches) != 1:
        raise InputError(f"Unsupported Portale Pagamenti dataset: {value}")
    return CANONICAL_DATASET_ID


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise InputError(f"Invalid date '{value}'; use YYYY-MM-DD") from error


def validate_period(start: date, end: date, today: date) -> None:
    if start > end:
        raise InputError("Start date must be on or before end date")
    if end > today:
        raise InputError("Future dates are not available")


def iter_dates(start: date, end: date) -> Iterator[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def normalize_record(record: Mapping[str, Any], day: date) -> dict[str, str]:
    try:
        hour = int(record.get("ora", 0))
    except (TypeError, ValueError) as error:
        raise VerificationError(f"Invalid ora for transaction {record.get('id', '<unknown>')}") from error
    normalized = {field: str(record.get(field, "")) for field in OUTPUT_FIELDS}
    normalized["pag_data"] = f"{day.isoformat()}T{hour:02d}:00:00.000"
    return normalized


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def csv_row_count(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        try:
            header = tuple(next(reader))
        except StopIteration as error:
            raise VerificationError(f"CSV file {path} has no header") from error
        if header != OUTPUT_FIELDS:
            raise VerificationError(f"CSV file {path} has an unexpected header")
        return sum(1 for _ in reader)


def write_verified_day(
    daily_dir: Path,
    day: date,
    records: Sequence[Mapping[str, Any]],
    expected_count: int,
    today: date,
) -> DayResult:
    normalized = [normalize_record(record, day) for record in records]
    ids = [record["id"] for record in normalized]
    if not all(ids) or len(set(ids)) != len(ids):
        raise VerificationError(f"Day {day.isoformat()} contains missing or duplicate transaction IDs")
    if day != today and len(normalized) != expected_count:
        raise VerificationError(
            f"Day {day.isoformat()} returned {len(normalized)} records; expected {expected_count}"
        )

    daily_dir.mkdir(parents=True, exist_ok=True)
    filename = f"pagamenti_{day.isoformat()}.csv"
    final_path = daily_dir / filename
    part_path = daily_dir / f"{filename}.part"
    status = "partial" if day == today and len(normalized) != expected_count else "complete"
    try:
        with part_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows(normalized)
            handle.flush()
            os.fsync(handle.fileno())
        if csv_row_count(part_path) != len(normalized):
            raise VerificationError(f"CSV row count verification failed for {day.isoformat()}")
        checksum = sha256_file(part_path)
        os.replace(part_path, final_path)
    except Exception:
        part_path.unlink(missing_ok=True)
        raise
    return DayResult(day, status, len(normalized), filename, checksum, expected_count)


def can_resume(path: Path, manifest_entry: Mapping[str, str]) -> bool:
    try:
        return (
            csv_row_count(path) == int(manifest_entry["transactions"])
            and sha256_file(path) == manifest_entry["sha256"]
        )
    except (KeyError, OSError, TypeError, ValueError, VerificationError):
        return False


class SocrataClient:
    def __init__(
        self,
        token: str = "",
        endpoint: str = DEFAULT_ENDPOINT,
        attempts: int = 5,
        backoff: float = 1.0,
        page_size: int = 50000,
    ) -> None:
        self.token = token
        self.endpoint = endpoint
        self.attempts = attempts
        self.backoff = backoff
        self.page_size = page_size

    def _request(self, params: Mapping[str, str]) -> list[dict[str, Any]]:
        query = urlencode(params)
        headers = {"Accept": "application/json"}
        if self.token:
            headers["X-App-Token"] = self.token
        request = Request(f"{self.endpoint}?{query}", headers=headers)
        context = create_ssl_context()
        last_error: HTTPError | URLError | None = None
        for attempt in range(1, self.attempts + 1):
            try:
                with urlopen(request, timeout=60, context=context) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as error:
                error.close()
                if error.code != 429 and error.code < 500:
                    raise ExportError(f"Socrata rejected the request with HTTP {error.code}") from error
                last_error = error
            except URLError as error:
                last_error = error
            if attempt < self.attempts:
                time.sleep(self.backoff * (2 ** (attempt - 1)))
        raise ExportError(f"Socrata request failed after {self.attempts} attempts") from last_error

    def expected_counts(self, start: date, end: date) -> dict[date, int]:
        counts = {day: 0 for day in iter_dates(start, end)}
        rows = self._request({
            "$select": "date_trunc_ymd(pag_data) AS day, count(*) AS count",
            "$where": f"pag_data between '{start.isoformat()}T00:00:00.000' and '{end.isoformat()}T23:59:59.999'",
            "$group": "date_trunc_ymd(pag_data)",
            "$order": "day ASC",
        })
        for row in rows:
            counts[date.fromisoformat(row["day"][:10])] = int(row["count"])
        return counts

    def count_day(self, day: date) -> int:
        rows = self._request({
            "$select": "count(*) AS count",
            "$where": f"date_trunc_ymd(pag_data) = '{day.isoformat()}T00:00:00.000'",
        })
        return int(rows[0]["count"])

    def fetch_day(self, day: date) -> list[dict[str, Any]]:
        records: dict[int, dict[str, Any]] = {}
        last_id: int | None = None
        while True:
            where = f"date_trunc_ymd(pag_data) = '{day.isoformat()}T00:00:00.000'"
            if last_id is not None:
                where += f" AND id > {last_id}"
            rows = self._request({
                "$select": ", ".join((*OUTPUT_FIELDS, "ora")),
                "$where": where,
                "$order": "id ASC",
                "$limit": str(self.page_size),
            })
            if not rows:
                break
            try:
                ids = [int(row["id"]) for row in rows]
            except (KeyError, TypeError, ValueError) as error:
                raise VerificationError("Socrata returned a non-numeric transaction id") from error
            next_id = max(ids)
            if last_id is not None and next_id <= last_id:
                raise VerificationError("Socrata pagination did not advance")
            for row, row_id in zip(rows, ids):
                records[row_id] = row
            last_id = next_id
            if len(rows) < self.page_size:
                break
        return [records[row_id] for row_id in sorted(records)]


def _load_manifest(path: Path) -> dict[date, dict[str, str]]:
    if not path.exists():
        return {}
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            entries = {}
            for entry in csv.DictReader(handle):
                entries[date.fromisoformat(entry["date"])] = entry
            return entries
    except (KeyError, OSError, UnicodeError, ValueError, csv.Error):
        return {}


def _write_manifest(path: Path, results: Sequence[DayResult]) -> None:
    part_path = path.with_name(f"{path.name}.part")
    try:
        with part_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=("date", "status", "transactions", "filename", "sha256")
            )
            writer.writeheader()
            for result in results:
                writer.writerow({
                    "date": result.day.isoformat(),
                    "status": result.status,
                    "transactions": result.transactions,
                    "filename": result.filename,
                    "sha256": result.sha256,
                })
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(part_path, path)
    except Exception:
        part_path.unlink(missing_ok=True)
        raise


def _write_metadata(path: Path, config: ExportConfig, results: Sequence[DayResult]) -> None:
    current_result = next((result for result in results if result.day == config.today), None)
    metadata = {
        "exporter_version": EXPORTER_VERSION,
        "dataset": {
            "requested": config.requested_dataset,
            "canonical_id": CANONICAL_DATASET_ID,
            "url": DEFAULT_ENDPOINT,
        },
        "period": {"from": config.start.isoformat(), "to": config.end.isoformat()},
        "timezone": "Europe/Rome",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema": list(OUTPUT_FIELDS),
        "files": len(results),
        "transactions": sum(result.transactions for result in results),
        "contains_partial_day": any(result.status == "partial" for result in results),
        "current_day_source_count_observed_at_end": (
            current_result.source_count_observed if current_result else None
        ),
    }
    part_path = path.with_name(f"{path.name}.part")
    try:
        with part_path.open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(part_path, path)
    except Exception:
        part_path.unlink(missing_ok=True)
        raise


def _write_zip(root: Path, zip_path: Path, results: Sequence[DayResult]) -> None:
    part_path = Path(f"{zip_path}.part")
    try:
        with zipfile.ZipFile(part_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for result in results:
                archive.write(root / "daily" / result.filename, f"daily/{result.filename}")
            archive.write(root / "manifest.csv", "manifest.csv")
            archive.write(root / "metadata.json", "metadata.json")
        os.replace(part_path, zip_path)
    except Exception:
        part_path.unlink(missing_ok=True)
        raise


def _resumed_result(day: date, entry: Mapping[str, str], source_count: int) -> DayResult:
    return DayResult(
        day=day,
        status="complete",
        transactions=int(entry["transactions"]),
        filename=entry["filename"],
        sha256=entry["sha256"],
        source_count_observed=source_count,
    )


def export_range(config: ExportConfig, client: SocrataClient) -> ExportSummary:
    validate_period(config.start, config.end, config.today)
    resolve_dataset(config.requested_dataset)
    root = config.output / f"portale-pagamenti-{config.start}-to-{config.end}"
    daily_dir = root / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    manifest_entries = _load_manifest(root / "manifest.csv")
    expected_counts = client.expected_counts(config.start, config.end)
    results: list[DayResult] = []

    for day in iter_dates(config.start, config.end):
        expected_count = expected_counts[day]
        filename = f"pagamenti_{day.isoformat()}.csv"
        entry = manifest_entries.get(day)
        path = daily_dir / filename
        resumed = (
            day != config.today
            and entry is not None
            and entry.get("status") == "complete"
            and entry.get("filename") == filename
            and entry.get("transactions") == str(expected_count)
            and can_resume(path, entry)
        )
        if resumed:
            result = _resumed_result(day, entry, expected_count)
            progress = "resumed"
        else:
            records = client.fetch_day(day)
            retried = day != config.today and len(records) != expected_count
            if retried:
                records = client.fetch_day(day)
            result = write_verified_day(daily_dir, day, records, expected_count, config.today)
            progress = "retried" if retried else "downloaded"

        if day == config.today:
            source_count = client.count_day(day)
            result = DayResult(
                result.day, "partial", result.transactions, result.filename, result.sha256, source_count
            )
            progress = "partial"
        else:
            source_count = client.count_day(day)
            if source_count != result.transactions:
                records = client.fetch_day(day)
                source_count = client.count_day(day)
                if len(records) != source_count:
                    raise VerificationError(
                        f"Day {day.isoformat()} changed during final reconciliation"
                    )
                result = write_verified_day(daily_dir, day, records, source_count, config.today)
                progress = "retried"
        print(f"{day.isoformat()}: {progress}")
        results.append(result)

    manifest_path = root / "manifest.csv"
    metadata_path = root / "metadata.json"
    _write_manifest(manifest_path, results)
    _write_metadata(metadata_path, config, results)
    zip_path = config.output / f"{root.name}.zip"
    _write_zip(root, zip_path, results)
    return ExportSummary(root, zip_path, tuple(results), sum(result.transactions for result in results))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export verified Portale Pagamenti daily CSV files.")
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--output", type=Path, default=Path("exports"))
    parser.add_argument("--dataset")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = ExportConfig(
            parse_iso_date(args.start),
            parse_iso_date(args.end),
            args.output,
            args.dataset,
            datetime.now(ZoneInfo("Europe/Rome")).date(),
        )
        summary = export_range(config, SocrataClient(token=os.environ.get("SOCRATA_APP_TOKEN", "")))
    except ExportError as error:
        print(f"Error: {error}", file=os.sys.stderr)
        return 1
    print(f"ZIP: {summary.zip_path}")
    print(f"Transactions: {summary.transactions}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
