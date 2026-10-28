-- Сгенерировано pipeline/bundle.py из sql/**. Не редактировать руками.
-- Запуск: psql -v ON_ERROR_STOP=1 -f dist/build_model.sql
BEGIN;

-- >>> sql/00_setup/000_schemas.sql
-- object : схемы stg, core, mart
-- grain  : -
-- source : -
-- cc     : -
-- why    : сборка с нуля и идемпотентна — каждый запуск пересоздаёт всё, кроме raw

DROP SCHEMA IF EXISTS stg CASCADE;
DROP SCHEMA IF EXISTS core CASCADE;
DROP SCHEMA IF EXISTS mart CASCADE;

CREATE SCHEMA stg;
CREATE SCHEMA core;
CREATE SCHEMA mart;

COMMENT ON SCHEMA stg IS 'Типизация и чистка raw: views, 1:1 с таблицами raw';
COMMENT ON SCHEMA core IS 'Модель: измерения и факты';
COMMENT ON SCHEMA mart IS 'Витрины для аналитики, ответов и графиков; DQ';
-- <<< sql/00_setup/000_schemas.sql

-- >>> sql/10_seed/110_dim_order_status.sql
-- object : core.dim_order_status
-- grain  : 1 строка = 1 статус заказа
-- source : статический справочник (8 статусов из handout.md) + unknown-member
-- cc     : FR-30 (определение выручки)
-- why    : определение выручки меняется флагом здесь, а не в каждом запросе

CREATE TABLE core.dim_order_status (
    order_status text PRIMARY KEY,
    is_revenue   boolean NOT NULL,
    is_final     boolean NOT NULL,
    description  text NOT NULL
);

INSERT INTO core.dim_order_status (order_status, is_revenue, is_final, description) VALUES
    ('delivered',   true,  true,  'вручён покупателю'),
    ('shipped',     false, false, 'передан в доставку'),
    ('canceled',    false, true,  'отменён'),
    ('unavailable', false, true,  'недоступен'),
    ('invoiced',    false, false, 'выставлен счёт'),
    ('processing',  false, false, 'в обработке'),
    ('created',     false, false, 'создан'),
    ('approved',    false, false, 'оплата подтверждена'),
    ('unknown',     false, false, 'unknown-member: статус не распознан');
-- <<< sql/10_seed/110_dim_order_status.sql

-- >>> sql/20_staging/200_stg_orders.sql
-- object : stg.orders
-- grain  : 1 строка = 1 строка raw.orders
-- source : raw.orders
-- cc     : пустые строки → NULL; статус приведён к нижнему регистру
-- why    : типы приводятся в одном месте, остальные слои читают только stg

CREATE VIEW stg.orders AS
SELECT
    NULLIF(TRIM(order_id), '')                                    AS order_id,
    NULLIF(TRIM(customer_id), '')                                 AS customer_id,
    LOWER(NULLIF(TRIM(order_status), ''))                         AS order_status,
    NULLIF(TRIM(order_purchase_timestamp), '')::timestamp         AS purchased_at,
    NULLIF(TRIM(order_approved_at), '')::timestamp                AS approved_at,
    NULLIF(TRIM(order_delivered_carrier_date), '')::timestamp     AS delivered_carrier_at,
    NULLIF(TRIM(order_delivered_customer_date), '')::timestamp    AS delivered_customer_at,
    NULLIF(TRIM(order_estimated_delivery_date), '')::timestamp    AS estimated_delivery_at
FROM raw.orders;
-- <<< sql/20_staging/200_stg_orders.sql

-- >>> sql/20_staging/210_stg_order_items.sql
-- object : stg.order_items
-- grain  : 1 строка = 1 строка raw.order_items
-- source : raw.order_items
-- cc     : CC-09 (order_item_id — порядковый номер внутри заказа, не id)
-- why    : деньги в numeric(12,2), номер позиции в int

CREATE VIEW stg.order_items AS
SELECT
    NULLIF(TRIM(order_id), '')                            AS order_id,
    NULLIF(TRIM(order_item_id), '')::int                  AS order_item_id,
    NULLIF(TRIM(product_id), '')                          AS product_id,
    NULLIF(TRIM(seller_id), '')                           AS seller_id,
    NULLIF(TRIM(shipping_limit_date), '')::timestamp      AS shipping_limit_at,
    NULLIF(TRIM(price), '')::numeric(12, 2)               AS price,
    NULLIF(TRIM(freight_value), '')::numeric(12, 2)       AS freight_value
FROM raw.order_items;
-- <<< sql/20_staging/210_stg_order_items.sql

-- >>> sql/40_core_fact/400_fact_order.sql
-- object : core.fact_order
-- grain  : 1 строка = 1 заказ; PK order_id
-- source : stg.orders, core.dim_order_status
-- cc     : неизвестный статус → 'unknown' (unknown-member), строка не теряется
-- why    : заказ — отдельный факт, позиции не смешиваются с ним по грануле

CREATE TABLE core.fact_order AS
SELECT
    o.order_id,
    o.customer_id,
    COALESCE(s.order_status, 'unknown') AS order_status,
    o.purchased_at,
    o.approved_at,
    o.delivered_carrier_at,
    o.delivered_customer_at,
    o.estimated_delivery_at
FROM stg.orders o
LEFT JOIN core.dim_order_status s ON s.order_status = o.order_status;

ALTER TABLE core.fact_order ADD PRIMARY KEY (order_id);
ALTER TABLE core.fact_order
    ADD FOREIGN KEY (order_status) REFERENCES core.dim_order_status (order_status);
-- <<< sql/40_core_fact/400_fact_order.sql

-- >>> sql/40_core_fact/410_fact_order_item.sql
-- object : core.fact_order_item
-- grain  : 1 строка = 1 позиция заказа; PK (order_id, order_item_id)
-- source : stg.order_items
-- cc     : CC-09 (order_item_id — номер позиции)
-- why    : выручка продавца и категории считается на этой грануле

CREATE TABLE core.fact_order_item AS
SELECT
    order_id,
    order_item_id,
    product_id,
    seller_id,
    shipping_limit_at,
    price,
    freight_value
FROM stg.order_items;

ALTER TABLE core.fact_order_item ADD PRIMARY KEY (order_id, order_item_id);
ALTER TABLE core.fact_order_item
    ADD FOREIGN KEY (order_id) REFERENCES core.fact_order (order_id);
-- <<< sql/40_core_fact/410_fact_order_item.sql

-- >>> sql/60_mart/600_v_sales_month.sql
-- object : mart.v_sales_month
-- grain  : 1 строка = 1 календарный месяц 2016-09..2018-10 (включая месяцы без заказов)
-- source : core.fact_order, core.fact_order_item, core.dim_order_status
-- cc     : FR-30 (выручка = SUM(price) по is_revenue, без freight, месяц по purchase); пустой месяц 2016-11
-- why    : материализовано — графики читают за доли миллисекунды

CREATE MATERIALIZED VIEW mart.v_sales_month AS
WITH calendar AS (
    SELECT generate_series(DATE '2016-09-01', DATE '2018-10-01', INTERVAL '1 month')::date AS month
),
revenue_items AS (
    SELECT date_trunc('month', o.purchased_at)::date AS month, o.order_id, i.price, i.freight_value
    FROM core.fact_order o
    JOIN core.dim_order_status s ON s.order_status = o.order_status AND s.is_revenue
    LEFT JOIN core.fact_order_item i ON i.order_id = o.order_id
)
SELECT
    c.month,
    COUNT(DISTINCT r.order_id)               AS orders,
    COALESCE(SUM(r.price), 0)::numeric(14, 2) AS revenue,
    COALESCE(SUM(r.freight_value), 0)::numeric(14, 2) AS freight
FROM calendar c
LEFT JOIN revenue_items r ON r.month = c.month
GROUP BY c.month
ORDER BY c.month;

COMMENT ON MATERIALIZED VIEW mart.v_sales_month IS
    'Выручка (SUM price, delivered) и число заказов по месяцу оформления; месяцы без заказов = 0';
-- <<< sql/60_mart/600_v_sales_month.sql

-- >>> sql/80_dq/800_dq_framework.sql
-- object : mart.dq_result, mart.build_info
-- grain  : dq_result — 1 строка = 1 проверка; build_info — 1 строка на сборку
-- source : -
-- cc     : NFR (самопроверки)
-- why    : результаты проверок лежат в базе и видны любому клиенту

CREATE TABLE mart.dq_result (
    check_id    text PRIMARY KEY,
    description text NOT NULL,
    expected    text NOT NULL,
    actual      text,
    passed      boolean NOT NULL,
    checked_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE mart.build_info AS
SELECT now() AS built_at;
-- <<< sql/80_dq/800_dq_framework.sql

-- >>> sql/80_dq/810_dq_checks.sql
-- object : проверки DQ (наполнение mart.dq_result)
-- grain  : 1 INSERT = 1 проверка
-- source : raw.*, core.*, mart.*
-- cc     : DQ-xx из ТЗ §9; контроль Q1 из tasks.md
-- why    : новая проверка = новый INSERT по этому же шаблону

INSERT INTO mart.dq_result (check_id, description, expected, actual, passed)
SELECT 'DQ-01', 'fact_order: строк столько же, сколько в raw.orders',
       (SELECT COUNT(*) FROM raw.orders)::text, COUNT(*)::text,
       COUNT(*) = (SELECT COUNT(*) FROM raw.orders)
FROM core.fact_order;

INSERT INTO mart.dq_result (check_id, description, expected, actual, passed)
SELECT 'DQ-02', 'fact_order_item: строк столько же, сколько в raw.order_items',
       (SELECT COUNT(*) FROM raw.order_items)::text, COUNT(*)::text,
       COUNT(*) = (SELECT COUNT(*) FROM raw.order_items)
FROM core.fact_order_item;

INSERT INTO mart.dq_result (check_id, description, expected, actual, passed)
SELECT 'DQ-03', 'fact_order: нет статусов unknown',
       '0', COUNT(*)::text, COUNT(*) = 0
FROM core.fact_order
WHERE order_status = 'unknown';

INSERT INTO mart.dq_result (check_id, description, expected, actual, passed)
SELECT 'Q1-CTRL', 'Q1: 24 месяца 2016-09..2018-08, итого выручка 13 221 498.11',
       '24 / 13221498.11', COUNT(*) || ' / ' || SUM(revenue),
       COUNT(*) = 24 AND SUM(revenue) = 13221498.11
FROM mart.v_sales_month
WHERE month BETWEEN DATE '2016-09-01' AND DATE '2018-08-01';
-- <<< sql/80_dq/810_dq_checks.sql

-- >>> sql/80_dq/890_dq_run.sql
-- object : гейт сборки по DQ
-- grain  : -
-- source : mart.dq_result
-- cc     : -
-- why    : в режиме strict упавшая проверка откатывает всю сборку (она идёт одной транзакцией);
--          режим задаётся SET capibara.dq_mode = 'strict' | 'report', по умолчанию strict

DO $$
DECLARE
    failed text;
BEGIN
    SELECT string_agg(check_id, ', ' ORDER BY check_id) INTO failed
    FROM mart.dq_result
    WHERE NOT passed;

    IF failed IS NOT NULL THEN
        IF COALESCE(NULLIF(current_setting('capibara.dq_mode', true), ''), 'strict') = 'strict' THEN
            RAISE EXCEPTION 'DQ failed: %', failed;
        END IF;
        RAISE WARNING 'DQ failed (report mode): %', failed;
    END IF;
END $$;
-- <<< sql/80_dq/890_dq_run.sql

COMMIT;
