-- object : mart.v_kpi
-- grain  : 1 строка = ключевые показатели площадки за весь период
-- source : mart.order_summary
-- cc     : средний чек и доли — неаддитивны, считаются на грануле заказа/покупателя, а не суммой срезов
-- why    : одна точка правды для строки KPI на странице и для слайдов

CREATE VIEW mart.v_kpi AS
WITH customers AS (
    SELECT customer_unique_id, COUNT(*) AS orders
    FROM mart.order_summary
    GROUP BY customer_unique_id
)
SELECT
    (SELECT SUM(goods_value) FROM mart.order_summary WHERE is_revenue)                    AS revenue,
    (SELECT COUNT(*) FROM mart.order_summary WHERE is_revenue)                            AS delivered_orders,
    (SELECT ROUND(SUM(order_value) / COUNT(*), 2) FROM mart.order_summary WHERE is_revenue) AS avg_check,
    (SELECT COUNT(*) FROM customers)                                                      AS customers,
    (SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE orders >= 2) / COUNT(*), 2) FROM customers) AS repeat_pct,
    (SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE delay_days > 0) / COUNT(*), 2)
       FROM mart.order_summary WHERE is_valid_delivery)                                   AS late_pct,
    (SELECT ROUND((percentile_cont(0.5) WITHIN GROUP (ORDER BY delivery_days))::numeric, 1)
       FROM mart.order_summary WHERE is_valid_delivery)                                   AS median_delivery_days;
