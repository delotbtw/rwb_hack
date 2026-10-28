-- object : mart.order_summary
-- grain  : 1 строка = 1 заказ (все 99 441, все статусы); PK order_id
-- source : core.fact_order, fact_order_item, fact_order_payment, fact_order_review, dim_customer, dim_order_status
-- cc     : 775 заказов без позиций, 1 без оплаты, 639 с расхождением оплаты; 8 delivered без даты вручения
-- why    : каждый поток сначала агрегируется до заказа отдельно — без fan-out (2 товара × 2 оплаты ≠ 4 строки)

CREATE MATERIALIZED VIEW mart.order_summary AS
WITH items AS (
    SELECT order_id,
           COUNT(*)                   AS line_count,
           SUM(price)                 AS goods_value,
           SUM(freight_value)         AS freight_value,
           COUNT(DISTINCT seller_id)  AS seller_count
    FROM core.fact_order_item
    GROUP BY order_id
),
payments AS (
    SELECT order_id, COUNT(*) AS payment_count, SUM(payment_value) AS payment_value
    FROM core.fact_order_payment
    GROUP BY order_id
),
reviews AS (
    SELECT order_id, COUNT(*) AS review_count, AVG(review_score)::numeric(4, 2) AS review_score_mean
    FROM core.fact_order_review
    GROUP BY order_id
),
base AS (
    SELECT
        o.order_id,
        o.order_status,
        s.is_revenue,
        c.customer_unique_id,
        c.state_normalized                          AS customer_state,
        o.purchased_at,
        date_trunc('month', o.purchased_at)::date   AS purchase_month,
        o.delivered_customer_at,
        o.estimated_delivery_at,
        COALESCE(i.line_count, 0)                   AS line_count,
        COALESCE(i.seller_count, 0)                 AS seller_count,
        i.goods_value,
        i.freight_value,
        i.goods_value + i.freight_value             AS order_value,
        COALESCE(p.payment_count, 0)                AS payment_count,
        p.payment_value,
        COALESCE(r.review_count, 0)                 AS review_count,
        r.review_score_mean,
        i.order_id IS NOT NULL                      AS has_items,
        p.order_id IS NOT NULL                      AS has_payments
    FROM core.fact_order o
    JOIN core.dim_order_status s ON s.order_status = o.order_status
    LEFT JOIN core.dim_customer c ON c.customer_id = o.customer_id
    LEFT JOIN items    i ON i.order_id = o.order_id
    LEFT JOIN payments p ON p.order_id = o.order_id
    LEFT JOIN reviews  r ON r.order_id = o.order_id
)
SELECT
    b.*,
    b.payment_value - b.order_value AS payment_delta,
    CASE
        WHEN NOT b.has_items AND NOT b.has_payments THEN 'Нет обеих сторон'
        WHEN NOT b.has_items                        THEN 'Нет позиций'
        WHEN NOT b.has_payments                     THEN 'Нет оплаты'
        WHEN b.payment_value = b.order_value        THEN 'Совпадает'
        ELSE 'Расхождение'
    END AS reconciliation,
    EXTRACT(EPOCH FROM b.delivered_customer_at - b.purchased_at) / 86400 AS delivery_days,
    b.delivered_customer_at::date - b.estimated_delivery_at::date        AS delay_days,
    (b.order_status = 'delivered' AND b.delivered_customer_at IS NOT NULL
        AND b.estimated_delivery_at IS NOT NULL
        AND b.delivered_customer_at >= b.purchased_at)                   AS is_valid_delivery
FROM base b;

CREATE UNIQUE INDEX ON mart.order_summary (order_id);
COMMENT ON MATERIALIZED VIEW mart.order_summary IS
    'Один заказ: суммы позиций/оплат/отзывов, сверка оплаты, срок и опоздание доставки';
