import importlib.util
import json
import sys
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch
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
