-- object : core.dim_seller
-- grain  : 1 строка = 1 продавец; PK seller_id
-- source : stg.sellers
-- cc     : is_inferred=false: заглушки продавцов из потока (K2) помечаются true
-- why    : география продавца нужна для Q2 (город, штат) и срезов доставки

CREATE TABLE core.dim_seller AS
SELECT seller_id, zip_prefix, city, state, city_normalized, state_normalized,
       false AS is_inferred
FROM stg.sellers;

ALTER TABLE core.dim_seller ADD PRIMARY KEY (seller_id);
