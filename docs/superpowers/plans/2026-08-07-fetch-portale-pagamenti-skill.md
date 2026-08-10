# Fetch Portale Pagamenti Agent Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a portable Agent Skill and zero-dependency Python exporter that downloads verified Regione Lombardia Portale Pagamenti transactions as one CSV per day plus manifest, metadata, and ZIP.

**Architecture:** Keep one canonical skill under `skills/fetch-portale-pagamenti/`. Its vendor-neutral `SKILL.md` delegates all data work to a deterministic standard-library Python script; a root installer copies that same skill into Codex, Claude Code, and Cursor user skill directories. The exporter separates pure date/schema rules, Socrata transport, verified daily file writes, and range packaging through focused functions in one executable module.

**Tech Stack:** Python 3.10+ standard library (`argparse`, `csv`, `datetime`, `hashlib`, `json`, `pathlib`, `urllib`, `unittest`, `zipfile`), Agent Skills `SKILL.md`, optional Codex `agents/openai.yaml` metadata.

## Global Constraints

- Support only Portale Pagamenti identifiers `78vt-im2v`, `dr3m-v3by`, and `ne5i-i4a8` in v1.
- Always export from canonical dataset `78vt-im2v`.
- Resolve relative dates outside the exporter in `Europe/Rome`; the exporter accepts explicit inclusive ISO dates.
- Reject future dates; mark today as `partial`; require exact row-count equality for completed historical dates.
- Output one fixed-schema CSV per requested day, `manifest.csv`, `metadata.json`, and a ZIP.
- Use Python 3.10+ and the standard library only; add no runtime or test dependency.
- Read the optional token only from `SOCRATA_APP_TOKEN`; never accept, print, or persist it elsewhere.
- Preserve verified files for resume, create final files atomically, and never create a successful ZIP after an unresolved historical mismatch.
- Keep one vendor-neutral `SKILL.md`; do not duplicate instructions into `CLAUDE.md`, Cursor rules, or `AGENTS.md`.
- Push to GitHub only after user testing and explicit confirmation.

---

## Planned file map

- Create `skills/fetch-portale-pagamenti/SKILL.md`: portable agent instructions and invocation contract.
- Create `skills/fetch-portale-pagamenti/agents/openai.yaml`: optional Codex display metadata.
- Create `skills/fetch-portale-pagamenti/references/schema.md`: dataset identifiers, fixed CSV schema, and output contract.
- Create `skills/fetch-portale-pagamenti/scripts/export_payments.py`: CLI, Socrata access, verification, resume, manifest, metadata, and ZIP implementation.
- Create `install.py`: cross-agent user-level installer.
- Create `tests/__init__.py`: make targeted standard-library unittest commands stable.
- Create `tests/test_export_payments.py`: pure, HTTP, filesystem, orchestration, and CLI tests.
- Create `tests/test_install.py`: isolated-home installer tests.
- Create `LICENSE`: explicit MIT license text.
- Modify `README.md`: human installation and CLI documentation.
- Modify `.gitignore`: ignore generated exports and temporary files.
- Delete `.env.example`: obsolete multi-setting configuration surface.
- Delete `query.py`: superseded single-day exporter.
- Delete `requirements.txt`: runtime becomes standard-library only.

---

### Task 1: Initialize the portable skill and implement pure export rules

**Files:**
- Create: `skills/fetch-portale-pagamenti/SKILL.md`
- Create: `skills/fetch-portale-pagamenti/agents/openai.yaml`
- Create: `skills/fetch-portale-pagamenti/scripts/export_payments.py`
- Create: `skills/fetch-portale-pagamenti/references/schema.md`
- Create: `tests/__init__.py`
- Create: `tests/test_export_payments.py`

**Interfaces:**
- Produces: `CANONICAL_DATASET_ID: str`, `OUTPUT_FIELDS: tuple[str, ...]`, `resolve_dataset(value: str | None) -> str`, `parse_iso_date(value: str) -> date`, `validate_period(start: date, end: date, today: date) -> None`, `iter_dates(start: date, end: date) -> Iterator[date]`, `normalize_record(record: Mapping[str, Any], day: date) -> dict[str, str]`.
- Produces exceptions: `ExportError`, `InputError`, `VerificationError`.

- [ ] **Step 1: Run the skill's baseline behavior test before creating it**

Start a fresh agent in an isolated temporary working directory with no reference to this repository, the design, or the planned skill. Give it only this realistic request:

```text
Download Portale Pagamenti transactions for June 23, 2026, as daily CSV files and give me the downloadable archive.
```

Record the resulting choices and artifacts verbatim in the task transcript. Specifically observe whether the agent discovers the canonical historical dataset, writes reusable deterministic code versus ad hoc code, verifies the row count and checksum, creates the requested archive, and reports success only with a real artifact. Do not tell the agent those expected behaviors. This is the no-skill RED baseline; if it already satisfies the complete contract, stop and reassess what instruction the skill actually needs to add before authoring it.

- [ ] **Step 2: Initialize the skill directory using the required skill scaffold**

Run:

```bash
python3 /Users/esp/.codex/skills/.system/skill-creator/scripts/init_skill.py \
  fetch-portale-pagamenti \
  --path skills \
  --resources scripts,references \
  --interface 'display_name=Fetch Portale Pagamenti' \
  --interface 'short_description=Download verified Lombardia PagoPA daily CSVs' \
  --interface 'default_prompt=Use $fetch-portale-pagamenti to download Portale Pagamenti transactions for a date range.'
```

Expected: `skills/fetch-portale-pagamenti/` exists with `SKILL.md`, `agents/openai.yaml`, `scripts/`, and `references/`.

- [ ] **Step 3: Write failing tests for dataset resolution, dates, and schema normalization**

Create `tests/__init__.py` as an empty file. Create `tests/test_export_payments.py` with an import helper and these tests:

```python
import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "skills/fetch-portale-pagamenti/scripts/export_payments.py"
SPEC = importlib.util.spec_from_file_location("export_payments", SCRIPT)
export_payments = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = export_payments
SPEC.loader.exec_module(export_payments)


class ExporterPureTests(unittest.TestCase):
    def test_resolves_supported_aliases_to_canonical_dataset(self):
        for value in (
            None,
            "78vt-im2v",
            "dr3m-v3by",
            "ne5i-i4a8",
            "https://www.dati.lombardia.it/Government/example/dr3m-v3by/about_data",
        ):
            self.assertEqual(export_payments.resolve_dataset(value), "78vt-im2v")

    def test_rejects_unknown_dataset(self):
        with self.assertRaises(export_payments.InputError):
            export_payments.resolve_dataset("abcd-1234")
        with self.assertRaises(export_payments.InputError):
            export_payments.resolve_dataset("https://example.com/dr3m-v3by")

    def test_validates_inclusive_period(self):
        start = export_payments.parse_iso_date("2026-07-30")
        end = export_payments.parse_iso_date("2026-07-31")
        export_payments.validate_period(start, end, date(2026, 8, 7))
        self.assertEqual(
            list(export_payments.iter_dates(start, end)),
            [date(2026, 7, 30), date(2026, 7, 31)],
        )

    def test_rejects_bad_reversed_and_future_dates(self):
        with self.assertRaises(export_payments.InputError):
            export_payments.parse_iso_date("07/31/2026")
        with self.assertRaises(export_payments.InputError):
            export_payments.validate_period(date(2026, 8, 2), date(2026, 8, 1), date(2026, 8, 7))
        with self.assertRaises(export_payments.InputError):
            export_payments.validate_period(date(2026, 8, 8), date(2026, 8, 8), date(2026, 8, 7))

    def test_normalizes_fixed_schema_and_hour(self):
        raw = {
            "id": "7",
            "psp_id": "BANK",
            "psp_desc": "Bank, S.p.A.",
            "ente_cf": "001",
            "ente_desc": "Comune",
            "ente_cap": "20100",
            "ente_prov": "MI",
            "pag_importo": "10.50",
            "pag_data": "2026-07-01T00:00:00.000",
            "tipo_dovuto": "ticket",
            "ora": "9",
            "modello": "3",
        }
        normalized = export_payments.normalize_record(raw, date(2026, 7, 1))
        self.assertEqual(tuple(normalized), export_payments.OUTPUT_FIELDS)
        self.assertEqual(normalized["pag_data"], "2026-07-01T09:00:00.000")
        self.assertNotIn("modello", normalized)
```

- [ ] **Step 4: Run the pure tests and confirm the missing exporter fails**

Run: `python3 -m unittest tests.test_export_payments.ExporterPureTests -v`

Expected: FAIL while importing the absent `export_payments.py` or missing interfaces.

- [ ] **Step 5: Implement the pure contracts minimally**

Create `export_payments.py` with imports, constants, exceptions, and pure functions:

```python
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterator, Mapping
from urllib.parse import urlparse

CANONICAL_DATASET_ID = "78vt-im2v"
SUPPORTED_DATASET_IDS = {"78vt-im2v", "dr3m-v3by", "ne5i-i4a8"}
OUTPUT_FIELDS = (
    "id", "psp_id", "psp_desc", "ente_cf", "ente_desc",
    "ente_cap", "ente_prov", "pag_importo", "pag_data", "tipo_dovuto",
)


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
    matches = [dataset_id for dataset_id in SUPPORTED_DATASET_IDS if dataset_id in parsed.path]
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
```

- [ ] **Step 6: Run the tests and verify they pass**

Run: `python3 -m unittest tests.test_export_payments.ExporterPureTests -v`

Expected: all `ExporterPureTests` PASS.

- [ ] **Step 7: Commit the scaffold and pure contracts**

```bash
git add skills/fetch-portale-pagamenti tests/__init__.py tests/test_export_payments.py
git commit -m "feat: scaffold portable payment export skill"
```

---

### Task 2: Add Socrata count queries, stable pagination, and retries

**Files:**
- Modify: `skills/fetch-portale-pagamenti/scripts/export_payments.py`
- Modify: `tests/test_export_payments.py`

**Interfaces:**
- Consumes: `CANONICAL_DATASET_ID`, `ExportError`, `VerificationError`.
- Produces: `SocrataClient(token: str = "", endpoint: str = DEFAULT_ENDPOINT, attempts: int = 5, backoff: float = 1.0, page_size: int = 50000)`, `SocrataClient.expected_counts(start: date, end: date) -> dict[date, int]`, `SocrataClient.count_day(day: date) -> int`, `SocrataClient.fetch_day(day: date) -> list[dict[str, Any]]`.
- Internal seam: `SocrataClient._request(params: Mapping[str, str]) -> list[dict[str, Any]]`, patchable through `unittest.mock.patch.object`.

- [ ] **Step 1: Write failing transport and pagination tests**

Append the following class to `tests/test_export_payments.py`:

```python
from unittest.mock import patch
from urllib.error import HTTPError, URLError


class SocrataClientTests(unittest.TestCase):
    def test_expected_counts_fills_zero_days(self):
        client = export_payments.SocrataClient()
        response = [{"day": "2026-07-01T00:00:00.000", "count": "2"}]
        with patch.object(client, "_request", return_value=response) as request:
            counts = client.expected_counts(date(2026, 7, 1), date(2026, 7, 2))
        self.assertEqual(counts, {date(2026, 7, 1): 2, date(2026, 7, 2): 0})
        self.assertIn("date_trunc_ymd(pag_data)", request.call_args.args[0]["$select"])

    def test_fetch_day_uses_id_keyset_and_deduplicates(self):
        client = export_payments.SocrataClient(page_size=2)
        pages = [
            [{"id": "1"}, {"id": "2"}],
            [{"id": "2"}, {"id": "3"}],
            [],
        ]
        with patch.object(client, "_request", side_effect=pages) as request:
            rows = client.fetch_day(date(2026, 7, 1))
        self.assertEqual([row["id"] for row in rows], ["1", "2", "3"])
        second_where = request.call_args_list[1].args[0]["$where"]
        self.assertIn("id > 2", second_where)

    def test_request_retries_transient_errors_only(self):
        client = export_payments.SocrataClient(attempts=3, backoff=0)
        transient = URLError("temporary")
        with patch.object(export_payments, "urlopen", side_effect=[transient, FakeResponse([])]) as urlopen:
            self.assertEqual(client._request({"$limit": "1"}), [])
        self.assertEqual(urlopen.call_count, 2)

    def test_request_does_not_retry_http_400(self):
        client = export_payments.SocrataClient(attempts=3, backoff=0)
        permanent = HTTPError("https://example", 400, "bad", {}, None)
        with patch.object(export_payments, "urlopen", side_effect=permanent) as urlopen:
            with self.assertRaises(export_payments.ExportError):
                client._request({"$limit": "1"})
        self.assertEqual(urlopen.call_count, 1)

    def test_request_retries_429_and_500_against_local_http_server(self):
        Handler.responses = [(429, b"[]"), (500, b"[]"), (200, b"[]")]
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            endpoint = f"http://127.0.0.1:{server.server_port}/resource.json"
            client = export_payments.SocrataClient(endpoint=endpoint, attempts=3, backoff=0)
            self.assertEqual(client._request({"$limit": "1"}), [])
            self.assertEqual(len(Handler.requests), 3)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_request_reports_retry_exhaustion(self):
        client = export_payments.SocrataClient(attempts=2, backoff=0)
        with patch.object(export_payments, "urlopen", side_effect=URLError("offline")) as urlopen:
            with self.assertRaisesRegex(export_payments.ExportError, "after 2 attempts"):
                client._request({"$limit": "1"})
        self.assertEqual(urlopen.call_count, 2)
```

Add this helper above the test classes:

```python
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self._body


class Handler(BaseHTTPRequestHandler):
    responses = []
    requests = []

    def do_GET(self):
        type(self).requests.append(self.path)
        status, body = type(self).responses.pop(0)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass
```

- [ ] **Step 2: Run the Socrata tests and verify they fail**

Run: `python3 -m unittest tests.test_export_payments.SocrataClientTests -v`

Expected: FAIL because `SocrataClient` is not defined.

- [ ] **Step 3: Implement the standard-library Socrata client**

Add `json` and `time`, plus `HTTPError` and `URLError` from `urllib.error`, `urlencode` from `urllib.parse`, and `Request` and `urlopen` from `urllib.request`. Implement:

```python
DEFAULT_ENDPOINT = "https://www.dati.lombardia.it/resource/78vt-im2v.json"


class SocrataClient:
    def __init__(self, token="", endpoint=DEFAULT_ENDPOINT, attempts=5, backoff=1.0, page_size=50000):
        self.token = token
        self.endpoint = endpoint
        self.attempts = attempts
        self.backoff = backoff
        self.page_size = page_size

    def _request(self, params):
        query = urlencode(params)
        headers = {"Accept": "application/json"}
        if self.token:
            headers["X-App-Token"] = self.token
        request = Request(f"{self.endpoint}?{query}", headers=headers)
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
```

Implement `expected_counts` with one grouped query and initialize every date to zero before applying returned rows. Implement `count_day` with `count(*) AS count`. Implement `fetch_day` with `$select` limited to `OUTPUT_FIELDS` plus `ora`, `$order: "id ASC"`, a date equality filter, `id > last_id` after the first page, numeric `id` validation, and a dictionary keyed by `id` for deduplication. Advance the cursor to the largest numeric ID in the raw page. Stop when the raw page is empty or shorter than `page_size`; raise `VerificationError` if a non-empty page does not advance the cursor. Return deduplicated records sorted by integer `id`.

- [ ] **Step 4: Run pure and transport tests**

Run: `python3 -m unittest tests.test_export_payments.ExporterPureTests tests.test_export_payments.SocrataClientTests -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit the Socrata client**

```bash
git add skills/fetch-portale-pagamenti/scripts/export_payments.py tests/test_export_payments.py
git commit -m "feat: add resilient Socrata client"
```

---

### Task 3: Write and resume verified daily CSV files atomically

**Files:**
- Modify: `skills/fetch-portale-pagamenti/scripts/export_payments.py`
- Modify: `tests/test_export_payments.py`

**Interfaces:**
- Consumes: `OUTPUT_FIELDS`, `normalize_record`, `VerificationError`.
- Produces: `DayResult(day: date, status: str, transactions: int, filename: str, sha256: str, source_count_observed: int)`, `sha256_file(path: Path) -> str`, `csv_row_count(path: Path) -> int`, `write_verified_day(daily_dir: Path, day: date, records: Sequence[Mapping[str, Any]], expected_count: int, today: date) -> DayResult`, `can_resume(path: Path, manifest_entry: Mapping[str, str]) -> bool`.

- [ ] **Step 1: Write failing filesystem verification tests**

Append:

```python
import csv
import tempfile


class DailyFileTests(unittest.TestCase):
    def test_writes_verified_historical_csv_atomically(self):
        records = [
            {"id": "1", "psp_desc": "Bank, S.p.A.", "pag_importo": "3.50", "ora": "8"},
            {"id": "2", "pag_importo": "4.00", "ora": "9"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp)
            result = export_payments.write_verified_day(
                daily, date(2026, 7, 1), records, expected_count=2, today=date(2026, 8, 7)
            )
            final = daily / result.filename
            self.assertEqual(result.status, "complete")
            self.assertEqual(export_payments.csv_row_count(final), 2)
            self.assertEqual(result.sha256, export_payments.sha256_file(final))
            self.assertFalse(list(daily.glob("*.part")))
            with final.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(tuple(reader.fieldnames), export_payments.OUTPUT_FIELDS)
                self.assertEqual(next(reader)["psp_desc"], "Bank, S.p.A.")

    def test_writes_header_only_zero_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = export_payments.write_verified_day(
                Path(tmp), date(2026, 7, 2), [], expected_count=0, today=date(2026, 8, 7)
            )
            self.assertEqual(result.transactions, 0)
            self.assertEqual(export_payments.csv_row_count(Path(tmp) / result.filename), 0)

    def test_rejects_historical_count_mismatch_without_final_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp)
            with self.assertRaises(export_payments.VerificationError):
                export_payments.write_verified_day(
                    daily, date(2026, 7, 1), [{"id": "1"}], 2, date(2026, 8, 7)
                )
            self.assertFalse((daily / "pagamenti_2026-07-01.csv").exists())

    def test_marks_today_partial_without_requiring_equal_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = export_payments.write_verified_day(
                Path(tmp), date(2026, 8, 7), [{"id": "1"}], 2, date(2026, 8, 7)
            )
            self.assertEqual(result.status, "partial")

    def test_resume_requires_matching_count_and_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp)
            result = export_payments.write_verified_day(
                daily, date(2026, 7, 1), [{"id": "1"}], 1, date(2026, 8, 7)
            )
            entry = {"transactions": "1", "sha256": result.sha256}
            self.assertTrue(export_payments.can_resume(daily / result.filename, entry))
            self.assertFalse(export_payments.can_resume(daily / result.filename, {**entry, "sha256": "bad"}))

    def test_interrupted_promotion_removes_part_and_preserves_other_verified_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp)
            preserved = export_payments.write_verified_day(
                daily, date(2026, 6, 30), [{"id": "1"}], 1, date(2026, 8, 7)
            )
            with patch.object(export_payments.os, "replace", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    export_payments.write_verified_day(
                        daily, date(2026, 7, 1), [{"id": "2"}], 1, date(2026, 8, 7)
                    )
            self.assertTrue((daily / preserved.filename).exists())
            self.assertFalse((daily / "pagamenti_2026-07-01.csv").exists())
            self.assertFalse(list(daily.glob("*.part")))
```

- [ ] **Step 2: Run daily file tests and verify they fail**

Run: `python3 -m unittest tests.test_export_payments.DailyFileTests -v`

Expected: FAIL because `DayResult` and daily-file functions are missing.

- [ ] **Step 3: Implement atomic CSV and resume helpers**

Add a frozen dataclass:

```python
@dataclass(frozen=True)
class DayResult:
    day: date
    status: str
    transactions: int
    filename: str
    sha256: str
    source_count_observed: int
```

Implement SHA-256 in 1 MiB chunks. Implement `csv_row_count` using `csv.reader`, verify the exact header tuple, and count remaining rows. In `write_verified_day`, create `daily_dir`, normalize records, reject duplicate or missing IDs, require exact historical equality, allow current-day inequality with status `partial`, write `filename.part` with `csv.DictWriter`, flush and `os.fsync`, verify the `.part` row count, then call `os.replace(part_path, final_path)`. Remove the `.part` file on exceptions. Implement `can_resume` by comparing both parsed manifest count and SHA-256 with the actual file and returning `False` on any read or parse failure.

- [ ] **Step 4: Run exporter unit tests**

Run: `python3 -m unittest tests.test_export_payments -v`

Expected: all current tests PASS.

- [ ] **Step 5: Commit verified daily files**

```bash
git add skills/fetch-portale-pagamenti/scripts/export_payments.py tests/test_export_payments.py
git commit -m "feat: write verified daily payment CSVs"
```

---

### Task 4: Orchestrate ranges, resume runs, and create manifests, metadata, and ZIPs

**Files:**
- Modify: `skills/fetch-portale-pagamenti/scripts/export_payments.py`
- Modify: `tests/test_export_payments.py`

**Interfaces:**
- Consumes: `SocrataClient`, `DayResult`, `iter_dates`, `write_verified_day`, `can_resume`.
- Produces: `ExportConfig(start: date, end: date, output: Path, requested_dataset: str | None, today: date)`, `ExportSummary(root: Path, zip_path: Path, days: tuple[DayResult, ...], transactions: int)`, `export_range(config: ExportConfig, client: SocrataClient) -> ExportSummary`, `build_parser() -> argparse.ArgumentParser`, `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Write failing range and CLI tests**

Append:

```python
from unittest.mock import Mock
import zipfile


class RangeExportTests(unittest.TestCase):
    def test_export_range_creates_manifest_metadata_and_zip(self):
        client = Mock()
        client.expected_counts.return_value = {
            date(2026, 7, 1): 1,
            date(2026, 7, 2): 0,
        }
        client.fetch_day.side_effect = [[{"id": "1", "ora": "8"}], []]
        client.count_day.side_effect = [1, 0]
        with tempfile.TemporaryDirectory() as tmp:
            config = export_payments.ExportConfig(
                start=date(2026, 7, 1),
                end=date(2026, 7, 2),
                output=Path(tmp),
                requested_dataset="dr3m-v3by",
                today=date(2026, 8, 7),
            )
            summary = export_payments.export_range(config, client)
            self.assertEqual(summary.transactions, 1)
            self.assertTrue(summary.zip_path.exists())
            with (summary.root / "manifest.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["date"] for row in rows], ["2026-07-01", "2026-07-02"])
            self.assertEqual([row["transactions"] for row in rows], ["1", "0"])
            metadata = json.loads((summary.root / "metadata.json").read_text())
            self.assertEqual(metadata["dataset"]["canonical_id"], "78vt-im2v")
            self.assertFalse(metadata["contains_partial_day"])
            with zipfile.ZipFile(summary.zip_path) as archive:
                self.assertEqual(
                    sorted(archive.namelist()),
                    [
                        "daily/pagamenti_2026-07-01.csv",
                        "daily/pagamenti_2026-07-02.csv",
                        "manifest.csv",
                        "metadata.json",
                    ],
                )

    def test_second_run_resumes_verified_historical_files(self):
        client = Mock()
        client.expected_counts.return_value = {date(2026, 7, 1): 1}
        client.fetch_day.return_value = [{"id": "1", "ora": "8"}]
        client.count_day.return_value = 1
        with tempfile.TemporaryDirectory() as tmp:
            config = export_payments.ExportConfig(
                date(2026, 7, 1), date(2026, 7, 1), Path(tmp), None, date(2026, 8, 7)
            )
            export_payments.export_range(config, client)
            export_payments.export_range(config, client)
        self.assertEqual(client.fetch_day.call_count, 1)

    def test_final_historical_reconciliation_failure_creates_no_zip(self):
        client = Mock()
        client.expected_counts.return_value = {date(2026, 7, 1): 1}
        client.fetch_day.return_value = [{"id": "1", "ora": "8"}]
        client.count_day.return_value = 2
        with tempfile.TemporaryDirectory() as tmp:
            config = export_payments.ExportConfig(
                date(2026, 7, 1), date(2026, 7, 1), Path(tmp), None, date(2026, 8, 7)
            )
            with self.assertRaises(export_payments.VerificationError):
                export_payments.export_range(config, client)
            self.assertFalse(list(Path(tmp).glob("*.zip")))
            self.assertTrue(
                (Path(tmp) / "portale-pagamenti-2026-07-01-to-2026-07-01"
                 / "daily/pagamenti_2026-07-01.csv").exists()
            )

    def test_final_count_mismatch_refetches_once_then_succeeds(self):
        client = Mock()
        client.expected_counts.return_value = {date(2026, 7, 1): 1}
        client.fetch_day.side_effect = [
            [{"id": "1", "ora": "8"}],
            [{"id": "1", "ora": "8"}],
        ]
        client.count_day.side_effect = [2, 1]
        with tempfile.TemporaryDirectory() as tmp:
            config = export_payments.ExportConfig(
                date(2026, 7, 1), date(2026, 7, 1), Path(tmp), None, date(2026, 8, 7)
            )
            summary = export_payments.export_range(config, client)
            self.assertTrue(summary.zip_path.exists())
        self.assertEqual(client.fetch_day.call_count, 2)

    def test_current_day_is_partial_and_records_final_source_count(self):
        client = Mock()
        client.expected_counts.return_value = {date(2026, 8, 7): 1}
        client.fetch_day.return_value = [{"id": "1", "ora": "8"}]
        client.count_day.return_value = 2
        with tempfile.TemporaryDirectory() as tmp:
            config = export_payments.ExportConfig(
                date(2026, 8, 7), date(2026, 8, 7), Path(tmp), None, date(2026, 8, 7)
            )
            summary = export_payments.export_range(config, client)
            metadata = json.loads((summary.root / "metadata.json").read_text())
            with (summary.root / "manifest.csv").open(newline="", encoding="utf-8") as handle:
                manifest = next(csv.DictReader(handle))
            self.assertEqual(manifest["status"], "partial")
            self.assertTrue(metadata["contains_partial_day"])
            self.assertEqual(metadata["current_day_source_count_observed_at_end"], 2)

    def test_cli_reads_token_only_from_environment(self):
        parser = export_payments.build_parser()
        destinations = {action.dest for action in parser._actions}
        self.assertNotIn("token", destinations)
        with patch.dict("os.environ", {"SOCRATA_APP_TOKEN": "secret"}), patch.object(
            export_payments, "export_range"
        ) as run:
            run.return_value = export_payments.ExportSummary(Path("x"), Path("x.zip"), (), 0)
            code = export_payments.main(["--from", "2026-07-01", "--to", "2026-07-01"])
        self.assertEqual(code, 0)
```

- [ ] **Step 2: Run range tests and verify they fail**

Run: `python3 -m unittest tests.test_export_payments.RangeExportTests -v`

Expected: FAIL because range dataclasses and orchestration are missing.

- [ ] **Step 3: Implement configuration, orchestration, and output artifacts**

Implement frozen dataclasses with the exact fields above. `export_range` must:

1. Validate the period and resolve the requested dataset.
2. Create root name `portale-pagamenti-{start}-to-{end}` and `daily/`.
3. Load an existing manifest into a date-keyed dictionary when present.
4. Query initial counts for all dates.
5. Resume only historical files that pass `can_resume` and still match the initial source count.
6. Fetch and write every non-resumable day. If fetched rows do not match the initial historical count, refetch that day once before failing.
7. Re-query each historical day with `count_day` and require exact equality. If the final source count differs from the written file, refetch the rows once, immediately re-query the count, and atomically rewrite only when those two new observations agree; otherwise raise `VerificationError`. For today, record `count_day` as `source_count_observed_at_end` without requiring equality.
8. Write `manifest.csv` atomically with columns exactly `date,status,transactions,filename,sha256`.
9. Write `metadata.json` atomically with exact keys:

```python
{
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
```

10. Create the ZIP through a temporary `.zip.part` path with relative members `daily/...`, `manifest.csv`, and `metadata.json`; atomically replace the final ZIP.

Print one plain progress line to stdout when each day is resumed, downloaded, retried, or marked partial. Never include request headers or the token in progress or error output.

Implement `build_parser` with required `--from`, required `--to`, optional `--output` defaulting to `exports`, and optional `--dataset`. Implement `main` to derive `today` using `ZoneInfo("Europe/Rome")`, read only `SOCRATA_APP_TOKEN`, print the ZIP and totals on success, catch `ExportError`, print `Error: ...` to stderr, and return `1`. End with `raise SystemExit(main())`.

- [ ] **Step 4: Run the complete exporter test file**

Run: `python3 -m unittest tests.test_export_payments -v`

Expected: all exporter tests PASS.

- [ ] **Step 5: Exercise CLI validation without network access**

Run: `python3 skills/fetch-portale-pagamenti/scripts/export_payments.py --from bad --to 2026-07-01`

Expected: exit code `1`, stderr contains `Invalid date 'bad'; use YYYY-MM-DD`, and no export directory is created.

- [ ] **Step 6: Commit range export and packaging**

```bash
git add skills/fetch-portale-pagamenti/scripts/export_payments.py tests/test_export_payments.py
git commit -m "feat: package verified payment date ranges"
```

---

### Task 5: Add the cross-agent installer

**Files:**
- Create: `install.py`
- Create: `tests/test_install.py`

**Interfaces:**
- Produces: `AGENT_DIRS: dict[str, Path]`, `install_skill(agent: str, home: Path, source: Path = DEFAULT_SOURCE) -> tuple[Path, ...]`, `build_parser() -> argparse.ArgumentParser`, `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Write failing installer tests**

Create `tests/test_install.py`:

```python
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "install.py"
SPEC = importlib.util.spec_from_file_location("skill_installer", SCRIPT)
skill_installer = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = skill_installer
SPEC.loader.exec_module(skill_installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "home"
        self.source = Path(self.temp.name) / "source"
        (self.source / "scripts").mkdir(parents=True)
        (self.source / "SKILL.md").write_text("---\nname: fetch-portale-pagamenti\ndescription: Test\n---\n")
        (self.source / "scripts/export.py").write_text("print('ok')\n")

    def tearDown(self):
        self.temp.cleanup()

    def test_installs_each_supported_agent(self):
        expected = {
            "codex": self.home / ".codex/skills/fetch-portale-pagamenti",
            "claude": self.home / ".claude/skills/fetch-portale-pagamenti",
            "cursor": self.home / ".cursor/skills/fetch-portale-pagamenti",
        }
        for agent, target in expected.items():
            installed = skill_installer.install_skill(agent, self.home, self.source)
            self.assertEqual(installed, (target,))
            self.assertEqual((target / "SKILL.md").read_text(), (self.source / "SKILL.md").read_text())

    def test_all_installs_three_identical_copies(self):
        targets = skill_installer.install_skill("all", self.home, self.source)
        self.assertEqual(len(targets), 3)
        self.assertEqual({(target / "SKILL.md").read_text() for target in targets}, {(self.source / "SKILL.md").read_text()})

    def test_replaces_only_named_skill_and_preserves_unrelated_files(self):
        unrelated = self.home / ".codex/skills/other/SKILL.md"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("keep")
        target = self.home / ".codex/skills/fetch-portale-pagamenti"
        target.mkdir(parents=True)
        (target / "old.txt").write_text("old")
        skill_installer.install_skill("codex", self.home, self.source)
        self.assertEqual(unrelated.read_text(), "keep")
        self.assertFalse((target / "old.txt").exists())
        self.assertTrue((target / "scripts/export.py").exists())
```

- [ ] **Step 2: Run installer tests and verify they fail**

Run: `python3 -m unittest tests.test_install -v`

Expected: FAIL because `install.py` does not exist.

- [ ] **Step 3: Implement safe named-skill replacement**

Create `install.py` using only `argparse`, `os`, `pathlib`, `shutil`, `tempfile`, and `uuid`. Define:

```python
SKILL_NAME = "fetch-portale-pagamenti"
DEFAULT_SOURCE = Path(__file__).resolve().parent / "skills" / SKILL_NAME
AGENT_DIRS = {
    "codex": Path(".codex/skills"),
    "claude": Path(".claude/skills"),
    "cursor": Path(".cursor/skills"),
}
```

For each selected agent, validate that `source/SKILL.md` exists, copy the source to a unique sibling temporary directory, rename an existing named target to a unique backup, rename the temporary directory to the target, then delete the backup. If promotion fails, restore the backup before raising. Never enumerate, rewrite, or delete sibling skill directories. `main` accepts only `--agent {codex,claude,cursor,all}`, installs under `Path.home()`, prints each final path, and returns `0`; unexpected installation errors return `1` with a plain error.

- [ ] **Step 4: Run installer tests**

Run: `python3 -m unittest tests.test_install -v`

Expected: all installer tests PASS.

- [ ] **Step 5: Commit the installer**

```bash
git add install.py tests/test_install.py
git commit -m "feat: install skill across coding agents"
```

---

### Task 6: Finish portable skill instructions, schema reference, README, and legacy cleanup

**Files:**
- Modify: `skills/fetch-portale-pagamenti/SKILL.md`
- Modify: `skills/fetch-portale-pagamenti/agents/openai.yaml`
- Create: `skills/fetch-portale-pagamenti/references/schema.md`
- Modify: `README.md`
- Modify: `.gitignore`
- Create: `LICENSE`
- Delete: `.env.example`
- Delete: `query.py`
- Delete: `requirements.txt`

**Interfaces:**
- Consumes: final CLI arguments and output contract from Tasks 1–4; installer commands from Task 5.
- Produces: reliable implicit trigger description and explicit `$fetch-portale-pagamenti` workflow shared across agents.

- [ ] **Step 1: Turn the no-skill baseline failure into the minimal instruction contract**

Review the verbatim Task 1 baseline. Keep only instructions that correct an observed failure plus the non-negotiable output and security contract from the approved design. Express the workflow as the seven-step positive recipe below; do not add a rationalization table, flowchart, vendor-specific section, or duplicated schema details.

- [ ] **Step 2: Replace `SKILL.md` with concise vendor-neutral instructions**

Use exactly this frontmatter:

```yaml
---
name: fetch-portale-pagamenti
description: Use when a user asks for Regione Lombardia Portale Pagamenti or pagoPA transactions for an explicit date, month, or range; daily CSV files; historical backfills; today or yesterday exports; or supplies dataset IDs 78vt-im2v, dr3m-v3by, or ne5i-i4a8.
---
```

The body must instruct the agent to:

1. Resolve relative dates in `Europe/Rome` and ask for the year only when genuinely ambiguous.
2. Resolve the absolute path of the skill directory from the current `SKILL.md` location.
3. Run `python3 <skill-directory>/scripts/export_payments.py --from <date> --to <date> --output <writable-directory>` and add `--dataset <user-value>` only when the user supplied a recognized URL or ID.
4. Use `SOCRATA_APP_TOKEN` only if already available; never request it for ordinary jobs or expose it.
5. Wait for successful completion, then report ZIP path, day count, total records, and partial-day status.
6. On failure, report the exporter error and preserved resumable directory; do not claim success or improvise another downloader.
7. Read `references/schema.md` only when the user asks about fields, provenance, or output details.

- [ ] **Step 3: Write the schema reference and regenerate Codex metadata**

`references/schema.md` must document the three recognized IDs, canonical source URL, the ten output fields in order, hour enrichment, manifest columns, metadata keys, historical `complete` versus today `partial`, and the zero-row header-only rule.

Read `/Users/esp/.codex/skills/.system/skill-creator/references/openai_yaml.md`, then regenerate:

```bash
python3 /Users/esp/.codex/skills/.system/skill-creator/scripts/generate_openai_yaml.py \
  skills/fetch-portale-pagamenti \
  --interface 'display_name=Fetch Portale Pagamenti' \
  --interface 'short_description=Download verified Lombardia PagoPA daily CSVs' \
  --interface 'default_prompt=Use $fetch-portale-pagamenti to download Portale Pagamenti transactions for a date range.'
```

- [ ] **Step 4: Rewrite the README as a problem-first project story and add the license**

Rewrite `README.md` with these sections in order:

1. **What this is:** a portable Agent Skill and deterministic CLI for verified Regione Lombardia Portale Pagamenti exports.
2. **The problem:** public records still require discovering the historical source, resolving current-day aliases, building Socrata queries, paginating safely, retrying transient failures, and proving daily completeness; coding agents otherwise improvise this work repeatedly.
3. **What this solves:** natural-language or CLI requests produce one CSV per day, `manifest.csv`, `metadata.json`, and one ZIP delivery artifact.
4. **Installation:** commands for Codex, Claude Code, Cursor, and direct Python use from the one canonical skill.
5. **Examples:** realistic agent prompts first, followed by the direct CLI command.
6. **Trust guarantees:** historical reconciliation, stable pagination, checksums, atomic completion, resume, header-only zero days, and current-day `partial` status.
7. **Output and schema:** the artifact tree and fixed ten-field schema, without duplicating the full reference prose.
8. **Focused v1:** Portale Pagamenti only; no arbitrary Socrata or Regione Lombardia dataset claim.
9. **Future direction:** the foundations may later inform a broader skill for other Lombardia open-data datasets, guided by real use cases, with no timeline, compatibility promise, or committed v2 scope.
10. **Development and license:** tests, Python 3.10+, zero dependencies, and MIT.

Use a concise, welcoming tone. Include the optional `SOCRATA_APP_TOKEN` where authentication is explained. Do not mention Southwind, lead with implementation history, or present the future direction as a roadmap promise.

Create `LICENSE` with the standard MIT license and copyright line `Copyright (c) 2026 esworde`.

Add to `.gitignore`:

```gitignore
exports/
*.part
*.zip
.DS_Store
```

- [ ] **Step 5: Remove the superseded exporter surface**

Delete `.env.example`, `query.py`, and `requirements.txt`. Confirm no remaining runtime or documentation file references `python-dotenv`, the `requests` package, `os.getenv("APP_TOKEN")`, `os.getenv("DATE")`, `DROP_COLUMNS`, or `RENAME_COLUMNS`; the design and plan documents may retain those names as migration history. Keep the new `SOCRATA_APP_TOKEN` contract.

- [ ] **Step 6: Run structural validation and the complete automated suite**

Run:

```bash
python3 /Users/esp/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/fetch-portale-pagamenti
python3 -m unittest discover -s tests -v
test "$(wc -w < skills/fetch-portale-pagamenti/SKILL.md)" -lt 500
git diff --check
```

Expected: validator succeeds, all tests PASS, `SKILL.md` is under 500 words, and `git diff --check` prints nothing.

- [ ] **Step 7: Commit documentation and cleanup**

```bash
git add README.md LICENSE .gitignore skills
git add -u .env.example query.py requirements.txt
git commit -m "docs: publish portable payment export skill"
```

---

### Task 7: Run live export, install locally, and forward-test agent behavior

**Files:**
- No tracked file changes expected.
- Generated and ignored: `exports/portale-pagamenti-2026-06-23-to-2026-06-23/`
- Generated and ignored: `exports/portale-pagamenti-2026-06-23-to-2026-06-23.zip`

**Interfaces:**
- Consumes: completed exporter, installer, canonical skill, and full test suite.
- Produces: verified user-test installation and evidence that a fresh agent follows the skill rather than inventing an exporter.

- [ ] **Step 1: Re-run all automated and structural verification from a clean status**

Run:

```bash
python3 /Users/esp/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/fetch-portale-pagamenti
python3 -m unittest discover -s tests -v
test "$(wc -w < skills/fetch-portale-pagamenti/SKILL.md)" -lt 500
git diff --check
git status --short
```

Expected: validation succeeds, all tests PASS, the skill stays under 500 words, no whitespace errors, and no tracked modifications.

- [ ] **Step 2: Run a tokenless live historical smoke test**

Run with `SOCRATA_APP_TOKEN` unset:

```bash
env -u SOCRATA_APP_TOKEN python3 skills/fetch-portale-pagamenti/scripts/export_payments.py \
  --from 2026-06-23 \
  --to 2026-06-23 \
  --dataset dr3m-v3by \
  --output exports
```

Expected: one completed daily CSV, `manifest.csv`, `metadata.json`, and ZIP; the manifest count equals the live `78vt-im2v` source count for 2026-06-23.

- [ ] **Step 3: Independently verify the live artifact**

Run a read-only Python command or test helper that:

- Opens the ZIP with `zipfile.ZipFile.testzip()` and requires `None`.
- Reads `manifest.csv` and requires one row with `date=2026-06-23`, `status=complete`, and a positive integer transaction count.
- Reads the daily CSV and requires the same row count plus the exact ten-field header.
- Recomputes the daily file SHA-256 and requires equality with the manifest.
- Reads `metadata.json` and requires `canonical_id=78vt-im2v`, `contains_partial_day=false`, and total transactions equal to the manifest.

Expected: every assertion succeeds.

- [ ] **Step 4: Detect locally available supported clients and install for testing**

Run:

```bash
command -v codex || true
command -v claude || true
command -v cursor || true
python3 install.py --agent codex
```

Expected: the Codex skill is installed at `~/.codex/skills/fetch-portale-pagamenti/`. If Claude Code or Cursor CLI is available, also run the corresponding installer command and record that client for a runtime smoke test. If unavailable, rely on the temporary-home installer tests and do not claim runtime validation.

- [ ] **Step 5: Forward-test the skill in a fresh agent context**

Use a fresh agent with the installed skill and only this task prompt; do not include evaluation criteria or expected implementation details in the dispatched prompt:

```text
Download Portale Pagamenti transactions for June 23, 2026, as daily CSV files and give me the downloadable archive.
```

After it finishes, compare its behavior and artifacts with the no-skill baseline. Pass only if it activates `fetch-portale-pagamenti`, runs the bundled exporter, uses the canonical `78vt-im2v` source, and returns the verified ZIP. Fail if it writes alternate download code, queries `dr3m-v3by` for historical records, omits reconciliation, or claims success without an archive.

- [ ] **Step 6: Report the user test handoff without pushing**

Provide the installed skill name, exact fresh-session test prompt, live ZIP path, automated-test count, structural-validation result, runtime-tested clients, and any clients validated only by install-layout tests. State that the branch remains local and unpushed pending user confirmation.

---

## Final implementation self-check

- Every requirement in `docs/superpowers/specs/2026-08-07-fetch-portale-pagamenti-skill-design.md` maps to Tasks 1–7.
- Run `rg -n 'T[B]D|T[O]DO|FIXM[E]|PLACEH[O]LDER|implement lat[e]r|similar t[o]' docs/superpowers/plans/2026-08-07-fetch-portale-pagamenti-skill.md` and require no plan placeholders.
- Run `python3 -m unittest discover -s tests -v`, skill validation, the skill word-count check, live smoke export, ZIP verification, and the paired no-skill/with-skill fresh-agent behavior tests before reporting completion.
- Do not delete or replace `/Users/esp/studio-regione-lombardia`; the implementation lives in `/Users/esp/socrata-lombardia`, which follows the public repository history.
- Do not push until the user tests and explicitly approves publication.
