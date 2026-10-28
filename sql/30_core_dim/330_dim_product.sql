-- object : core.dim_product
-- grain  : 1 строка = 1 товар; PK product_id
-- source : stg.products, core.dim_category
-- cc     : пустая категория → '__unknown__' + флаг is_missing_category; габариты nullable
-- why    : категория — FK на справочник, исходное название сохраняется для прозрачности

CREATE TABLE core.dim_product AS
SELECT
    product_id,
    category_key,
    category_name,
    category_name IS NULL AS is_missing_category,
    name_length, description_length, photos_qty,
    weight_g, length_cm, height_cm, width_cm
FROM stg.products;

ALTER TABLE core.dim_product ADD PRIMARY KEY (product_id);
ALTER TABLE core.dim_product
    ADD FOREIGN KEY (category_key) REFERENCES core.dim_category (category_key);
