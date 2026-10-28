"""Contract checks (K0-T3): schemas are valid JSON Schema 2020-12, examples behave as named."""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
EVENTS = CONTRACTS / "events"
EXAMPLES = EVENTS / "examples"

SCHEMA_FILES = sorted(EVENTS.glob("*.json")) + [CONTRACTS / "chart_spec.json"]
EVENT_TYPES = [
    "order.created",
    "payment.captured",
    "order.status_changed",
    "review.posted",
    "replay.completed",
]


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _registry():
    resources = []
    for path in SCHEMA_FILES:
        schema = _load(path)
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


REGISTRY = _registry()


def _validator(schema_path):
    return Draft202012Validator(_load(schema_path), registry=REGISTRY)


def _target(example_name):
    """Schema file for an example: event types go through the envelope."""
    prefix = example_name.split(".valid")[0].split(".invalid")[0]
    if prefix in EVENT_TYPES:
        return EVENTS / "envelope.json"
    if prefix == "chart_spec":
        return CONTRACTS / "chart_spec.json"
    return EVENTS / f"{prefix}.json"


def _examples(kind):
    return sorted(EXAMPLES.glob(f"*.{kind}*.json"))


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=lambda p: p.name)
def test_schema_is_valid_2020_12(path):
    schema = _load(path)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("path", _examples("valid"), ids=lambda p: p.name)
def test_valid_example_passes(path):
    errors = list(_validator(_target(path.name)).iter_errors(_load(path)))
    assert errors == []


@pytest.mark.parametrize("path", _examples("invalid"), ids=lambda p: p.name)
def test_invalid_example_rejected(path):
    assert not _validator(_target(path.name)).is_valid(_load(path))


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_every_event_type_has_valid_and_invalid_example(event_type):
    assert (EXAMPLES / f"{event_type}.valid.json").exists()
    assert list(EXAMPLES.glob(f"{event_type}.invalid_*.json"))


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_valid_payload_passes_own_schema(event_type):
    payload = _load(EXAMPLES / f"{event_type}.valid.json")["payload"]
    assert _validator(EVENTS / f"{event_type}.json").is_valid(payload)
