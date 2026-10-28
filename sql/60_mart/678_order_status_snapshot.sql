-- object : mart.v_order_status_snapshot
-- grain  : итоговый статус, полный доступный период
-- source : mart.order_summary
-- cc     : Q6–Q10; независимые факты не размножаются
-- why    : определения нового ноутбука без изменения Q1–Q5

CREATE VIEW mart.v_order_status_snapshot AS
SELECT order_status, COUNT(*) AS orders,
       100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0) AS share_pct,
       COUNT(*) FILTER (WHERE NOT has_items) AS without_items
FROM mart.order_summary GROUP BY order_status;
