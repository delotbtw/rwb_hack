-- object : mart.v_layer_rows, mart.v_raw_missingness
-- grain  : таблица источника; колонка источника
-- source : raw.*, core.*
-- cc     : строки не теряются между raw и core; пропуски в raw сохраняются, а не «лечатся»
-- why    : самопроверка видна на странице, а не только в логе сборки

CREATE VIEW mart.v_layer_rows AS
SELECT * FROM (VALUES
    ('orders',              (SELECT COUNT(*) FROM raw.orders),                       (SELECT COUNT(*) FROM core.fact_order)),
    ('order_items',         (SELECT COUNT(*) FROM raw.order_items),                  (SELECT COUNT(*) FROM core.fact_order_item)),
    ('order_payments',      (SELECT COUNT(*) FROM raw.order_payments),               (SELECT COUNT(*) FROM core.fact_order_payment)),
    ('order_reviews',       (SELECT COUNT(*) FROM raw.order_reviews),                (SELECT COUNT(*) FROM core.fact_order_review)),
    ('products',            (SELECT COUNT(*) FROM raw.products),                     (SELECT COUNT(*) FROM core.dim_product)),
    ('sellers',             (SELECT COUNT(*) FROM raw.sellers),                      (SELECT COUNT(*) FROM core.dim_seller)),
    ('customers',           (SELECT COUNT(*) FROM raw.customers),                    (SELECT COUNT(*) FROM core.dim_customer)),
    ('category_translation',(SELECT COUNT(*) FROM raw.product_category_translation), (SELECT COUNT(*) FROM stg.category_translation))
) AS t(source_table, raw_rows, model_rows);

-- пропуски по каждой колонке raw: строки разворачиваются в пары (колонка, значение) через jsonb
CREATE MATERIALIZED VIEW mart.v_raw_missingness AS
WITH cells AS (
    SELECT 'orders' AS source_table, j.key, j.value FROM raw.orders t, jsonb_each_text(to_jsonb(t)) j
    UNION ALL SELECT 'order_items', j.key, j.value FROM raw.order_items t, jsonb_each_text(to_jsonb(t)) j
    UNION ALL SELECT 'order_payments', j.key, j.value FROM raw.order_payments t, jsonb_each_text(to_jsonb(t)) j
    UNION ALL SELECT 'order_reviews', j.key, j.value FROM raw.order_reviews t, jsonb_each_text(to_jsonb(t)) j
    UNION ALL SELECT 'products', j.key, j.value FROM raw.products t, jsonb_each_text(to_jsonb(t)) j
    UNION ALL SELECT 'sellers', j.key, j.value FROM raw.sellers t, jsonb_each_text(to_jsonb(t)) j
    UNION ALL SELECT 'customers', j.key, j.value FROM raw.customers t, jsonb_each_text(to_jsonb(t)) j
)
SELECT
    source_table,
    key AS column_name,
    COUNT(*) FILTER (WHERE NULLIF(TRIM(value), '') IS NULL) AS missing,
    (100.0 * COUNT(*) FILTER (WHERE NULLIF(TRIM(value), '') IS NULL) / COUNT(*))::numeric(5, 2) AS missing_pct
FROM cells
WHERE key NOT IN ('_source_file', '_loaded_at')
GROUP BY source_table, key;
