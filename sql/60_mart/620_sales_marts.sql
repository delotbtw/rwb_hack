-- object : mart.v_seller_sales, mart.v_category_sales
-- grain  : продавец; категория (по позициям доставленных заказов)
-- source : core.fact_order_item, core.fact_order, core.dim_order_status, core.dim_seller, core.dim_product, core.dim_category
-- cc     : FR-30 выручка = SUM(price) по is_revenue; выручка продавца — только его позиции, не весь чек
-- why    : гранула позиции: заказ с товарами разных продавцов делится между ними корректно

CREATE VIEW mart.v_seller_sales AS
SELECT
    i.seller_id,
    s.city,
    s.state,
    COUNT(DISTINCT i.order_id) AS orders,
    COUNT(*)                   AS units,
    SUM(i.price)               AS revenue
FROM core.fact_order_item i
JOIN core.fact_order o        ON o.order_id = i.order_id
JOIN core.dim_order_status st ON st.order_status = o.order_status AND st.is_revenue
LEFT JOIN core.dim_seller s   ON s.seller_id = i.seller_id
GROUP BY i.seller_id, s.city, s.state;

CREATE VIEW mart.v_category_sales AS
SELECT
    c.category_key,
    c.label,
    c.is_unknown,
    SUM(i.price) AS revenue,
    (100 * SUM(i.price) / SUM(SUM(i.price)) OVER ())::numeric(6, 2) AS share_pct
FROM core.fact_order_item i
JOIN core.fact_order o        ON o.order_id = i.order_id
JOIN core.dim_order_status st ON st.order_status = o.order_status AND st.is_revenue
LEFT JOIN core.dim_product p  ON p.product_id = i.product_id
LEFT JOIN core.dim_category c ON c.category_key = COALESCE(p.category_key, '__unknown__')
GROUP BY c.category_key, c.label, c.is_unknown;

COMMENT ON VIEW mart.v_seller_sales IS 'Выручка, заказы и единицы продавца по доставленным заказам';
COMMENT ON VIEW mart.v_category_sales IS 'Выручка и доля категории; unknown — отдельная строка, сумма = общей выручке';
