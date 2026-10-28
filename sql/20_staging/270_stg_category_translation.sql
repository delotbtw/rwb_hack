-- object : stg.category_translation
-- grain  : 1 строка = 1 перевод категории
-- source : raw.product_category_translation
-- cc     : 2 категории товаров без перевода (pc_gamer, portateis_cozinha_e_preparadores_de_alimentos)
-- why    : справочник перевода — необязательная подпись, а не фильтр допустимых категорий

CREATE VIEW stg.category_translation AS
SELECT
    NULLIF(TRIM(product_category_name), '')          AS category_name,
    NULLIF(TRIM(product_category_name_english), '')  AS category_name_en
FROM raw.product_category_translation;
