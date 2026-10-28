-- object : stg.sellers
-- grain  : 1 строка = 1 продавец
-- source : raw.sellers
-- cc     : город/штат нормализуются в отдельные колонки, исходные значения сохраняются
-- why    : zip-префикс остаётся text — ведущие нули не теряются

CREATE VIEW stg.sellers AS
SELECT
    NULLIF(TRIM(seller_id), '')               AS seller_id,
    NULLIF(TRIM(seller_zip_code_prefix), '')  AS zip_prefix,
    NULLIF(TRIM(seller_city), '')             AS city,
    NULLIF(TRIM(seller_state), '')            AS state,
    LOWER(NULLIF(TRIM(seller_city), ''))      AS city_normalized,
    UPPER(NULLIF(TRIM(seller_state), ''))     AS state_normalized
FROM raw.sellers;
