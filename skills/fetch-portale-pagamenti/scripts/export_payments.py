from __future__ import annotations

import json
import time
from datetime import date, timedelta
from typing import Any, Iterator, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

CANONICAL_DATASET_ID = "78vt-im2v"
SUPPORTED_DATASET_IDS = {"78vt-im2v", "dr3m-v3by", "ne5i-i4a8"}
OUTPUT_FIELDS = (
    "id", "psp_id", "psp_desc", "ente_cf", "ente_desc",
    "ente_cap", "ente_prov", "pag_importo", "pag_data", "tipo_dovuto",
)
DEFAULT_ENDPOINT = "https://www.dati.lombardia.it/resource/78vt-im2v.json"


class ExportError(Exception):
    """Base class for user-facing export failures."""


class InputError(ExportError):
    """Raised for invalid user input."""


class VerificationError(ExportError):
    """Raised when source and exported data do not reconcile."""


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
        last_error: HTTPError | URLError | None = None
        for attempt in range(1, self.attempts + 1):
            try:
                with urlopen(request, timeout=60) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as error:
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
