-- object : mart.v_delivery_by_state
-- grain  : штат покупателя, полный доступный период
-- source : mart.order_summary
-- cc     : Q6–Q10; независимые факты не размножаются
-- why    : определения нового ноутбука без изменения Q1–Q5

CREATE VIEW mart.v_delivery_by_state AS
SELECT customer_state, COUNT(*) AS all_orders,
       COUNT(*) FILTER (WHERE is_valid_delivery) AS valid_orders,
       AVG(delivery_days) FILTER (WHERE is_valid_delivery) AS mean_delivery_days,
       COUNT(*) FILTER (WHERE is_valid_delivery AND delay_days > 0) AS late_orders,
       100.0 * COUNT(*) FILTER (WHERE is_valid_delivery AND delay_days > 0)
         / NULLIF(COUNT(*) FILTER (WHERE is_valid_delivery), 0) AS late_pct
FROM mart.order_summary GROUP BY customer_state;
