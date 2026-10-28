-- object : core.fact_order_item
-- grain  : 1 строка = 1 позиция заказа; PK (order_id, order_item_id)
-- source : stg.order_items
-- cc     : CC-09 (order_item_id — номер позиции)
-- why    : выручка продавца и категории считается на этой грануле

CREATE TABLE core.fact_order_item AS
SELECT
    order_id,
    order_item_id,
    product_id,
    seller_id,
    shipping_limit_at,
    price,
    freight_value
FROM stg.order_items;

ALTER TABLE core.fact_order_item ADD PRIMARY KEY (order_id, order_item_id);
ALTER TABLE core.fact_order_item
    ADD FOREIGN KEY (order_id) REFERENCES core.fact_order (order_id);
