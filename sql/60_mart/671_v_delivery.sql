-- object : mart.v_delivery
-- grain  : 1 строка = 1 заказ со статусом delivered; PK order_id
-- source : mart.order_summary, core.fact_order_item, core.dim_seller, core.dim_product, core.dim_category
-- cc     : 8 delivered без даты вручения и невалидные даты: has_valid_dates = FALSE, флаги и late_bucket = NULL; доставка и опоздание не пересчитываются
-- why    : основной продавец и категория заказа (по наибольшей сумме price, при равенстве по id/названию) дают срез D2 без JOIN фактов в панелях

CREATE VIEW mart.v_delivery AS
WITH seller_pick AS (
    SELECT DISTINCT ON (order_id) order_id, seller_state
    FROM (
        SELECT i.order_id, i.seller_id, s.state_normalized AS seller_state, SUM(i.price) AS price_sum
        FROM core.fact_order_item i
        LEFT JOIN core.dim_seller s ON s.seller_id = i.seller_id
        GROUP BY i.order_id, i.seller_id, s.state_normalized
    ) t
    ORDER BY order_id, price_sum DESC NULLS LAST, seller_id
),
category_pick AS (
    SELECT DISTINCT ON (order_id) order_id, category_label
    FROM (
        SELECT i.order_id, i.category_label, SUM(i.price) AS price_sum
        FROM mart.v_sales_item i
        GROUP BY i.order_id, i.category_label
    ) t
    ORDER BY order_id, price_sum DESC NULLS LAST, category_label
)
SELECT
    o.order_id,
    o.purchase_month,
    o.customer_state,
    sp.seller_state                                  AS seller_state_main,
    cp.category_label                                AS category_main,
    o.delivery_days,
    o.delay_days,
    CASE WHEN o.is_valid_delivery THEN o.delay_days <= 0 END AS is_on_time,
    CASE WHEN o.is_valid_delivery THEN o.delay_days > 0 END  AS is_late,
    o.is_valid_delivery                              AS has_valid_dates,
    o.review_score_mean,
    CASE
        WHEN NOT o.is_valid_delivery THEN NULL
        WHEN o.delay_days <= 0       THEN 'on_time'
        WHEN o.delay_days <= 3       THEN '1-3'
        WHEN o.delay_days <= 7       THEN '4-7'
        ELSE '8+'
    END                                              AS late_bucket
FROM mart.order_summary o
LEFT JOIN seller_pick   sp ON sp.order_id = o.order_id
LEFT JOIN category_pick cp ON cp.order_id = o.order_id
WHERE o.order_status = 'delivered';

COMMENT ON VIEW mart.v_delivery IS 'Delivered-заказ: срок и опоздание из order_summary, основной продавец/категория, корзина опоздания';
