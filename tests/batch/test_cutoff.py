"""K3-T1: фильтр cutoff в staging и DQ (A-1..A-3).

Тест пересобирает модель в БД из PGDATABASE (сборка из sql/** одной транзакцией) и в конце
возвращает полную сборку. На общей БД `marketplace` не запускается.
"""
import datetime as dt
import os
import pathlib

import psycopg2
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CUTOFF = "2018-08-01"
FULL_ORDERS = 99_441
CUT_ORDERS = 92_909

DSN = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": os.getenv("PGPORT", "5432"),
    "dbname": os.getenv("PGDATABASE", "marketplace"),
    "user": os.getenv("PGUSER", "hack"),
    "password": os.getenv("PGPASSWORD", "hack"),
}

pytestmark = pytest.mark.skipif(
    DSN["dbname"] == "marketplace",
    reason="тест пересобирает модель: запускайте на отдельной БД (PGDATABASE)",
)

SKIP_IDS = {"DQ-03", "DQ-04", "DQ-05", "DQ-06", "DQ-07", "DQ-08", "DQ-09", "Q1-ZERO",
            "Q1-CTRL", "Q2-CTRL", "Q3-CTRL", "Q4-CTRL", "Q5-CTRL"}


def _bundle_sql() -> str:
    files = sorted((ROOT / "sql").rglob("*.sql"))
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


def _scalar(cur, sql, params=None):
    cur.execute(sql, params)
    return cur.fetchone()[0]


def _build_and_collect(cutoff):
    """Собирает модель с заданным cutoff (None = полная) и снимает метрики."""
    conn = psycopg2.connect(**DSN)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE ops.build_params SET cutoff = %s WHERE id = 1", (cutoff,))
            cur.execute(_bundle_sql())  # DQ strict: упавшая проверка = исключение, откат сборки
            snap = {
                "orders": _scalar(cur, "SELECT COUNT(*) FROM core.fact_order"),
                "max_purchase": _scalar(cur, "SELECT MAX(purchased_at) FROM core.fact_order"),
                "items": _scalar(cur, "SELECT COUNT(*) FROM core.fact_order_item"),
                "payments": _scalar(cur, "SELECT COUNT(*) FROM core.fact_order_payment"),
                "reviews": _scalar(cur, "SELECT COUNT(*) FROM core.fact_order_review"),
                "foreign_children": _scalar(cur, """
                    SELECT (SELECT COUNT(*) FROM core.fact_order_item i
                             WHERE NOT EXISTS (SELECT 1 FROM core.fact_order o WHERE o.order_id = i.order_id))
                         + (SELECT COUNT(*) FROM core.fact_order_payment p
                             WHERE NOT EXISTS (SELECT 1 FROM core.fact_order o WHERE o.order_id = p.order_id))
                         + (SELECT COUNT(*) FROM core.fact_order_review r
                             WHERE NOT EXISTS (SELECT 1 FROM core.fact_order o WHERE o.order_id = r.order_id))"""),
                "products": _scalar(cur, "SELECT COUNT(*) FROM core.dim_product"),
                "sellers": _scalar(cur, "SELECT COUNT(*) FROM core.dim_seller"),
                "customers": _scalar(cur, "SELECT COUNT(*) FROM core.dim_customer"),
                "raw_items_of_cut": _scalar(cur, """
                    SELECT COUNT(*) FROM raw.order_items i WHERE EXISTS (
                        SELECT 1 FROM raw.orders o WHERE TRIM(o.order_id) = TRIM(i.order_id)
                          AND NULLIF(TRIM(o.order_purchase_timestamp), '')::timestamp < %s::date)""", (CUTOFF,)),
                "revenue": _scalar(cur, "SELECT SUM(revenue) FROM mart.v_sales_month"),
            }
            cur.execute("SELECT check_id, expected, passed FROM mart.dq_result ORDER BY check_id")
            snap["dq"] = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
        return snap
    finally:
        conn.close()


@pytest.fixture(scope="module")
def builds():
    full = _build_and_collect(None)
    cut = _build_and_collect(CUTOFF)
    yield {"full": full, "cut": cut}
    _build_and_collect(None)


def test_a1_full_build_unchanged(builds):
    full = builds["full"]
    assert full["orders"] == FULL_ORDERS
    assert all(passed for _, passed in full["dq"].values())
    assert not any(exp == "skip: cutoff" for exp, _ in full["dq"].values())
    assert full["dq"]["Q1-CTRL"][0] == "24 / 13221498.11"
    assert str(full["revenue"]) == "13221498.11"


def test_a2_cutoff_filters_orders_and_children(builds):
    full, cut = builds["full"], builds["cut"]
    assert cut["orders"] == CUT_ORDERS
    assert cut["max_purchase"] < dt.datetime(2018, 8, 1)
    assert cut["foreign_children"] == 0
    assert cut["items"] == cut["raw_items_of_cut"] < full["items"]
    assert cut["payments"] < full["payments"]
    assert cut["reviews"] < full["reviews"]


def test_a2_dimensions_unchanged(builds):
    full, cut = builds["full"], builds["cut"]
    for key in ("products", "sellers", "customers"):
        assert cut[key] == full[key], key


def test_a3_cutoff_keeps_build_and_dq(builds):
    dq = builds["cut"]["dq"]  # сборка дошла до конца: strict-гейт не откатил транзакцию
    assert all(passed for _, passed in dq.values())
    for check_id in ("DQ-01-orders", "DQ-01-order_items", "DQ-01-order_payments", "DQ-01-order_reviews",
                     "DQ-10", "DQ-11", "DQ-12"):
        expected, passed = dq[check_id]
        assert passed and expected != "skip: cutoff", check_id
    for check_id in SKIP_IDS:
        assert dq[check_id] == ("skip: cutoff", True), check_id
