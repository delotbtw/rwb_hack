-- object : mart.v_payment
-- grain  : 1 строка = 1 платёж заказа (order_id, payment_sequential), все статусы заказа
-- source : core.fact_order_payment, mart.order_summary
-- cc     : 1 заказ без оплаты не попадает в витрину (нет платежа); значения оплаты как в core, расхождение с позициями не правим
-- why    : срез способов оплаты для D1 без JOIN фактов в панелях: платёж ровно один раз, срезы заказа берутся из order_summary

CREATE VIEW mart.v_payment AS
SELECT
    p.order_id,
    p.payment_sequential,
    o.purchase_month,
    o.customer_state,
    p.payment_type,
    p.payment_installments  AS installments,
    p.payment_value,
    COALESCE(o.is_revenue, FALSE) AS is_revenue
FROM core.fact_order_payment p
LEFT JOIN mart.order_summary o ON o.order_id = p.order_id;

COMMENT ON VIEW mart.v_payment IS 'Платёж заказа: способ, рассрочка, сумма и срезы месяц/штат покупателя/is_revenue';
