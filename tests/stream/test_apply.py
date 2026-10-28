"""K2-T5: apply_batch на временной БД (A-8..A-11). В marketplace тесты ничего не пишут.

Фикстура создаёт БД `capibara_t5_<hex>`, ставит в неё пустые raw-таблицы (структура читается из marketplace)
и собирает текущие SQL-файлы без проверок DQ; удаляет БД в конце. Нет БД/роли ingestor - skip.
"""
import os
import uuid
from datetime import datetime
from pathlib import Path

import pytest

psycopg2 = pytest.importorskip("psycopg2")

from stream.common import make_envelope  # noqa: E402
from stream.ingestor.apply import apply_batch  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BASE = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": int(os.getenv("PGPORT", "5432")),
    "password": os.getenv("PGPASSWORD", "hack"),
}
ADMIN_USER = os.getenv("PGUSER", "hack")
MAIN_DB = os.getenv("PGDATABASE", "marketplace")
TS = datetime(2018, 1, 1, 10, 0, 0)


def _model_sql() -> str:
    """Без DQ для пустого raw и глобальных ролей, чтобы не менять кластер."""
    excluded = {"001_roles.sql", "810_dq_checks.sql", "890_dq_run.sql"}
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted((ROOT / "sql").rglob("*.sql"))
                     if path.name not in excluded)


def _connect(dbname, user=ADMIN_USER, password=None):
    return psycopg2.connect(dbname=dbname, user=user, **{**BASE, "password": password or BASE["password"]})


@pytest.fixture(scope="module")
def temp_db():
    name = f"capibara_t5_{uuid.uuid4().hex[:8]}"
    try:
        main = _connect(MAIN_DB)
    except psycopg2.OperationalError as exc:
        pytest.skip(f"БД недоступна: {exc}")
    main.set_session(readonly=True, autocommit=True)
    with main.cursor() as cur:  # только чтение: структура raw
        cur.execute("""SELECT table_name, column_name FROM information_schema.columns
                       WHERE table_schema = 'raw' ORDER BY table_name, ordinal_position""")
        raw_columns = cur.fetchall()
        cur.execute("SELECT rolcreatedb OR rolsuper FROM pg_roles WHERE rolname = current_user")
        can_create = cur.fetchone()[0]
    main.close()
    if not raw_columns or not can_create:
        pytest.skip("нет raw в marketplace или нет права CREATE DATABASE")

    admin = _connect("postgres")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{name}"')
    try:
        build = _connect(name)
        build.autocommit = True
        with build.cursor() as cur:
            cur.execute("CREATE SCHEMA raw")
            tables: dict[str, list[str]] = {}
            for table, column in raw_columns:
                tables.setdefault(table, []).append(column)
            for table, columns in tables.items():
                cols = ", ".join(f'"{c}" text' for c in columns)
                cur.execute(f'CREATE TABLE raw."{table}" ({cols})')
            cur.execute(_model_sql())
        build.close()
        try:
            probe = _connect(name, "ingestor", "ingestor")
            probe.close()
        except psycopg2.OperationalError as exc:
            pytest.skip(f"роль ingestor недоступна: {exc}")
        yield name
    finally:
        with admin.cursor() as cur:
            cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (name,))
            cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
        admin.close()


@pytest.fixture()
def conn(temp_db):
    connection = _connect(temp_db, "ingestor", "ingestor")
    yield connection
    connection.rollback()
    connection.close()


# --- построители событий ---

def _ids():
    tag = uuid.uuid4().hex[:12]
    return {"order": f"o{tag}", "customer": f"c{tag}", "seller": f"s{tag}", "product": f"p{tag}"}


def created(ids, moment=TS):
    payload = {
        "order": {"order_id": ids["order"], "customer_id": ids["customer"], "order_status": "created",
                  "purchased_at": moment.isoformat(), "estimated_delivery_at": None},
        "customer": {"customer_id": ids["customer"], "customer_unique_id": "u" + ids["customer"],
                     "zip_prefix": "01000", "city": "Sao Paulo", "state": "SP"},
        "items": [{"order_item_id": 1, "product_id": ids["product"], "seller_id": ids["seller"],
                   "price": "10.50", "freight_value": "2.00"}],
    }
    return make_envelope("order.created", ids["order"], moment, payload)


def payment(ids):
    payload = {"payment_sequential": 1, "payment_type": "credit_card", "payment_installments": 1,
               "payment_value": "12.50"}
    return make_envelope("payment.captured", ids["order"], TS, payload, "1")


def status(ids, name, **labels):
    return make_envelope("order.status_changed", ids["order"], TS, {"order_status": name, **labels}, name)


def _order_state(conn, order_id):
    with conn.cursor() as cur:
        cur.execute("""SELECT order_status, approved_at, delivered_customer_at FROM core.fact_order
                       WHERE order_id = %s""", (order_id,))
        return cur.fetchone()


def _fingerprint(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT (SELECT COUNT(*) FROM core.fact_order), (SELECT COUNT(*) FROM core.fact_order_item),
                              (SELECT COUNT(*) FROM core.fact_order_payment), (SELECT COUNT(*) FROM core.fact_order_review),
                              (SELECT COALESCE(SUM(price), 0) FROM core.fact_order_item),
                              (SELECT COALESCE(SUM(payment_value), 0) FROM core.fact_order_payment),
                              (SELECT COUNT(*) FROM landing.events)""")
        return cur.fetchone()


def test_a8_repeat_batch_changes_nothing(conn):
    ids = _ids()
    review = make_envelope("review.posted", ids["order"], TS, {
        "review_id": "r" + ids["order"], "review_score": 5, "review_created_at": TS.isoformat()}, "r")
    batch = [created(ids), payment(ids), status(ids, "approved", approved_at="2018-01-01T11:00:00"), review]
    first = apply_batch(conn, batch)
    conn.commit()
    assert first.new_events == 4 and first.duplicates == 0 and not first.errors
    before = _fingerprint(conn)

    second = apply_batch(conn, batch)
    conn.commit()
    assert second.duplicates == 4 and second.new_events == 0 and not second.errors
    assert _fingerprint(conn) == before
    assert _order_state(conn, ids["order"])[0] == "approved"


def test_a9_stale_status_and_reverse_order_converge(conn):
    delivered_labels = {"delivered_customer_at": "2018-01-05T10:00:00"}
    approved_labels = {"approved_at": "2018-01-01T11:00:00"}

    forward, backward = _ids(), _ids()
    result = apply_batch(conn, [created(forward), status(forward, "delivered", **delivered_labels),
                                status(forward, "approved", **approved_labels)])
    assert result.skipped_stale == 1 and not result.errors
    apply_batch(conn, [created(backward), status(backward, "approved", **approved_labels),
                       status(backward, "delivered", **delivered_labels)])
    conn.commit()

    state_forward = _order_state(conn, forward["order"])
    assert state_forward[0] == "delivered"
    assert state_forward[1] is not None  # approved_at заполнен несмотря на устаревший статус
    assert state_forward == _order_state(conn, backward["order"])
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM landing.events WHERE order_id = %s AND type = 'order.status_changed' "
                    "ORDER BY status", (forward["order"],))
        assert [row[0] for row in cur.fetchall()] == ["applied", "skipped_stale"]


def test_a10_unknown_seller_and_product_become_inferred_stubs(conn):
    ids = _ids()
    result = apply_batch(conn, [created(ids)])
    conn.commit()
    assert not result.errors
    with conn.cursor() as cur:
        cur.execute("SELECT is_inferred FROM core.dim_seller WHERE seller_id = %s", (ids["seller"],))
        assert cur.fetchone() == (True,)
        cur.execute("SELECT is_inferred FROM core.dim_product WHERE product_id = %s", (ids["product"],))
        assert cur.fetchone() == (True,)
        cur.execute("SELECT price FROM core.fact_order_item WHERE order_id = %s", (ids["order"],))
        assert [str(row[0]) for row in cur.fetchall()] == ["10.50"]


def test_a11_status_of_missing_order_goes_to_error_rest_applied(conn):
    good, ghost = _ids(), _ids()
    bad_event = status(ghost, "approved", approved_at="2018-01-01T11:00:00")
    result = apply_batch(conn, [created(good), bad_event, payment(good)])
    conn.commit()
    assert len(result.errors) == 1
    assert result.errors[0][0].envelope["event_id"] == bad_event["event_id"]
    assert result.applied == 2
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM landing.events WHERE event_id = %s", (bad_event["event_id"],))
        assert cur.fetchone() == ("error",)
        cur.execute("SELECT COUNT(*) FROM core.fact_order_payment WHERE order_id = %s", (good["order"],))
        assert cur.fetchone() == (1,)
