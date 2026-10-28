-- object : история категорий и адресов
-- grain  : сущность + момент начала действия
-- source : события product.category_changed, customer.address_changed; контекст заказа
-- cc     : Вброс; прошлые продажи и адрес заказа не подменяются текущими
-- why    : постоянные версии переживают пересборку core/mart

-- Снимок заказа авторитетен: последующие переезды человека его не изменяют.
INSERT INTO ops.order_address_snapshot
    (order_id, customer_id, customer_unique_id, purchased_at, zip_prefix, city, state)
SELECT o.order_id, o.customer_id, c.customer_unique_id, o.purchased_at, c.zip_prefix, c.city, c.state
FROM core.fact_order o
LEFT JOIN core.dim_customer c ON c.customer_id = o.customer_id
WHERE c.customer_unique_id IS NOT NULL
ON CONFLICT (order_id) DO NOTHING;

CREATE VIEW mart.v_product_category_history AS
SELECT seller_id, product_id, category_key, event_id, valid_from,
       LEAD(valid_from) OVER (PARTITION BY seller_id, product_id ORDER BY valid_from) AS valid_to
FROM ops.product_category_history;

CREATE VIEW mart.v_customer_address_history AS
SELECT customer_unique_id, zip_prefix, city, state, event_id, valid_from,
       LEAD(valid_from) OVER (PARTITION BY customer_unique_id ORDER BY valid_from) AS valid_to
FROM ops.customer_address_history;

CREATE VIEW mart.v_order_address AS
SELECT s.order_id, s.customer_id, s.customer_unique_id, s.purchased_at, s.zip_prefix, s.city, s.state,
       LOWER(NULLIF(TRIM(s.city), '')) AS city_normalized,
       UPPER(NULLIF(TRIM(s.state), '')) AS state_normalized
FROM ops.order_address_snapshot s
JOIN core.fact_order o ON o.order_id = s.order_id;
