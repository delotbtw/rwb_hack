-- object : stg.order_payments
-- grain  : 1 строка = 1 платёжная запись заказа
-- source : raw.order_payments
-- cc     : installments = 0 сохраняется как есть (не подменяем на 1); payment_value не умножается на installments
-- why    : деньги в numeric(12,2), номера и рассрочка в int

CREATE VIEW stg.order_payments AS
SELECT
    NULLIF(TRIM(order_id), '')                        AS order_id,
    NULLIF(TRIM(payment_sequential), '')::int         AS payment_sequential,
    LOWER(NULLIF(TRIM(payment_type), ''))             AS payment_type,
    NULLIF(TRIM(payment_installments), '')::int       AS payment_installments,
    NULLIF(TRIM(payment_value), '')::numeric(12, 2)   AS payment_value
FROM raw.order_payments;
