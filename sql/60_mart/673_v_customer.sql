-- object : mart.v_customer
-- grain  : 1 строка = 1 покупатель (customer_unique_id), все статусы заказов; ключ customer_unique_id
-- source : mart.order_summary, mart.v_sales_item
-- cc     : покупатель = customer_unique_id; выручка = Σ goods_value по is_revenue (без freight); first_category = категория первой позиции первого заказа
-- why    : гранула покупателя для D3 (доля вернувшихся, выручка и заказы на покупателя) без пересчёта в панелях; orders_count совпадает с customers в mart.v_kpi

CREATE VIEW mart.v_customer AS
WITH order_category AS (
    SELECT DISTINCT ON (order_id) order_id, category_label
    FROM mart.v_sales_item
    ORDER BY order_id, order_item_id
),
orders AS (
    SELECT
        os.customer_unique_id,
        os.customer_state,
        os.purchase_month,
        os.is_revenue,
        os.goods_value,
        oc.category_label,
        ROW_NUMBER() OVER (PARTITION BY os.customer_unique_id ORDER BY os.purchased_at, os.order_id)           AS seq_first,
        ROW_NUMBER() OVER (PARTITION BY os.customer_unique_id ORDER BY os.purchased_at DESC, os.order_id DESC) AS seq_last
    FROM mart.order_summary os
    LEFT JOIN order_category oc ON oc.order_id = os.order_id
)
SELECT
    customer_unique_id,
    MAX(purchase_month)  FILTER (WHERE seq_first = 1)                 AS first_order_month,
    MAX(category_label)  FILTER (WHERE seq_first = 1)                 AS first_category,
    MAX(customer_state)  FILTER (WHERE seq_last = 1)                  AS last_state,
    COUNT(*)                                                          AS orders_count,
    COUNT(*)             FILTER (WHERE is_revenue)                    AS delivered_orders,
    COALESCE(SUM(goods_value) FILTER (WHERE is_revenue), 0)           AS revenue_total,
    COUNT(*) >= 2                                                     AS is_repeat
FROM orders
GROUP BY customer_unique_id;

COMMENT ON VIEW mart.v_customer IS 'Покупатель (customer_unique_id): первый месяц и категория, последний штат, заказы, выручка, признак повторного';
