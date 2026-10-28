"""Применение событий в landing и core (K2 §5 п.2-3): всё upsert, повтор пачки не меняет итог.

apply_batch не делает COMMIT и не пишет ops.stream_status: транзакцией владеет вызывающий
(пауза по K3 §3.3 берётся им первым запросом транзакции).
"""

from dataclasses import dataclass, field

from psycopg2 import DataError, IntegrityError
from psycopg2.extras import Json

from stream.common import (
    STATUS_RANK,
    TOPIC_EVENTS,
    TYPE_CREATED,
    TYPE_PAYMENT,
    TYPE_REPLAY,
    TYPE_REVIEW,
    TYPE_STATUS,
)

STATUS_APPLIED = "applied"
STATUS_SKIPPED = "skipped_stale"
STATUS_ERROR = "error"
_DONE = (STATUS_APPLIED, STATUS_SKIPPED)
ERROR_MAX = 1000


class ApplyError(Exception):
    """Событие не применимо к текущему состоянию core (например, заказа нет)."""


@dataclass(frozen=True)
class Incoming:
    """Валидное событие и его происхождение (для landing.events и orders.dlq)."""

    envelope: dict
    topic: str = TOPIC_EVENTS
    partition: int | None = None
    offset: int | None = None
    key: bytes | None = None
    raw: bytes | None = None


@dataclass
class BatchResult:
    new_events: int = 0
    applied: int = 0
    skipped_stale: int = 0
    duplicates: int = 0
    replay_seen: bool = False
    last_event_ts: str | None = None
    errors: list[tuple[Incoming, str]] = field(default_factory=list)


_INSERT_LANDING = """
INSERT INTO landing.events (event_id, topic, partition, kafka_offset, order_id, type, schema_version,
                            payload, event_ts, produced_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::timestamp, %s::timestamp)
ON CONFLICT (event_id) DO NOTHING
"""

_UPSERT_CUSTOMER = """
INSERT INTO core.dim_customer (customer_id, customer_unique_id, zip_prefix, city, state,
                               city_normalized, state_normalized)
VALUES (%(customer_id)s, %(customer_unique_id)s, NULLIF(TRIM(%(zip_prefix)s), ''), NULLIF(TRIM(%(city)s), ''),
        NULLIF(TRIM(%(state)s), ''), LOWER(NULLIF(TRIM(%(city)s), '')), UPPER(NULLIF(TRIM(%(state)s), '')))
ON CONFLICT (customer_id) DO NOTHING
"""

_UPSERT_ORDER = """
INSERT INTO core.fact_order (order_id, customer_id, order_status, purchased_at, estimated_delivery_at)
VALUES (%(order_id)s, %(customer_id)s, %(order_status)s, %(purchased_at)s, %(estimated_delivery_at)s)
ON CONFLICT (order_id) DO UPDATE SET
    customer_id           = COALESCE(core.fact_order.customer_id, EXCLUDED.customer_id),
    purchased_at          = COALESCE(core.fact_order.purchased_at, EXCLUDED.purchased_at),
    estimated_delivery_at = COALESCE(core.fact_order.estimated_delivery_at, EXCLUDED.estimated_delivery_at)
"""

_STUB_SELLER = """
INSERT INTO core.dim_seller (seller_id, is_inferred) VALUES (%s, true)
ON CONFLICT (seller_id) DO NOTHING
"""

_STUB_PRODUCT = """
INSERT INTO core.dim_product (product_id, category_key, is_missing_category, is_inferred)
VALUES (%s, '__unknown__', true, true)
ON CONFLICT (product_id) DO NOTHING
"""

_UPSERT_ITEM = """
INSERT INTO core.fact_order_item (order_id, order_item_id, product_id, seller_id, shipping_limit_at, price,
                                  freight_value)
VALUES (%(order_id)s, %(order_item_id)s, %(product_id)s, %(seller_id)s, %(shipping_limit_at)s, %(price)s,
        %(freight_value)s)
ON CONFLICT (order_id, order_item_id) DO UPDATE SET
    product_id        = EXCLUDED.product_id,
    seller_id         = EXCLUDED.seller_id,
    shipping_limit_at = EXCLUDED.shipping_limit_at,
    price             = EXCLUDED.price,
    freight_value     = EXCLUDED.freight_value
"""

_UPSERT_PAYMENT = """
INSERT INTO core.fact_order_payment (order_id, payment_sequential, payment_type, payment_installments,
                                     payment_value)
VALUES (%(order_id)s, %(payment_sequential)s, %(payment_type)s, %(payment_installments)s, %(payment_value)s)
ON CONFLICT (order_id, payment_sequential) DO UPDATE SET
    payment_type         = EXCLUDED.payment_type,
    payment_installments = EXCLUDED.payment_installments,
    payment_value        = EXCLUDED.payment_value
"""

_UPSERT_REVIEW = """
INSERT INTO core.fact_order_review (review_id, order_id, review_score, review_comment_title,
                                    review_comment_message, has_text, review_created_at, review_answered_at)
VALUES (%(review_id)s, %(order_id)s, %(review_score)s, %(review_comment_title)s, %(review_comment_message)s,
        %(review_comment_message)s IS NOT NULL, %(review_created_at)s, %(review_answered_at)s)
ON CONFLICT (review_id, order_id) DO UPDATE SET
    review_score           = EXCLUDED.review_score,
    review_comment_title   = EXCLUDED.review_comment_title,
    review_comment_message = EXCLUDED.review_comment_message,
    has_text               = EXCLUDED.has_text,
    review_created_at      = EXCLUDED.review_created_at,
    review_answered_at     = EXCLUDED.review_answered_at
"""

_LOCK_ORDER = "SELECT order_status FROM core.fact_order WHERE order_id = %s FOR UPDATE"

_UPDATE_STATUS = """
UPDATE core.fact_order SET
    approved_at           = COALESCE(approved_at, %(approved_at)s),
    delivered_carrier_at  = COALESCE(delivered_carrier_at, %(delivered_carrier_at)s),
    delivered_customer_at = COALESCE(delivered_customer_at, %(delivered_customer_at)s),
    order_status          = CASE WHEN %(advance)s THEN %(order_status)s ELSE order_status END
WHERE order_id = %(order_id)s
"""

_INSERT_REPLAY = """
INSERT INTO ops.replay_runs (replay_id, cutoff, events_total, orders_total, expected, received_at)
VALUES (%(replay_id)s, %(cutoff)s, %(events_total)s, %(orders_total)s, %(expected)s,
        now() AT TIME ZONE 'utc')
ON CONFLICT (replay_id) DO NOTHING
"""


def _created(cur, envelope: dict) -> str:
    payload = envelope["payload"]
    cur.execute(_UPSERT_CUSTOMER, payload["customer"])
    order = {"estimated_delivery_at": None, **payload["order"]}
    cur.execute(_UPSERT_ORDER, order)
    for item in payload["items"]:
        cur.execute(_STUB_SELLER, (item["seller_id"],))
        cur.execute(_STUB_PRODUCT, (item["product_id"],))
        cur.execute(_UPSERT_ITEM, {"order_id": order["order_id"], "shipping_limit_at": None, **item})
    return STATUS_APPLIED


def _payment(cur, envelope: dict) -> str:
    cur.execute(_UPSERT_PAYMENT, {"order_id": envelope["order_id"], **envelope["payload"]})
    return STATUS_APPLIED


def _review(cur, envelope: dict) -> str:
    payload = {"review_comment_title": None, "review_comment_message": None, "review_answered_at": None,
               **envelope["payload"]}
    cur.execute(_UPSERT_REVIEW, {"order_id": envelope["order_id"], **payload})
    return STATUS_APPLIED


def _status_changed(cur, envelope: dict) -> str:
    """Метки времени заполняются всегда, статус - только при строго большем ранге (коммутативно)."""
    order_id = envelope["order_id"]
    cur.execute(_LOCK_ORDER, (order_id,))
    row = cur.fetchone()
    if row is None:
        raise ApplyError(f"order {order_id} not found")
    payload = {"approved_at": None, "delivered_carrier_at": None, "delivered_customer_at": None,
               **envelope["payload"]}
    advance = STATUS_RANK[payload["order_status"]] > STATUS_RANK.get(row[0], STATUS_RANK["unknown"])
    cur.execute(_UPDATE_STATUS, {**payload, "order_id": order_id, "advance": advance})
    return STATUS_APPLIED if advance else STATUS_SKIPPED


def _replay(cur, envelope: dict) -> str:
    payload = envelope["payload"]
    cur.execute(_INSERT_REPLAY, {**payload, "expected": Json(payload["expected"])})
    return STATUS_APPLIED


_HANDLERS = {
    TYPE_CREATED: _created,
    TYPE_PAYMENT: _payment,
    TYPE_STATUS: _status_changed,
    TYPE_REVIEW: _review,
    TYPE_REPLAY: _replay,
}

# Ошибки данных события; остальные ошибки БД (сеть, пересборка схем) поднимаются и повторяют пачку целиком.
_APPLY_ERRORS = (ApplyError, IntegrityError, DataError, KeyError, ValueError, TypeError)


def _apply_one(cur, incoming: Incoming, result: BatchResult) -> None:
    envelope = incoming.envelope
    cur.execute(_INSERT_LANDING, (
        envelope["event_id"], incoming.topic, incoming.partition, incoming.offset, envelope["order_id"],
        envelope["type"], envelope["schema_version"], Json(envelope["payload"]), envelope["event_ts"],
        envelope["produced_at"],
    ))
    if cur.rowcount == 1:
        result.new_events += 1
    else:
        cur.execute("SELECT status FROM landing.events WHERE event_id = %s", (envelope["event_id"],))
        if cur.fetchone()[0] in _DONE:
            result.duplicates += 1
            return
    if result.last_event_ts is None or envelope["event_ts"] > result.last_event_ts:
        result.last_event_ts = envelope["event_ts"]

    cur.execute("SAVEPOINT apply_event")
    try:
        status = _HANDLERS[envelope["type"]](cur, envelope)
    except _APPLY_ERRORS as exc:
        cur.execute("ROLLBACK TO SAVEPOINT apply_event")
        cur.execute("RELEASE SAVEPOINT apply_event")
        message = f"{type(exc).__name__}: {exc}".strip()[:ERROR_MAX]
        cur.execute("UPDATE landing.events SET status = %s, error = %s WHERE event_id = %s",
                    (STATUS_ERROR, message, envelope["event_id"]))
        result.errors.append((incoming, message))
        return
    cur.execute("RELEASE SAVEPOINT apply_event")
    cur.execute("UPDATE landing.events SET status = %s, error = NULL WHERE event_id = %s",
                (status, envelope["event_id"]))
    if status == STATUS_SKIPPED:
        result.skipped_stale += 1
    else:
        result.applied += 1
    if envelope["type"] == TYPE_REPLAY:
        result.replay_seen = True


def apply_batch(conn, events) -> BatchResult:
    """Применяет валидные события (конверты dict или Incoming) в порядке списка; COMMIT делает вызывающий."""
    result = BatchResult()
    with conn.cursor() as cur:
        for event in events:
            _apply_one(cur, event if isinstance(event, Incoming) else Incoming(event), result)
    return result
