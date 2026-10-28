"""Q6–Q10: проверки полной сборки в отдельной БД (PGDATABASE != marketplace)."""

import os
from decimal import Decimal

import psycopg2
import pytest

from app.api.catalog import load_catalog
from app.api.query_builder import run_query
from app.api.schemas import QueryRequest


@pytest.fixture
def conn():
    database = os.getenv("PGDATABASE", "marketplace")
    if database == "marketplace":
        pytest.skip("для Q6–Q10 нужна отдельная полная БД: PGDATABASE=mp_extension")
    connection = psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"), port=os.getenv("PGPORT", "5432"),
        dbname=database, user=os.getenv("PGUSER", "hack"),
        password=os.getenv("PGPASSWORD", "hack"),
    )
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT cutoff FROM ops.build_params WHERE id = 1")
            assert cur.fetchone()[0] is None, "контроли ноутбука требуют полной сборки"
        yield connection
    finally:
        connection.rollback()
        connection.close()


def rows(conn, query, params=None):
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def test_q6_observed_price_history_preserves_item_units(conn):
    # Q6: выбор по distinct price и product_id ASC, все статусы, без fan-out.
    product = rows(conn, """
        SELECT product_id FROM core.fact_order_item GROUP BY product_id
        ORDER BY COUNT(DISTINCT price) DESC, product_id LIMIT 1
    """)[0][0]
    assert product == "437c05a395e9e47f9762e677a7068ce7"
    assert rows(conn, """
        SELECT product_id, COUNT(DISTINCT price), SUM(units)
        FROM mart.v_product_price_history GROUP BY product_id
    """) == [(product, 31, Decimal(155))]
    expected = rows(conn, """
        SELECT o.purchased_at::date, i.price, COUNT(*)
        FROM core.fact_order_item i
        LEFT JOIN core.fact_order o ON o.order_id = i.order_id
        WHERE i.product_id = %s GROUP BY o.purchased_at::date, i.price
        ORDER BY 1, 2
    """, (product,))
    assert rows(conn, """
        SELECT purchase_date, price, units FROM mart.v_product_price_history ORDER BY 1, 2
    """) == expected


def test_q7_delivery_denominator_and_calendar_lateness(conn):
    # Q7: порог 500 по валидным delivered, покрытие остальных штатов сохранено.
    assert rows(conn, """
        SELECT SUM(valid_orders), COUNT(*) FILTER (WHERE valid_orders >= 500)
        FROM mart.v_delivery_by_state
    """) == [(Decimal(96470), 17)]
    expected = rows(conn, """
        SELECT c.state_normalized, COUNT(*), AVG(EXTRACT(EPOCH FROM
            o.delivered_customer_at - o.purchased_at) / 86400),
            COUNT(*) FILTER (WHERE o.delivered_customer_at::date > o.estimated_delivery_at::date)
        FROM core.fact_order o
        LEFT JOIN core.dim_customer c ON c.customer_id = o.customer_id
        WHERE o.order_status = 'delivered' AND o.purchased_at IS NOT NULL
            AND o.delivered_customer_at >= o.purchased_at AND o.estimated_delivery_at IS NOT NULL
        GROUP BY c.state_normalized ORDER BY 1
    """)
    assert rows(conn, """
        SELECT customer_state, valid_orders, mean_delivery_days, late_orders
        FROM mart.v_delivery_by_state WHERE valid_orders > 0 ORDER BY 1
    """) == expected
    for _, count, _, late, pct in rows(conn, """
        SELECT customer_state, valid_orders, mean_delivery_days, late_orders, late_pct
        FROM mart.v_delivery_by_state WHERE valid_orders > 0
    """):
        assert abs(pct - Decimal(100) * late / count) < Decimal("0.000000000001")


def test_q8_all_statuses_and_orders_without_items(conn):
    # Q8: снимок статусов содержит каждый заказ, отсутствие позиции не равно отсутствию оплаты.
    result = rows(conn, """
        SELECT SUM(orders), SUM(without_items), SUM(share_pct) FROM mart.v_order_status_snapshot
    """)[0]
    assert result[:2] == (Decimal(99441), Decimal(775))
    assert abs(result[2] - 100) < Decimal("0.000000000001")
    assert rows(conn, """
        SELECT order_status, orders, without_items FROM mart.v_order_status_snapshot ORDER BY 1
    """) == rows(conn, """
        SELECT o.order_status, COUNT(*), COUNT(*) FILTER (WHERE NOT EXISTS
            (SELECT 1 FROM core.fact_order_item i WHERE i.order_id = o.order_id))
        FROM core.fact_order o GROUP BY o.order_status ORDER BY 1
    """)


def test_q9_payment_grain_all_statuses_and_purchase_year(conn):
    # Q9: суммы и средняя рассрочка по платёжным записям без multiplication/fan-out.
    assert rows(conn, "SELECT COUNT(*) FROM mart.v_payment_context") == [(103886,)]
    assert rows(conn, """
        SELECT payment_type, COUNT(*), SUM(payment_value), AVG(payment_installments)
        FROM mart.v_payment_context GROUP BY payment_type ORDER BY 1
    """) == rows(conn, """
        SELECT payment_type, COUNT(*), SUM(payment_value), AVG(payment_installments)
        FROM core.fact_order_payment GROUP BY payment_type ORDER BY 1
    """)
    assert rows(conn, """
        SELECT customer_state, COUNT(*), SUM(payment_value), AVG(payment_installments)
        FROM mart.v_payment_context WHERE purchase_ts >= '2018-01-01'
            AND purchase_ts < '2019-01-01' GROUP BY customer_state ORDER BY 1
    """) == rows(conn, """
        SELECT c.state_normalized, COUNT(*), SUM(p.payment_value), AVG(p.payment_installments)
        FROM core.fact_order_payment p
        LEFT JOIN core.fact_order o ON o.order_id = p.order_id
        LEFT JOIN core.dim_customer c ON c.customer_id = o.customer_id
        WHERE o.purchased_at >= '2018-01-01' AND o.purchased_at < '2019-01-01'
        GROUP BY c.state_normalized ORDER BY 1
    """)


def test_q10_one_review_per_order_and_baseline_counts(conn):
    # Q10: каждый заказ имеет один голос, заказы без отзыва не становятся оценкой ноль.
    assert rows(conn, """
        SELECT COUNT(*), COUNT(DISTINCT order_id), COUNT(review_score),
            COUNT(*) FILTER (WHERE review_score IS NULL) FROM mart.v_review_delivery
    """) == [(96470, 96470, 95824, 646)]
    assert rows(conn, "SELECT score, orders FROM mart.v_review_delivery_summary ORDER BY score") == [
        (1, 9351), (2, 2921), (3, 7916), (4, 18888), (5, 56748),
    ]


def test_q10_latest_review_ties_and_null_dates(conn):
    # Q10: временные NULL идут первыми; review_id разрешает совпадения воспроизводимо.
    order = rows(conn, """
        SELECT r.order_id FROM core.fact_order_review r
        LEFT JOIN mart.order_summary o ON o.order_id = r.order_id
        WHERE o.is_valid_delivery GROUP BY r.order_id HAVING COUNT(*) > 1 LIMIT 1
    """)[0][0]
    reviews = rows(conn, """
        SELECT review_id FROM core.fact_order_review WHERE order_id = %s ORDER BY review_id
    """, (order,))
    rows(conn, """
        UPDATE core.fact_order_review SET review_answered_at = NULL,
            review_created_at = NULL, review_score = 1 WHERE order_id = %s RETURNING review_id
    """, (order,))
    rows(conn, """
        UPDATE core.fact_order_review SET review_score = 5
        WHERE order_id = %s AND review_id = %s RETURNING review_id
    """, (order, reviews[-1][0]))
    assert rows(conn, "SELECT review_score FROM mart.v_review_delivery WHERE order_id = %s", (order,)) == [(5,)]
    rows(conn, """
        UPDATE core.fact_order_review SET review_answered_at = '2019-01-01', review_score = 2
        WHERE order_id = %s AND review_id = %s RETURNING review_id
    """, (order, reviews[0][0]))
    assert rows(conn, "SELECT review_score FROM mart.v_review_delivery WHERE order_id = %s", (order,)) == [(2,)]


def test_q10_empty_score_groups_keep_unknown_means(conn):
    # Q10: даже при отсутствии отзывов сохраняются строки всех пяти оценок.
    with conn.cursor() as cur:
        cur.execute("DELETE FROM core.fact_order_review")
    assert rows(conn, """
        SELECT score, orders, mean_delivery_days, late_pct
        FROM mart.v_review_delivery_summary ORDER BY score
    """) == [(score, 0, None, None) for score in range(1, 6)]


@pytest.mark.parametrize("metric,dimension,table,expression,time_column", [
    ("observed_units", "product", "mart.v_product_price_item", "COUNT(*)", "purchase_ts"),
    ("payment_records", "payment_type", "mart.v_payment_context", "COUNT(*)", "purchase_ts"),
    ("rated_delivery_orders", "review_score", "mart.v_review_delivery",
     "COUNT(*) FILTER (WHERE review_score IS NOT NULL)", "purchased_at"),
])
def test_q6_q9_q10_api_new_dimensions_and_day_filters(
    conn, metric, dimension, table, expression, time_column,
):
    # Q6/Q9/Q10: каталог работает с новыми источниками и границей date_to включительно.
    catalog = load_catalog(conn)
    expected = rows(conn, f"""
        SELECT {expression} FROM {table}
        WHERE {time_column} >= '2018-02-21' AND {time_column} < '2018-02-22'
    """)[0][0]
    with conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE app_ro")
        cur.execute("SET LOCAL statement_timeout = '5s'")
    total = run_query(conn, catalog, QueryRequest(
        metric=metric, date_from="2018-02-21", date_to="2018-02-21",
    ))
    assert total.rows == [{metric: expected}]
    grouped = run_query(conn, catalog, QueryRequest(
        metric=metric, group_by=["month", dimension], grain="day",
        date_from="2018-02-21", date_to="2018-02-21", limit=1000,
    ))
    assert not grouped.truncated
    assert all(row["month"] == "2018-02-21" for row in grouped.rows)
    assert sum(row[metric] for row in grouped.rows) == expected
