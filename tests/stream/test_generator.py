"""K2-T5: генератор без брокера (A-1..A-4, A-6) и разбор сообщений ingestor-а (A-7)."""
import json
import random
from collections import Counter
from datetime import date, datetime, timedelta
from functools import lru_cache

import pytest

pytest.importorskip("jsonschema")

from stream.common import (  # noqa: E402
    DATA_DIR, STATUS_RANK, TYPE_REPLAY, TYPE_STATUS, dumps, load_validator,
)
from stream.generator.dataset import build_replay, envelope  # noqa: E402
from stream.generator.noise import add_noise  # noqa: E402
from stream.generator.schedule import schedule  # noqa: E402
from stream.ingestor.validate import (  # noqa: E402
    REASON_INVALID_JSON, REASON_SCHEMA, REASON_UNKNOWN_TYPE, REASON_VERSION, Rejected, parse_message,
)

pytestmark = pytest.mark.skipif(not (DATA_DIR / "olist_orders_dataset.csv").exists(), reason="нет data/*.csv")

CUTOFF = date(2018, 8, 1)
PRODUCED_AT = "2020-01-01T00:00:00.000000Z"


@lru_cache(maxsize=1)
def _cut_replay():
    return build_replay(DATA_DIR, CUTOFF)


@lru_cache(maxsize=1)
def _validator():
    return load_validator()


def test_a1_counts_for_cutoff():
    replay = _cut_replay()
    assert replay.orders_total == 6532
    assert abs(len(replay.events) - 39099) <= 39099 * 0.02


def test_a2_events_valid_created_first_per_order():
    replay = _cut_replay()
    validator = _validator()
    seen: dict[str, str] = {}
    for event in replay.events:
        message = envelope(event, PRODUCED_AT)
        assert validator.is_valid(message), message
        assert message["order_id"] == event.order_id
        seen.setdefault(event.order_id, message["type"])
    assert set(seen.values()) == {"order.created"}
    assert len(seen) == replay.orders_total


def test_a2_replay_completed_is_valid():
    runner = pytest.importorskip("stream.generator.runner")
    replay = _cut_replay()
    last_ts = max(e.event_ts for e in replay.events)
    done = runner.replay_event("5b0b2f0a-0000-4000-8000-000000000001", CUTOFF, len(replay.events),
                               replay.orders_total, last_ts)
    assert done["type"] == TYPE_REPLAY
    assert _validator().is_valid(done)
    assert done["payload"]["expected"]["orders_total"] == 99441


def test_a3_event_ids_are_deterministic_and_unique():
    first = [envelope(e, "2020-01-01T00:00:00.000000Z")["event_id"] for e in _cut_replay().events]
    second = [envelope(e, "2021-02-02T00:00:00.000000Z")["event_id"] for e in build_replay(DATA_DIR, CUTOFF).events]
    assert first == second
    assert len(set(first)) == len(first)


def test_a6_max_status_rank_matches_csv():
    import csv

    replay = _cut_replay()
    top: dict[str, str] = {}
    for event in replay.events:
        if event.type == TYPE_STATUS:
            status = envelope(event, PRODUCED_AT)["payload"]["order_status"]
            if STATUS_RANK[status] > STATUS_RANK[top.get(event.order_id, "created")]:
                top[event.order_id] = status
    with open(DATA_DIR / "olist_orders_dataset.csv", encoding="utf-8", newline="") as handle:
        csv_status = {row["order_id"]: row["order_status"].strip() for row in csv.DictReader(handle)}
    for order_id, status in top.items():
        assert STATUS_RANK[status] == STATUS_RANK[csv_status[order_id]], order_id


# --- schedule (A-4) ---

def _times(n: int = 2000, seed: int = 1) -> list[datetime]:
    rng = random.Random(seed)
    moment = datetime(2018, 1, 1)
    result = []
    for _ in range(n):
        moment += timedelta(seconds=rng.choice([0, 30, 3600, 86400 * 3]))
        result.append(moment)
    return result


@pytest.mark.parametrize("duration", [5.0, 60.0, 120.0])
def test_a4_schedule_total_and_gap(duration):
    pauses = schedule(_times(), duration=duration, max_gap=0.2)
    assert len(pauses) == 2000
    assert pauses[0] == 0.0
    assert all(0.0 <= p <= 0.2 + 1e-9 for p in pauses)
    assert 0.9 * duration <= sum(pauses) <= duration


def test_a4_schedule_real_replay_60s():
    times = [e.event_ts for e in _cut_replay().events]
    # паузы считаются по порядку отправки: отрицательная разница даёт 0
    pauses = schedule(times, duration=60.0, max_gap=0.2)
    assert len(pauses) == len(times)
    assert max(pauses) <= 0.2 + 1e-9
    assert 54.0 <= sum(pauses) <= 60.0


def test_schedule_edge_cases():
    assert schedule([]) == []
    assert schedule([datetime(2018, 1, 1)]) == [0.0]
    same = [datetime(2018, 1, 1)] * 3
    assert schedule(same, duration=10) == [0.0, 0.0, 0.0]


def test_schedule_without_duration_is_day_per_second():
    base = datetime(2018, 1, 1)
    assert schedule([base, base + timedelta(hours=12)], max_gap=10) == pytest.approx([0.0, 0.5])


# --- шум ---

def test_noise_loses_nothing_and_keeps_order_per_order():
    events = _cut_replay().events[:5000]
    noisy = add_noise(events)
    assert {id(e) for e in noisy} == {id(e) for e in events}
    assert len(noisy) >= len(events)
    assert len(noisy) - len(events) <= len(events) * 0.02

    # первое появление событий одного заказа идёт в исходном порядке
    def firsts(items):
        order: dict[str, list] = {}
        seen = set()
        for event in items:
            if id(event) not in seen:
                seen.add(id(event))
                order.setdefault(event.order_id, []).append(id(event))
        return order

    assert firsts(noisy) == firsts(events)
    assert [id(e) for e in add_noise(events)] == [id(e) for e in noisy]  # детерминированно


# --- parse_message (A-7) ---

def _valid_message() -> dict:
    event = _cut_replay().events[0]
    return envelope(event, PRODUCED_AT)


def test_parse_valid_message():
    document = parse_message(dumps(_valid_message()), _validator())
    assert isinstance(document, dict)
    assert document["type"] == "order.created"


@pytest.mark.parametrize("raw", [b"{not json", b"", b"\xff\xfe"])
def test_parse_invalid_json(raw):
    result = parse_message(raw, _validator())
    assert isinstance(result, Rejected) and result.reason_code == REASON_INVALID_JSON


def test_parse_none_and_non_object():
    assert parse_message(None, _validator()).reason_code == REASON_INVALID_JSON
    assert parse_message(b"[1,2]", _validator()).reason_code == REASON_SCHEMA


def test_parse_unknown_type_keeps_event_id():
    message = {**_valid_message(), "type": "order.exploded"}
    result = parse_message(json.dumps(message).encode(), _validator())
    assert result.reason_code == REASON_UNKNOWN_TYPE
    assert result.event_id == message["event_id"]


def test_parse_unsupported_version():
    message = {**_valid_message(), "schema_version": 2}
    assert parse_message(json.dumps(message).encode(), _validator()).reason_code == REASON_VERSION


def test_parse_schema_violation():
    message = _valid_message()
    del message["payload"]["customer"]
    result = parse_message(json.dumps(message).encode(), _validator())
    assert result.reason_code == REASON_SCHEMA
    bad_id = {**_valid_message(), "event_id": "not-a-uuid"}
    assert parse_message(json.dumps(bad_id).encode(), _validator()).reason_code == REASON_SCHEMA


def test_type_counts_in_cut_replay():
    counts = Counter(e.type for e in _cut_replay().events)
    assert counts["order.created"] == 6532
    assert set(counts) <= {"order.created", "payment.captured", "order.status_changed", "review.posted"}
