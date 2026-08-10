import importlib.util
import json
import sys
import unittest
import csv
import tempfile
import zipfile
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

SCRIPT = Path(__file__).parents[1] / "skills/fetch-portale-pagamenti/scripts/export_payments.py"
SPEC = importlib.util.spec_from_file_location("export_payments", SCRIPT)
export_payments = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = export_payments
SPEC.loader.exec_module(export_payments)


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

    def test_rejects_dataset_ids_embedded_in_url_path_segments(self):
        with self.assertRaises(export_payments.InputError):
            export_payments.resolve_dataset(
                "https://www.dati.lombardia.it/Government/example-dr3m-v3by/about_data"
            )

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
            self.assertFalse(export_payments.can_resume(daily / result.filename, {**entry, "transactions": None}))

    def test_resume_returns_false_when_csv_cannot_be_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_bytes(b"\xff")
            self.assertFalse(export_payments.can_resume(path, {"transactions": "0", "sha256": "x"}))

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

    def test_current_day_records_final_count_when_initial_count_was_stale(self):
        client = Mock()
        client.expected_counts.return_value = {date(2026, 8, 7): 2}
        client.fetch_day.return_value = [{"id": "1", "ora": "8"}]
        client.count_day.return_value = 1
        with tempfile.TemporaryDirectory() as tmp:
            config = export_payments.ExportConfig(
                date(2026, 8, 7), date(2026, 8, 7), Path(tmp), None, date(2026, 8, 7)
            )
            summary = export_payments.export_range(config, client)
        self.assertEqual(summary.days[0].status, "partial")
        self.assertEqual(summary.days[0].source_count_observed, 1)

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
