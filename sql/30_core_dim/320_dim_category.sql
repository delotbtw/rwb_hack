-- object : core.dim_category
-- grain  : 1 строка = 1 категория; PK category_key
-- source : stg.products, stg.category_translation
-- cc     : 71 перевод + 2 категории без перевода + '__unknown__' (610 товаров без категории) = 74
-- why    : справочник строится из товаров И переводов — неполный перевод не отсекает товары

CREATE TABLE core.dim_category AS
WITH names AS (
    SELECT category_name FROM stg.products WHERE category_name IS NOT NULL
    UNION
    SELECT category_name FROM stg.category_translation WHERE category_name IS NOT NULL
)
SELECT
    n.category_name                          AS category_key,
    n.category_name                          AS category_name,
    t.category_name_en,
    COALESCE(t.category_name_en, n.category_name) AS label,
    t.category_name_en IS NULL               AS is_untranslated,
    false                                    AS is_unknown
FROM names n
LEFT JOIN stg.category_translation t ON t.category_name = n.category_name
UNION ALL
SELECT '__unknown__', NULL, NULL, 'Неизвестная категория', false, true;

ALTER TABLE core.dim_category ADD PRIMARY KEY (category_key);
