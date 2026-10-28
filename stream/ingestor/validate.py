"""Разбор сообщения orders.events и сообщения orders.dlq (K2 §5 п.1, contracts/events/dlq.json)."""

import json
from typing import NamedTuple

from jsonschema.exceptions import best_match

from stream.common import EVENT_TYPES, SCHEMA_VERSION, utc_now_iso

REASON_INVALID_JSON = "invalid_json"
REASON_SCHEMA = "schema_violation"
REASON_UNKNOWN_TYPE = "unknown_type"
REASON_VERSION = "unsupported_version"
REASON_APPLY = "apply_error"

DETAIL_MAX = 500


class Rejected(NamedTuple):
    reason_code: str
    reason_detail: str
    event_id: str | None


def _cut(text: str) -> str:
    return text if len(text) <= DETAIL_MAX else text[:DETAIL_MAX - 3] + "..."


def parse_message(raw: bytes | None, validator) -> dict | Rejected:
    """Конверт события или причина отказа; в landing попадают только валидные события."""
    if raw is None:
        return Rejected(REASON_INVALID_JSON, "message is empty", None)
    try:
        document = json.loads(raw)
    except ValueError as exc:
        return Rejected(REASON_INVALID_JSON, _cut(str(exc)), None)
    if not isinstance(document, dict):
        return Rejected(REASON_SCHEMA, "message is not a JSON object", None)

    event_id = document.get("event_id")
    event_id = event_id if isinstance(event_id, str) else None
    event_type = document.get("type")
    if isinstance(event_type, str) and event_type not in EVENT_TYPES:
        return Rejected(REASON_UNKNOWN_TYPE, _cut(f"unknown type {event_type!r}"), event_id)
    if "schema_version" in document and document["schema_version"] != SCHEMA_VERSION:
        return Rejected(REASON_VERSION, _cut(f"schema_version {document['schema_version']!r} is not supported"),
                        event_id)
    if not validator.is_valid(document):
        error = best_match(validator.iter_errors(document))
        path = "/".join(str(part) for part in error.absolute_path) or "$"
        return Rejected(REASON_SCHEMA, _cut(f"{path}: {error.message}"), event_id)
    return document


def dlq_message(reason_code: str, reason_detail: str, topic: str, partition: int | None, offset: int | None,
                event_id: str | None, original: str) -> dict:
    return {
        "failed_at": utc_now_iso(),
        "reason_code": reason_code,
        "reason_detail": _cut(reason_detail),
        "source": {"topic": topic, "partition": partition if partition is not None else 0,
                   "offset": offset if offset is not None else 0},
        "event_id": event_id,
        "original": original,
    }
