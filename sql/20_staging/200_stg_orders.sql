-- object : stg.orders
-- grain  : 1 строка = 1 строка raw.orders
-- source : raw.orders
-- cc     : пустые строки → NULL; статус приведён к нижнему регистру;
--          cutoff (ops.build_params): при заданном cutoff только заказы с purchased_at < cutoff (K0 §4.5, K3 §3.1)
-- why    : типы приводятся в одном месте, остальные слои читают только stg

CREATE VIEW stg.orders AS
WITH typed AS (
    SELECT
        NULLIF(TRIM(order_id), '')                                    AS order_id,
        NULLIF(TRIM(customer_id), '')                                 AS customer_id,
        LOWER(NULLIF(TRIM(order_status), ''))                         AS order_status,
        NULLIF(TRIM(order_purchase_timestamp), '')::timestamp         AS purchased_at,
        NULLIF(TRIM(order_approved_at), '')::timestamp                AS approved_at,
        NULLIF(TRIM(order_delivered_carrier_date), '')::timestamp     AS delivered_carrier_at,
        NULLIF(TRIM(order_delivered_customer_date), '')::timestamp    AS delivered_customer_at,
        NULLIF(TRIM(order_estimated_delivery_date), '')::timestamp    AS estimated_delivery_at
    FROM raw.orders
)

SELECT * FROM typed
WHERE (SELECT cutoff FROM ops.build_params WHERE id = 1) IS NULL
   OR purchased_at < (SELECT cutoff FROM ops.build_params WHERE id = 1);
