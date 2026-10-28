-- object : core.fact_order_payment
-- grain  : 1 строка = 1 платёжная запись; PK (order_id, payment_sequential)
-- source : stg.order_payments
-- cc     : 1 заказ без оплаты; installments = 0 сохранён; сумма оплат ≠ сумме позиций у 639 заказов
-- why    : платёж — отдельный факт, с позициями соединяется только после агрегации до заказа

CREATE TABLE core.fact_order_payment AS
SELECT order_id, payment_sequential, payment_type, payment_installments, payment_value
FROM stg.order_payments;

ALTER TABLE core.fact_order_payment ADD PRIMARY KEY (order_id, payment_sequential);
ALTER TABLE core.fact_order_payment
    ADD FOREIGN KEY (order_id) REFERENCES core.fact_order (order_id);
