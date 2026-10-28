"""Синтетические события истории; транзакции откатываются, marketplace не изменяется."""
import os
import uuid
from datetime import datetime
from pathlib import Path

import pytest

psycopg2 = pytest.importorskip("psycopg2")

from stream.common import dumps, load_validator, make_envelope
from stream.ingestor.apply import apply_batch
from stream.ingestor.validate import parse_message

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def connection():
    database = os.getenv("PGDATABASE", "marketplace")
    if database == "marketplace":
        pytest.skip("история проверяется только на отдельной БД")
    conn = psycopg2.connect(dbname=database, host=os.getenv("PGHOST", "localhost"),
                            port=os.getenv("PGPORT", "5432"), user=os.getenv("PGUSER", "hack"),
                            password=os.getenv("PGPASSWORD", "hack"))
    yield conn
    conn.rollback()
    conn.close()


def change(kind, moment, payload, discriminator=None):
    return make_envelope(kind, None, datetime.fromisoformat(moment), payload,
                         discriminator or ":".join([moment, *map(str, payload.values())]))


def created(moment, seller, product, person, state="SP"):
    order, customer = uuid.uuid4().hex, uuid.uuid4().hex
    return make_envelope("order.created", order, datetime.fromisoformat(moment), {
        "order": {"order_id": order, "customer_id": customer, "order_status": "delivered",
                  "purchased_at": moment},
        "customer": {"customer_id": customer, "customer_unique_id": person,
                     "zip_prefix": "01000", "city": "Original", "state": state},
        "items": [{"order_item_id": 1, "seller_id": seller, "product_id": product,
                   "price": "10.00", "freight_value": "1.00"}],
    })


def test_new_events_validate():
    validator = load_validator()
    category = change("product.category_changed", "2020-01-02T00:00:00", {
        "seller_id": "a" * 32, "product_id": "b" * 32, "category_key": "__unknown__"})
    address = change("customer.address_changed", "2020-01-02T00:00:00", {
        "customer_unique_id": "c" * 32, "zip_prefix": "20000", "city": "New city", "state": "RJ"})
    for event in (category, address):
        assert parse_message(dumps(event), validator) == event
        event["order_id"] = "d" * 32
        assert not validator.is_valid(event)


def test_category_as_of_out_of_order_and_repeated(connection):
    with connection.cursor() as cur:
        cur.execute("SELECT category_key FROM core.dim_category WHERE category_key <> '__unknown__' ORDER BY category_key LIMIT 2")
        first, second = [row[0] for row in cur.fetchall()]
    seller, product, person = [uuid.uuid4().hex for _ in range(3)]
    orders = [created(f"2020-01-0{day}T00:00:00", seller, product, person) for day in (1, 3, 5)]
    updates = [change("product.category_changed", "2020-01-04T00:00:00", {
        "seller_id": seller, "product_id": product, "category_key": second}),
        change("product.category_changed", "2020-01-02T00:00:00", {
        "seller_id": seller, "product_id": product, "category_key": first})]
    result = apply_batch(connection, [*orders, *updates])
    assert not result.errors
    assert apply_batch(connection, updates).duplicates == 2
    with connection.cursor() as cur:
        for event, expected in zip(orders, ("__unknown__", first, second)):
            cur.execute("SELECT category_key FROM mart.v_sales_item WHERE order_id = %s", (event["order_id"],))
            assert cur.fetchone() == (expected,)
        cur.execute("SELECT category_main FROM mart.v_delivery WHERE order_id = %s", (orders[-1]["order_id"],))
        assert cur.fetchone()[0] is not None
        cur.execute("SELECT valid_from, valid_to FROM mart.v_product_category_history WHERE seller_id = %s ORDER BY valid_from", (seller,))
        intervals = cur.fetchall()
        assert intervals[0][1] == intervals[1][0] and intervals[1][1] is None


def test_customer_move_never_changes_order_address(connection):
    seller, product, person = [uuid.uuid4().hex for _ in range(3)]
    old = created("2020-01-01T00:00:00", seller, product, person)
    new = created("2020-01-03T00:00:00", seller, product, person, state="RJ")
    # Повторный customer_id не обновляет core.dim_customer; адрес нового заказа
    # при этом должен браться из его собственного события.
    new["payload"]["order"]["customer_id"] = old["payload"]["order"]["customer_id"]
    new["payload"]["customer"]["customer_id"] = old["payload"]["customer"]["customer_id"]
    move = change("customer.address_changed", "2020-01-02T00:00:00", {
        "customer_unique_id": person, "zip_prefix": "20000", "city": "New city", "state": "RJ"})
    assert not apply_batch(connection, [old, move, new]).errors
    with connection.cursor() as cur:
        for event, expected in [(old, "SP"), (new, "RJ")]:
            cur.execute("SELECT state FROM mart.v_order_address WHERE order_id = %s", (event["order_id"],))
            assert cur.fetchone() == (expected,)
            for view in ("mart.v_sales_item", "mart.order_summary"):
                cur.execute(f"SELECT customer_state FROM {view} WHERE order_id = %s", (event["order_id"],))
                assert cur.fetchone() == (expected,)
        cur.execute("SELECT state FROM mart.v_customer_address_history WHERE customer_unique_id = %s", (person,))
        assert cur.fetchone() == ("RJ",)
        # Полная пересборка не удаляет версии и снимки.
        for path in sorted((ROOT / "sql").rglob("*.sql")):
            cur.execute(path.read_text())
        cur.execute("SELECT state FROM ops.order_address_snapshot WHERE order_id = %s", (old["order_id"],))
        assert cur.fetchone() == ("SP",)
        # Синтетический заказ отсутствует в пересобранном core и не попадает в витрину.
        cur.execute("SELECT state FROM mart.v_order_address WHERE order_id = %s", (old["order_id"],))
        assert cur.fetchone() is None
        cur.execute("SELECT state FROM mart.v_customer_address_history WHERE customer_unique_id = %s", (person,))
        assert cur.fetchone() == ("RJ",)
