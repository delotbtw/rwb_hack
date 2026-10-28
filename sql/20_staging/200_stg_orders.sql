-- object : stg.orders
-- grain  : 1 строка = 1 строка raw.orders
-- source : raw.orders
-- cc     : пустые строки → NULL; статус приведён к нижнему регистру
-- why    : типы приводятся в одном месте, остальные слои читают только stg

CREATE VIEW stg.orders AS
SELECT
    NULLIF(TRIM(order_id), '')                                    AS order_id,
    NULLIF(TRIM(customer_id), '')                                 AS customer_id,
    LOWER(NULLIF(TRIM(order_status), ''))                         AS order_status,
    NULLIF(TRIM(order_purchase_timestamp), '')::timestamp         AS purchased_at,
    NULLIF(TRIM(order_approved_at), '')::timestamp                AS approved_at,
    NULLIF(TRIM(order_delivered_carrier_date), '')::timestamp     AS delivered_carrier_at,
    NULLIF(TRIM(order_delivered_customer_date), '')::timestamp    AS delivered_customer_at,
    NULLIF(TRIM(order_estimated_delivery_date), '')::timestamp    AS estimated_delivery_at
FROM raw.orders;
