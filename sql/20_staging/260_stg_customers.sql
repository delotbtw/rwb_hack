-- object : stg.customers
-- grain  : 1 строка = 1 контекст покупателя в заказе (customer_id); человек — customer_unique_id
-- source : raw.customers
-- cc     : 99 441 customer_id ↔ 96 096 customer_unique_id; покупателей считаем по unique_id
-- why    : город/штат нормализуются в отдельные колонки, исходные значения сохраняются

CREATE VIEW stg.customers AS
SELECT
    NULLIF(TRIM(customer_id), '')               AS customer_id,
    NULLIF(TRIM(customer_unique_id), '')        AS customer_unique_id,
    NULLIF(TRIM(customer_zip_code_prefix), '')  AS zip_prefix,
    NULLIF(TRIM(customer_city), '')             AS city,
    NULLIF(TRIM(customer_state), '')            AS state,
    LOWER(NULLIF(TRIM(customer_city), ''))      AS city_normalized,
    UPPER(NULLIF(TRIM(customer_state), ''))     AS state_normalized
FROM raw.customers;
