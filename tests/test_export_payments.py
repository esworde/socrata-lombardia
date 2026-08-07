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
