-- object : mart.v_payment_context
-- grain  : платёж (order_id, payment_sequential), все статусы
-- source : core.fact_order_payment, mart.order_summary
-- cc     : Q6–Q10; независимые факты не размножаются
-- why    : определения нового ноутбука без изменения Q1–Q5

CREATE VIEW mart.v_payment_context AS
SELECT p.*, o.purchased_at AS purchase_ts, o.purchase_month, o.customer_state, o.order_status
FROM core.fact_order_payment p
LEFT JOIN mart.order_summary o ON o.order_id = p.order_id;
