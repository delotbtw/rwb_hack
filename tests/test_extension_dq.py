"""Q5 baseline stays independent of category history; all changes roll back."""
import os
import uuid
from pathlib import Path

import pytest

psycopg2 = pytest.importorskip("psycopg2")

ROOT = Path(__file__).resolve().parents[1]


def test_history_changes_q5_without_breaking_strict_baseline():
    # A full rebuild takes DDL locks: require a dedicated, disposable database.
    database = os.getenv("DQ_TEST_DATABASE")
    if not database or database == "marketplace":
        pytest.skip("set DQ_TEST_DATABASE to a dedicated database loaded with the baseline dataset")
    conn = psycopg2.connect(dbname=database, host=os.getenv("PGHOST", "localhost"),
                            port=os.getenv("PGPORT", "5432"), user=os.getenv("PGUSER", "hack"),
                            password=os.getenv("PGPASSWORD", "hack"))
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT cutoff FROM ops.build_params WHERE id = 1")
            assert cur.fetchone() == (None,)
            cur.execute("SELECT category_key, revenue FROM mart.v_category_sales")
            before = dict(cur.fetchall())
            cur.execute("""
                SELECT i.seller_id, i.product_id, o.purchased_at, p.category_key,
                       (SELECT c.category_key FROM core.dim_category c
                        WHERE c.category_key <> p.category_key ORDER BY c.category_key LIMIT 1)
                FROM core.fact_order_item i
                JOIN core.fact_order o ON o.order_id = i.order_id
                JOIN core.dim_product p ON p.product_id = i.product_id
                WHERE o.order_status = 'delivered' AND i.price > 0
                  AND o.purchased_at >= DATE '2016-09-01' AND o.purchased_at < DATE '2018-09-01'
                  AND NOT EXISTS (SELECT 1 FROM ops.product_category_history h
                                  WHERE h.seller_id = i.seller_id AND h.product_id = i.product_id)
                ORDER BY i.order_id, i.order_item_id LIMIT 1
            """)
            seller, product, purchased_at, original, replacement = cur.fetchone()
            assert replacement and replacement != original
            cur.execute("""
                INSERT INTO ops.product_category_history
                    (seller_id, product_id, valid_from, category_key, event_id)
                VALUES (%s, %s, %s, %s, %s)
            """, (seller, product, purchased_at, replacement, str(uuid.uuid4())))
            cur.execute("SET LOCAL capibara.dq_mode = 'strict'")
            for path in sorted((ROOT / "sql").rglob("*.sql")):
                cur.execute(path.read_text())
            cur.execute("SELECT check_id, expected, actual, passed FROM mart.dq_result WHERE check_id IN ('Q5-CTRL', 'DQ-12')")
            checks = {row[0]: row[1:] for row in cur.fetchall()}
            assert checks["Q5-CTRL"] == ("74 / 1233131.72 / 13221498.11", "74 / 1233131.72 / 13221498.11", True)
            assert checks["DQ-12"][2] is True
            cur.execute("SELECT category_key, revenue FROM mart.v_category_sales")
            after = dict(cur.fetchall())
            assert after != before
            assert sum(after.values()) == sum(before.values())
            cur.execute("SELECT SUM(revenue) FROM mart.q05_revenue_by_category")
            assert cur.fetchone()[0] == sum(before.values())
    finally:
        conn.rollback()
        conn.close()
