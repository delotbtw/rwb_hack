-- object : stg.order_items
-- grain  : 1 строка = 1 строка raw.order_items
-- source : raw.order_items
-- cc     : CC-09 (order_item_id — порядковый номер внутри заказа, не id)
-- why    : деньги в numeric(12,2), номер позиции в int

CREATE VIEW stg.order_items AS
SELECT
    NULLIF(TRIM(order_id), '')                            AS order_id,
    NULLIF(TRIM(order_item_id), '')::int                  AS order_item_id,
    NULLIF(TRIM(product_id), '')                          AS product_id,
    NULLIF(TRIM(seller_id), '')                           AS seller_id,
    NULLIF(TRIM(shipping_limit_date), '')::timestamp      AS shipping_limit_at,
    NULLIF(TRIM(price), '')::numeric(12, 2)               AS price,
    NULLIF(TRIM(freight_value), '')::numeric(12, 2)       AS freight_value
FROM raw.order_items;
