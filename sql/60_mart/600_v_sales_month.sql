-- object : mart.v_sales_month
-- grain  : 1 строка = 1 календарный месяц 2016-09..2018-10 (включая месяцы без заказов)
-- source : core.fact_order, core.fact_order_item, core.dim_order_status
-- cc     : FR-30 (выручка = SUM(price) по is_revenue, без freight, месяц по purchase); пустой месяц 2016-11
-- why    : материализовано — графики читают за доли миллисекунды

CREATE MATERIALIZED VIEW mart.v_sales_month AS
WITH calendar AS (
    SELECT generate_series(DATE '2016-09-01', DATE '2018-10-01', INTERVAL '1 month')::date AS month
),
revenue_items AS (
    SELECT date_trunc('month', o.purchased_at)::date AS month, o.order_id, i.price, i.freight_value
    FROM core.fact_order o
    JOIN core.dim_order_status s ON s.order_status = o.order_status AND s.is_revenue
    LEFT JOIN core.fact_order_item i ON i.order_id = o.order_id
)
SELECT
    c.month,
    COUNT(DISTINCT r.order_id)               AS orders,
    COALESCE(SUM(r.price), 0)::numeric(14, 2) AS revenue,
    COALESCE(SUM(r.freight_value), 0)::numeric(14, 2) AS freight
FROM calendar c
LEFT JOIN revenue_items r ON r.month = c.month
GROUP BY c.month
ORDER BY c.month;

COMMENT ON MATERIALIZED VIEW mart.v_sales_month IS
    'Выручка (SUM price, delivered) и число заказов по месяцу оформления; месяцы без заказов = 0';
