"""CSV Olist -> упорядоченный список событий (K2 §4 п.1-3).

Нормализация как в sql/20_staging: NULLIF(TRIM(x), ''), статус и тип оплаты в нижнем регистре.
Аномалии не правим: значения как в CSV. Событие хранит ссылку на данные, конверт собирается при отправке.
"""

import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, NamedTuple

from stream.common import (
    STATUS_RANK,
    TYPE_CREATED,
    TYPE_PAYMENT,
    TYPE_REVIEW,
    TYPE_STATUS,
    make_envelope,
)

KIND_CREATED, KIND_PAYMENT, KIND_STATUS, KIND_REVIEW = 0, 1, 2, 3
_TYPE_BY_KIND = {
    KIND_CREATED: TYPE_CREATED,
    KIND_PAYMENT: TYPE_PAYMENT,
    KIND_STATUS: TYPE_STATUS,
    KIND_REVIEW: TYPE_REVIEW,
}
# метка времени заказа -> статус, который она подтверждает
_STATUS_LABELS = (
    ("approved_at", "approved"),
    ("delivered_carrier_at", "shipped"),
    ("delivered_customer_at", "delivered"),
)


class Event(NamedTuple):
    sort_ts: datetime  # позиция в потоке: max(event_ts, purchased_at), чтобы created заказа шёл первым
    kind: int
    sub: str  # детерминированный тай-брейк внутри заказа
    order_id: str
    event_ts: datetime
    discriminator: str  # часть ключа uuid5 (K0 §4.1)
    data: Any  # данные для payload

    @property
    def type(self) -> str:
        return _TYPE_BY_KIND[self.kind]


@dataclass
class OrderRec:
    row: dict
    customer: dict
    items: list


@dataclass
class Replay:
    events: list[Event]
    orders_total: int


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


def _ts(value: str | None) -> datetime | None:
    cleaned = _clean(value)
    return datetime.fromisoformat(cleaned) if cleaned else None


def _money(value: str) -> str:
    return f"{Decimal(value.strip()):.2f}"


def _read(data_dir: Path, name: str):
    with open(data_dir / f"olist_{name}_dataset.csv", newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


def _order_row(raw: dict) -> dict:
    status = (_clean(raw["order_status"]) or "unknown").lower()
    return {
        "order_id": _clean(raw["order_id"]),
        "customer_id": _clean(raw["customer_id"]),
        "final_status": status if status in STATUS_RANK else "unknown",
        "purchased_at": _ts(raw["order_purchase_timestamp"]),
        "approved_at": _ts(raw["order_approved_at"]),
        "delivered_carrier_at": _ts(raw["order_delivered_carrier_date"]),
        "delivered_customer_at": _ts(raw["order_delivered_customer_date"]),
        "estimated_delivery_at": _ts(raw["order_estimated_delivery_date"]),
    }


def status_events(row: dict) -> list[tuple[str, datetime, dict]]:
    """Статусные события заказа: (статус, event_ts, метки в payload); K2 §4 п.2.

    Метка даёт событие своего статуса, если ранг не выше финального. Метки выше финального и сам финальный
    статус, не подтверждённый меткой, уходят одним событием финального статуса.
    """
    final = row["final_status"]
    if final == "created":
        return []
    by_status: dict[str, dict] = {}
    leftover: dict[str, datetime] = {}
    for field, status in _STATUS_LABELS:
        moment = row[field]
        if moment is None:
            continue
        if STATUS_RANK[status] <= STATUS_RANK[final]:
            by_status.setdefault(status, {})[field] = moment
        else:
            leftover[field] = moment
    stamps = {status: max(labels.values()) for status, labels in by_status.items()}
    if final not in by_status:
        by_status[final] = {}
        stamps[final] = max([*stamps.values(), *leftover.values()], default=row["purchased_at"])
    by_status[final].update(leftover)
    return [(status, stamps[status], labels) for status, labels in by_status.items()]


def build_replay(data_dir: Path, cutoff: date | None = None) -> Replay:
    """События заказов с purchased_at >= cutoff (без cutoff - весь датасет), в порядке отправки."""
    floor = datetime.combine(cutoff, datetime.min.time()) if cutoff else None
    orders = {}
    for raw in _read(data_dir, "orders"):
        row = _order_row(raw)
        if floor is None or row["purchased_at"] >= floor:
            orders[row["order_id"]] = OrderRec(row, {}, [])

    wanted_customers = {rec.row["customer_id"]: rec for rec in orders.values()}
    for raw in _read(data_dir, "customers"):
        rec = wanted_customers.get(_clean(raw["customer_id"]))
        if rec is not None:
            rec.customer = {
                "customer_id": _clean(raw["customer_id"]),
                "customer_unique_id": _clean(raw["customer_unique_id"]),
                "zip_prefix": _clean(raw["customer_zip_code_prefix"]) or "",
                "city": _clean(raw["customer_city"]) or "",
                "state": _clean(raw["customer_state"]) or "",
            }
    for raw in _read(data_dir, "order_items"):
        rec = orders.get(_clean(raw["order_id"]))
        if rec is not None:
            shipping = _ts(raw["shipping_limit_date"])
            item = {
                "order_item_id": int(raw["order_item_id"]),
                "product_id": _clean(raw["product_id"]),
                "seller_id": _clean(raw["seller_id"]),
                "price": _money(raw["price"]),
                "freight_value": _money(raw["freight_value"]),
            }
            if shipping is not None:
                item["shipping_limit_at"] = shipping
            rec.items.append(item)
    for rec in orders.values():
        rec.items.sort(key=lambda item: item["order_item_id"])

    events: list[Event] = []
    for order_id, rec in orders.items():
        purchased = rec.row["purchased_at"]
        events.append(Event(purchased, KIND_CREATED, "", order_id, purchased, "", rec))
        for status, moment, labels in status_events(rec.row):
            rank = STATUS_RANK[status]
            events.append(Event(max(moment, purchased), KIND_STATUS, f"{rank}:{status}", order_id, moment,
                                status, {"order_status": status, **labels}))

    for raw in _read(data_dir, "order_payments"):
        order_id = _clean(raw["order_id"])
        rec = orders.get(order_id)
        if rec is not None:
            sequential = int(raw["payment_sequential"])
            purchased = rec.row["purchased_at"]
            events.append(Event(purchased, KIND_PAYMENT, f"{sequential:06d}", order_id, purchased, str(sequential), {
                "payment_sequential": sequential,
                "payment_type": (_clean(raw["payment_type"]) or "").lower(),
                "payment_installments": int(raw["payment_installments"]),
                "payment_value": _money(raw["payment_value"]),
            }))
    for raw in _read(data_dir, "order_reviews"):
        order_id = _clean(raw["order_id"])
        rec = orders.get(order_id)
        if rec is not None:
            created = _ts(raw["review_creation_date"])
            review_id = _clean(raw["review_id"])
            events.append(Event(max(created, rec.row["purchased_at"]), KIND_REVIEW, review_id, order_id, created,
                                review_id, {
                "review_id": review_id,
                "review_score": int(raw["review_score"]),
                "review_comment_title": _clean(raw["review_comment_title"]),
                "review_comment_message": _clean(raw["review_comment_message"]),
                "review_created_at": created,
                "review_answered_at": _ts(raw["review_answer_timestamp"]),
            }))

    events.sort(key=lambda e: (e.sort_ts, e.kind, e.order_id, e.sub))
    return Replay(events, len(orders))


def _fmt(moment: datetime | None) -> str | None:
    return None if moment is None else moment.strftime("%Y-%m-%dT%H:%M:%S")


def _fmt_fields(fields: dict) -> dict:
    return {key: _fmt(value) if isinstance(value, datetime) else value for key, value in fields.items()}


def payload(event: Event) -> dict:
    data = event.data
    if event.kind == KIND_CREATED:
        row = data.row
        return {
            "order": {
                "order_id": row["order_id"],
                "customer_id": row["customer_id"],
                "order_status": "created",
                "purchased_at": _fmt(row["purchased_at"]),
                "estimated_delivery_at": _fmt(row["estimated_delivery_at"]),
            },
            "customer": data.customer,
            "items": [_fmt_fields(item) for item in data.items],
        }
    return _fmt_fields(data)


def envelope(event: Event, produced_at: str | None = None) -> dict:
    return make_envelope(event.type, event.order_id, event.event_ts, payload(event), event.discriminator, produced_at)
