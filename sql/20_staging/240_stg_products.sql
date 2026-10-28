-- object : stg.products
-- grain  : 1 строка = 1 карточка товара
-- source : raw.products
-- cc     : 610 товаров без категории → category_key '__unknown__'; опечатка lenght исправлена в именах колонок
-- why    : числовые характеристики в int, исходное название категории сохраняется отдельно от ключа

CREATE VIEW stg.products AS
SELECT
    NULLIF(TRIM(product_id), '')                              AS product_id,
    NULLIF(TRIM(product_category_name), '')                   AS category_name,
    COALESCE(NULLIF(TRIM(product_category_name), ''), '__unknown__') AS category_key,
    NULLIF(TRIM(product_name_lenght), '')::int                AS name_length,
    NULLIF(TRIM(product_description_lenght), '')::int         AS description_length,
    NULLIF(TRIM(product_photos_qty), '')::int                 AS photos_qty,
    NULLIF(TRIM(product_weight_g), '')::int                   AS weight_g,
    NULLIF(TRIM(product_length_cm), '')::int                  AS length_cm,
    NULLIF(TRIM(product_height_cm), '')::int                  AS height_cm,
    NULLIF(TRIM(product_width_cm), '')::int                   AS width_cm
FROM raw.products;
