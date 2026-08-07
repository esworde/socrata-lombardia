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
