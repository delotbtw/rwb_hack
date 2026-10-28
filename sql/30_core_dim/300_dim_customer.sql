-- object : core.dim_customer
-- grain  : 1 строка = 1 customer_id (контекст покупателя в заказе); PK customer_id
-- source : stg.customers
-- cc     : человек = customer_unique_id (96 096), customer_id меняется от заказа к заказу (99 441)
-- why    : повторность и число покупателей считаются по customer_unique_id, адрес — контекстный

CREATE TABLE core.dim_customer AS
SELECT customer_id, customer_unique_id, zip_prefix, city, state, city_normalized, state_normalized
FROM stg.customers;

ALTER TABLE core.dim_customer ADD PRIMARY KEY (customer_id);
ALTER TABLE core.dim_customer ALTER COLUMN customer_unique_id SET NOT NULL;
CREATE INDEX ON core.dim_customer (customer_unique_id);
