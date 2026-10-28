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

-- >>> sql/00_setup/001_roles.sql
-- object : роли app_ro (чтение mart для API/Grafana) и ingestor (запись в landing/core из потока)
-- grain  : -
-- source : -
-- cc     : NFR (разграничение доступа), K0 §4.4
-- why    : роли живут на уровне кластера и не пересоздаются; гранты выдаёт 900_grants.sql (схемы дропаются при сборке)
-- ASSUMPTION-K0-1: демо-пароль = имя роли (только локально); пользователь hack не меняется

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_ro') THEN
        CREATE ROLE app_ro LOGIN PASSWORD 'app_ro';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ingestor') THEN
        CREATE ROLE ingestor LOGIN PASSWORD 'ingestor';
    END IF;
END
$$;

ALTER ROLE app_ro SET statement_timeout = '5s';
ALTER ROLE app_ro SET default_transaction_read_only = on;
-- <<< sql/00_setup/001_roles.sql

-- >>> sql/00_setup/002_persistent_schemas.sql
-- object : схемы landing и ops
-- grain  : -
-- source : -
-- cc     : K0 §3.1
-- why    : 000_schemas.sql дропает stg/core/mart на каждой сборке; журнал событий и служебные таблицы
--          должны пережить сборку, поэтому схемы создаются IF NOT EXISTS и никогда не дропаются

CREATE SCHEMA IF NOT EXISTS landing;
CREATE SCHEMA IF NOT EXISTS ops;

COMMENT ON SCHEMA landing IS 'Журнал входящих событий real-time; не пересоздаётся при сборке';
COMMENT ON SCHEMA ops IS 'Служебные таблицы: запуски ETL, статус потока, сверка, параметры сборки; не пересоздаётся';
-- <<< sql/00_setup/002_persistent_schemas.sql

-- >>> sql/05_landing/050_landing_events.sql
-- object : landing.events
-- grain  : 1 строка = 1 событие orders.events (event_id)
-- source : Kafka topic orders.events
-- cc     : K0 §4.1, §4.2
-- why    : неизменяемый журнал входящих событий; PK event_id даёт идемпотентность
--          (ON CONFLICT DO NOTHING), IF NOT EXISTS — данные переживают пересборку

CREATE TABLE IF NOT EXISTS landing.events (
    event_id       uuid PRIMARY KEY,
    topic          text,
    partition      integer,
    kafka_offset   bigint,
    order_id       text,
    type           text NOT NULL CHECK (type IN (
                       'order.created', 'payment.captured', 'order.status_changed',
                       'review.posted', 'replay.completed')),
    schema_version smallint,
    payload        jsonb NOT NULL,
    event_ts       timestamp NOT NULL,
    produced_at    timestamp,
    received_at    timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    status         text NOT NULL DEFAULT 'received'
                       CHECK (status IN ('received', 'applied', 'skipped_stale', 'error')),
    error          text
);

CREATE INDEX IF NOT EXISTS ix_events_order_event_ts ON landing.events (order_id, event_ts);
CREATE INDEX IF NOT EXISTS ix_events_event_ts ON landing.events (event_ts);
CREATE INDEX IF NOT EXISTS ix_events_received_not_applied ON landing.events (received_at)
    WHERE status <> 'applied';

COMMENT ON TABLE landing.events IS 'Журнал событий orders.events: 1 строка = 1 event_id';
COMMENT ON COLUMN landing.events.kafka_offset IS 'Offset в партиции (offset — зарезервированное слово)';
-- <<< sql/05_landing/050_landing_events.sql

-- >>> sql/05_landing/055_ops_tables.sql
-- object : ops.build_params, ops.etl_runs, ops.stream_status, ops.reconcile_result
-- grain  : build_params и stream_status — 1 строка (id=1); etl_runs — 1 строка = 1 запуск;
--          reconcile_result — 1 строка = 1 проверка сверки batch vs stream
-- source : -
-- cc     : K0 §3, §4.3, §4.5
-- why    : служебное состояние ETL и потока переживает пересборку (IF NOT EXISTS, сид ON CONFLICT DO NOTHING);
--          сервисы пишут в ops.*, API/Grafana читают тонкие views mart.* (660_ops_views.sql)

CREATE TABLE IF NOT EXISTS ops.build_params (
    id         smallint PRIMARY KEY CHECK (id = 1),
    cutoff     date,
    updated_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

INSERT INTO ops.build_params (id, cutoff) VALUES (1, NULL)
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS ops.etl_runs (
    run_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ds             date NOT NULL,
    kind           text NOT NULL CHECK (kind IN ('batch', 'stream', 'demo')),
    status         text NOT NULL CHECK (status IN ('running', 'success', 'failed', 'blocked', 'published')),
    started_at     timestamp NOT NULL,
    finished_at    timestamp,
    dq_passed      smallint,
    dq_total       smallint,
    reconcile_diff numeric(14, 2),
    cutoff         date,
    note           text
);

CREATE TABLE IF NOT EXISTS ops.stream_status (
    id             smallint PRIMARY KEY CHECK (id = 1),
    last_event_ts  timestamp,
    events_total   bigint NOT NULL DEFAULT 0,
    events_per_sec numeric(10, 2) NOT NULL DEFAULT 0,
    lag_events     bigint NOT NULL DEFAULT 0,
    lag_sec        numeric(10, 2) NOT NULL DEFAULT 0,
    dlq_count      bigint NOT NULL DEFAULT 0,
    updated_at     timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

INSERT INTO ops.stream_status (id) VALUES (1)
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS ops.reconcile_result (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id       bigint NOT NULL REFERENCES ops.etl_runs (run_id),
    ds           date NOT NULL,
    day          date,
    check_code   text NOT NULL CHECK (check_code IN ('orders_count', 'revenue_sum', 'payments_sum')),
    batch_value  numeric(18, 2),
    stream_value numeric(18, 2),
    diff         numeric(18, 2) GENERATED ALWAYS AS (batch_value - stream_value) STORED,
    is_ok        boolean NOT NULL,
    checked_at   timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

COMMENT ON TABLE ops.build_params IS 'Параметры сборки; cutoff NULL = полная сборка';
COMMENT ON TABLE ops.etl_runs IS 'Учёт запусков ETL';
COMMENT ON TABLE ops.stream_status IS 'Состояние потока (одна строка)';
COMMENT ON TABLE ops.reconcile_result IS 'Сверка batch vs stream; diff = batch - stream';
-- <<< sql/05_landing/055_ops_tables.sql

-- >>> sql/05_landing/056_ops_stream_pause.sql
-- object : ops.stream_pause
-- grain  : 1 строка (id=1) = флаг паузы потока на время сборки
-- source : -
-- cc     : K3 §3.3, K0 §4.3
-- why    : пауза живёт дольше одного процесса задачи Airflow, поэтому это таблица, а не advisory lock;
--          ETL ставит run_id, ingestor первым в транзакции батча берёт SELECT ... FOR SHARE и при паузе откатывается;
--          IF NOT EXISTS, сид ON CONFLICT DO NOTHING — состояние переживает пересборку

CREATE TABLE IF NOT EXISTS ops.stream_pause (
    id        smallint PRIMARY KEY CHECK (id = 1),
    run_id    bigint,
    paused_at timestamp
);

INSERT INTO ops.stream_pause (id, run_id, paused_at) VALUES (1, NULL, NULL)
ON CONFLICT DO NOTHING;

COMMENT ON TABLE ops.stream_pause IS 'Пауза потока на время сборки; run_id IS NULL = потока ничто не держит (одна строка)';
-- <<< sql/05_landing/056_ops_stream_pause.sql

-- >>> sql/05_landing/057_replay_runs.sql
-- object : ops.replay_runs
-- grain  : 1 строка = 1 проигрывание датасета в поток (replay_id из события replay.completed)
-- source : -
-- cc     : K2 §5 (replay.completed), K2 §6 п.3, ASSUMPTION-K2-1
-- why    : ingestor фиксирует итоги реплея и момент догона (caught_up_at); «Контроль» и /api/status сверяют модель с expected;
--          IF NOT EXISTS: состояние переживает пересборку

CREATE TABLE IF NOT EXISTS ops.replay_runs (
    replay_id    uuid PRIMARY KEY,
    cutoff       date,
    events_total bigint,
    orders_total bigint,
    expected     jsonb NOT NULL,
    received_at  timestamp NOT NULL,
    caught_up_at timestamp
);

COMMENT ON TABLE ops.replay_runs IS 'Проигрывания датасета: итоги генератора (expected) и момент догона ingestor-ом';
-- <<< sql/05_landing/057_replay_runs.sql

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
-- cc     : пустые строки → NULL; статус приведён к нижнему регистру;
--          cutoff (ops.build_params): при заданном cutoff только заказы с purchased_at < cutoff (K0 §4.5, K3 §3.1)
-- why    : типы приводятся в одном месте, остальные слои читают только stg

CREATE VIEW stg.orders AS
WITH typed AS (
    SELECT
        NULLIF(TRIM(order_id), '')                                    AS order_id,
        NULLIF(TRIM(customer_id), '')                                 AS customer_id,
        LOWER(NULLIF(TRIM(order_status), ''))                         AS order_status,
        NULLIF(TRIM(order_purchase_timestamp), '')::timestamp         AS purchased_at,
        NULLIF(TRIM(order_approved_at), '')::timestamp                AS approved_at,
        NULLIF(TRIM(order_delivered_carrier_date), '')::timestamp     AS delivered_carrier_at,
        NULLIF(TRIM(order_delivered_customer_date), '')::timestamp    AS delivered_customer_at,
        NULLIF(TRIM(order_estimated_delivery_date), '')::timestamp    AS estimated_delivery_at
    FROM raw.orders
)

SELECT * FROM typed
WHERE (SELECT cutoff FROM ops.build_params WHERE id = 1) IS NULL
   OR purchased_at < (SELECT cutoff FROM ops.build_params WHERE id = 1);
-- <<< sql/20_staging/200_stg_orders.sql

-- >>> sql/20_staging/210_stg_order_items.sql
-- object : stg.order_items
-- grain  : 1 строка = 1 строка raw.order_items
-- source : raw.order_items
-- cc     : CC-09 (order_item_id — порядковый номер внутри заказа, не id)
--          cutoff: при заданном cutoff только позиции заказов из stg.orders (K3 §3.1)
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
FROM raw.order_items AS i
WHERE (SELECT cutoff FROM ops.build_params WHERE id = 1) IS NULL
   OR EXISTS (SELECT 1 FROM stg.orders AS o WHERE o.order_id = NULLIF(TRIM(i.order_id), ''));
-- <<< sql/20_staging/210_stg_order_items.sql

-- >>> sql/20_staging/220_stg_order_payments.sql
-- object : stg.order_payments
-- grain  : 1 строка = 1 платёжная запись заказа
-- source : raw.order_payments
-- cc     : installments = 0 сохраняется как есть (не подменяем на 1); payment_value не умножается на installments
--          cutoff: при заданном cutoff только позиции заказов из stg.orders (K3 §3.1)
-- why    : деньги в numeric(12,2), номера и рассрочка в int

CREATE VIEW stg.order_payments AS
SELECT
    NULLIF(TRIM(order_id), '')                        AS order_id,
    NULLIF(TRIM(payment_sequential), '')::int         AS payment_sequential,
    LOWER(NULLIF(TRIM(payment_type), ''))             AS payment_type,
    NULLIF(TRIM(payment_installments), '')::int       AS payment_installments,
    NULLIF(TRIM(payment_value), '')::numeric(12, 2)   AS payment_value
FROM raw.order_payments AS p
WHERE (SELECT cutoff FROM ops.build_params WHERE id = 1) IS NULL
   OR EXISTS (SELECT 1 FROM stg.orders AS o WHERE o.order_id = NULLIF(TRIM(p.order_id), ''));
-- <<< sql/20_staging/220_stg_order_payments.sql

-- >>> sql/20_staging/230_stg_order_reviews.sql
-- object : stg.order_reviews
-- grain  : 1 строка = 1 связь отзыва с заказом; ключ (review_id, order_id)
-- source : raw.order_reviews
-- cc     : review_id не уникален сам по себе, у 547 заказов несколько отзывов — DISTINCT не делаем
--          cutoff: при заданном cutoff только позиции заказов из stg.orders (K3 §3.1)
-- why    : оценка в int, пустой текст отзыва — NULL, а не пустая строка

CREATE VIEW stg.order_reviews AS
SELECT
    NULLIF(TRIM(review_id), '')                           AS review_id,
    NULLIF(TRIM(order_id), '')                            AS order_id,
    NULLIF(TRIM(review_score), '')::int                   AS review_score,
    NULLIF(TRIM(review_comment_title), '')                AS review_comment_title,
    NULLIF(TRIM(review_comment_message), '')              AS review_comment_message,
    NULLIF(TRIM(review_creation_date), '')::timestamp     AS review_created_at,
    NULLIF(TRIM(review_answer_timestamp), '')::timestamp  AS review_answered_at
FROM raw.order_reviews AS r
WHERE (SELECT cutoff FROM ops.build_params WHERE id = 1) IS NULL
   OR EXISTS (SELECT 1 FROM stg.orders AS o WHERE o.order_id = NULLIF(TRIM(r.order_id), ''));
-- <<< sql/20_staging/230_stg_order_reviews.sql

-- >>> sql/20_staging/240_stg_products.sql
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
-- <<< sql/20_staging/240_stg_products.sql

-- >>> sql/20_staging/250_stg_sellers.sql
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
-- <<< sql/20_staging/250_stg_sellers.sql

-- >>> sql/20_staging/260_stg_customers.sql
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
-- <<< sql/20_staging/260_stg_customers.sql

-- >>> sql/20_staging/270_stg_category_translation.sql
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
-- <<< sql/20_staging/270_stg_category_translation.sql

-- >>> sql/30_core_dim/300_dim_customer.sql
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
-- <<< sql/30_core_dim/300_dim_customer.sql

-- >>> sql/30_core_dim/310_dim_seller.sql
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
-- <<< sql/30_core_dim/310_dim_seller.sql

-- >>> sql/30_core_dim/320_dim_category.sql
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
-- <<< sql/30_core_dim/320_dim_category.sql

-- >>> sql/30_core_dim/330_dim_product.sql
-- object : core.dim_product
-- grain  : 1 строка = 1 товар; PK product_id
-- source : stg.products, core.dim_category
-- cc     : пустая категория → '__unknown__' + флаг is_missing_category; габариты nullable; is_inferred=false (заглушки из потока = true)
-- why    : категория — FK на справочник, исходное название сохраняется для прозрачности

CREATE TABLE core.dim_product AS
SELECT
    product_id,
    category_key,
    category_name,
    category_name IS NULL AS is_missing_category,
    name_length, description_length, photos_qty,
    weight_g, length_cm, height_cm, width_cm,
    false AS is_inferred
FROM stg.products;

ALTER TABLE core.dim_product ADD PRIMARY KEY (product_id);
ALTER TABLE core.dim_product
    ADD FOREIGN KEY (category_key) REFERENCES core.dim_category (category_key);
-- <<< sql/30_core_dim/330_dim_product.sql

-- >>> sql/40_core_fact/400_fact_order.sql
-- object : core.fact_order
-- grain  : 1 строка = 1 заказ; PK order_id
-- source : stg.orders, core.dim_order_status, core.dim_customer
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
ALTER TABLE core.fact_order
    ADD FOREIGN KEY (customer_id) REFERENCES core.dim_customer (customer_id);
-- <<< sql/40_core_fact/400_fact_order.sql

-- >>> sql/40_core_fact/410_fact_order_item.sql
-- object : core.fact_order_item
-- grain  : 1 строка = 1 позиция заказа; PK (order_id, order_item_id)
-- source : stg.order_items, core.dim_product, core.dim_seller
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
ALTER TABLE core.fact_order_item
    ADD FOREIGN KEY (product_id) REFERENCES core.dim_product (product_id);
ALTER TABLE core.fact_order_item
    ADD FOREIGN KEY (seller_id) REFERENCES core.dim_seller (seller_id);
CREATE INDEX ON core.fact_order_item (seller_id);
CREATE INDEX ON core.fact_order_item (product_id);
-- <<< sql/40_core_fact/410_fact_order_item.sql

-- >>> sql/40_core_fact/420_fact_order_payment.sql
-- object : core.fact_order_payment
-- grain  : 1 строка = 1 платёжная запись; PK (order_id, payment_sequential)
-- source : stg.order_payments
-- cc     : 1 заказ без оплаты; installments = 0 сохранён; сумма оплат ≠ сумме позиций у 639 заказов
-- why    : платёж — отдельный факт, с позициями соединяется только после агрегации до заказа

CREATE TABLE core.fact_order_payment AS
SELECT order_id, payment_sequential, payment_type, payment_installments, payment_value
FROM stg.order_payments;

ALTER TABLE core.fact_order_payment ADD PRIMARY KEY (order_id, payment_sequential);
ALTER TABLE core.fact_order_payment
    ADD FOREIGN KEY (order_id) REFERENCES core.fact_order (order_id);
-- <<< sql/40_core_fact/420_fact_order_payment.sql

-- >>> sql/40_core_fact/430_fact_order_review.sql
-- object : core.fact_order_review
-- grain  : 1 строка = 1 связь отзыва с заказом; PK (review_id, order_id)
-- source : stg.order_reviews
-- cc     : 547 заказов с несколькими отзывами — все записи сохраняются, оценка заказа = среднее
-- why    : отсутствие отзыва не равно нулевой оценке — заказ без отзыва просто не попадает сюда

CREATE TABLE core.fact_order_review AS
SELECT
    review_id, order_id, review_score,
    review_comment_title, review_comment_message,
    review_comment_message IS NOT NULL AS has_text,
    review_created_at, review_answered_at
FROM stg.order_reviews;

ALTER TABLE core.fact_order_review ADD PRIMARY KEY (review_id, order_id);
ALTER TABLE core.fact_order_review
    ADD FOREIGN KEY (order_id) REFERENCES core.fact_order (order_id);
ALTER TABLE core.fact_order_review
    ADD CHECK (review_score BETWEEN 1 AND 5);
-- <<< sql/40_core_fact/430_fact_order_review.sql

-- >>> sql/60_mart/600_v_sales_month.sql
-- object : mart.v_sales_month
-- grain  : 1 строка = 1 календарный месяц 2016-09..2018-10 (включая месяцы без заказов)
-- source : core.fact_order, core.fact_order_item, core.dim_order_status
-- cc     : FR-30 (выручка = SUM(price) по is_revenue, без freight, месяц по purchase); пустой месяц 2016-11
-- why    : обычный view: поток (ingestor) обновляет core, REFRESH не нужен; Q1-Q5 видят события сразу

CREATE VIEW mart.v_sales_month AS
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

COMMENT ON VIEW mart.v_sales_month IS
    'Выручка (SUM price, delivered) и число заказов по месяцу оформления; месяцы без заказов = 0';
-- <<< sql/60_mart/600_v_sales_month.sql

-- >>> sql/60_mart/605_v_sales_item.sql
-- object : mart.v_sales_item
-- grain  : 1 строка = 1 позиция заказа (order_id, order_item_id), все статусы заказа
-- source : core.fact_order_item, core.fact_order, core.dim_order_status, core.dim_seller, core.dim_product, core.dim_category, core.dim_customer
-- cc     : FR-30 выручка = SUM(price) по is_revenue, без freight; месяц по purchase; покупатель = customer_unique_id
-- why    : единая гранула позиции для выручки, единиц и срезов по продавцу/категории без JOIN фактов в панелях (К5)

CREATE VIEW mart.v_sales_item AS
SELECT
    i.order_id,
    i.order_item_id,
    o.purchased_at                                   AS purchase_ts,
    date_trunc('month', o.purchased_at)::date        AS purchase_month,
    o.order_status,
    COALESCE(st.is_revenue, FALSE)                   AS is_revenue,
    i.seller_id,
    s.state_normalized                               AS seller_state,
    c.category_key,
    c.label                                          AS category_label,
    cu.customer_unique_id,
    cu.state_normalized                              AS customer_state,
    i.price,
    i.freight_value
FROM core.fact_order_item i
LEFT JOIN core.fact_order o        ON o.order_id = i.order_id
LEFT JOIN core.dim_order_status st ON st.order_status = o.order_status
LEFT JOIN core.dim_seller s        ON s.seller_id = i.seller_id
LEFT JOIN core.dim_product p       ON p.product_id = i.product_id
LEFT JOIN core.dim_category c      ON c.category_key = COALESCE(p.category_key, '__unknown__')
LEFT JOIN core.dim_customer cu     ON cu.customer_id = o.customer_id;

COMMENT ON VIEW mart.v_sales_item IS 'Позиция заказа: выручка, фрахт и срезы месяц/статус/продавец/категория/покупатель';
-- <<< sql/60_mart/605_v_sales_item.sql

-- >>> sql/60_mart/610_order_summary.sql
-- object : mart.order_summary
-- grain  : 1 строка = 1 заказ (все 99 441, все статусы); PK order_id
-- source : core.fact_order, fact_order_item, fact_order_payment, fact_order_review, dim_customer, dim_order_status
-- cc     : 775 заказов без позиций, 1 без оплаты, 639 с расхождением оплаты; 8 delivered без даты вручения
-- why    : каждый поток сначала агрегируется до заказа отдельно — без fan-out (2 товара × 2 оплаты ≠ 4 строки)

CREATE VIEW mart.order_summary AS
WITH items AS (
    SELECT order_id,
           COUNT(*)                   AS line_count,
           SUM(price)                 AS goods_value,
           SUM(freight_value)         AS freight_value,
           COUNT(DISTINCT seller_id)  AS seller_count
    FROM core.fact_order_item
    GROUP BY order_id
),
payments AS (
    SELECT order_id, COUNT(*) AS payment_count, SUM(payment_value) AS payment_value
    FROM core.fact_order_payment
    GROUP BY order_id
),
reviews AS (
    SELECT order_id, COUNT(*) AS review_count, AVG(review_score)::numeric(4, 2) AS review_score_mean
    FROM core.fact_order_review
    GROUP BY order_id
),
base AS (
    SELECT
        o.order_id,
        o.order_status,
        s.is_revenue,
        c.customer_unique_id,
        c.state_normalized                          AS customer_state,
        o.purchased_at,
        date_trunc('month', o.purchased_at)::date   AS purchase_month,
        o.delivered_customer_at,
        o.estimated_delivery_at,
        COALESCE(i.line_count, 0)                   AS line_count,
        COALESCE(i.seller_count, 0)                 AS seller_count,
        i.goods_value,
        i.freight_value,
        i.goods_value + i.freight_value             AS order_value,
        COALESCE(p.payment_count, 0)                AS payment_count,
        p.payment_value,
        COALESCE(r.review_count, 0)                 AS review_count,
        r.review_score_mean,
        i.order_id IS NOT NULL                      AS has_items,
        p.order_id IS NOT NULL                      AS has_payments
    FROM core.fact_order o
    JOIN core.dim_order_status s ON s.order_status = o.order_status
    LEFT JOIN core.dim_customer c ON c.customer_id = o.customer_id
    LEFT JOIN items    i ON i.order_id = o.order_id
    LEFT JOIN payments p ON p.order_id = o.order_id
    LEFT JOIN reviews  r ON r.order_id = o.order_id
)
SELECT
    b.*,
    b.payment_value - b.order_value AS payment_delta,
    CASE
        WHEN NOT b.has_items AND NOT b.has_payments THEN 'Нет обеих сторон'
        WHEN NOT b.has_items                        THEN 'Нет позиций'
        WHEN NOT b.has_payments                     THEN 'Нет оплаты'
        WHEN b.payment_value = b.order_value        THEN 'Совпадает'
        ELSE 'Расхождение'
    END AS reconciliation,
    EXTRACT(EPOCH FROM b.delivered_customer_at - b.purchased_at) / 86400 AS delivery_days,
    b.delivered_customer_at::date - b.estimated_delivery_at::date        AS delay_days,
    (b.order_status = 'delivered' AND b.delivered_customer_at IS NOT NULL
        AND b.estimated_delivery_at IS NOT NULL
        AND b.delivered_customer_at >= b.purchased_at)                   AS is_valid_delivery
FROM base b;

COMMENT ON VIEW mart.order_summary IS
    'Один заказ: суммы позиций/оплат/отзывов, сверка оплаты, срок и опоздание доставки';
-- <<< sql/60_mart/610_order_summary.sql

-- >>> sql/60_mart/620_sales_marts.sql
-- object : mart.v_seller_sales, mart.v_category_sales
-- grain  : продавец; категория (по позициям доставленных заказов)
-- source : core.fact_order_item, core.fact_order, core.dim_order_status, core.dim_seller, core.dim_product, core.dim_category
-- cc     : FR-30 выручка = SUM(price) по is_revenue; выручка продавца — только его позиции, не весь чек
-- why    : гранула позиции: заказ с товарами разных продавцов делится между ними корректно

CREATE VIEW mart.v_seller_sales AS
SELECT
    i.seller_id,
    s.city,
    s.state,
    COUNT(DISTINCT i.order_id) AS orders,
    COUNT(*)                   AS units,
    SUM(i.price)               AS revenue
FROM core.fact_order_item i
JOIN core.fact_order o        ON o.order_id = i.order_id
JOIN core.dim_order_status st ON st.order_status = o.order_status AND st.is_revenue
LEFT JOIN core.dim_seller s   ON s.seller_id = i.seller_id
GROUP BY i.seller_id, s.city, s.state;

CREATE VIEW mart.v_category_sales AS
SELECT
    c.category_key,
    c.label,
    c.is_unknown,
    SUM(i.price) AS revenue,
    (100 * SUM(i.price) / SUM(SUM(i.price)) OVER ())::numeric(6, 2) AS share_pct
FROM core.fact_order_item i
JOIN core.fact_order o        ON o.order_id = i.order_id
JOIN core.dim_order_status st ON st.order_status = o.order_status AND st.is_revenue
LEFT JOIN core.dim_product p  ON p.product_id = i.product_id
LEFT JOIN core.dim_category c ON c.category_key = COALESCE(p.category_key, '__unknown__')
GROUP BY c.category_key, c.label, c.is_unknown;

COMMENT ON VIEW mart.v_seller_sales IS 'Выручка, заказы и единицы продавца по доставленным заказам';
COMMENT ON VIEW mart.v_category_sales IS 'Выручка и доля категории; unknown — отдельная строка, сумма = общей выручке';
-- <<< sql/60_mart/620_sales_marts.sql

-- >>> sql/60_mart/630_delivery_marts.sql
-- object : mart.v_delivery_review
-- grain  : 1 строка = 1 группа опоздания (В срок / 1–3 / 4–7 / >7 дней)
-- source : mart.order_summary
-- cc     : только валидные delivered с отзывом; оценка заказа = среднее его отзывов, затем среднее по заказам
-- why    : связь опоздания и оценки — наблюдение, не причинный эффект

CREATE VIEW mart.v_delivery_review AS
WITH g AS (
    SELECT
        CASE
            WHEN delay_days <= 0 THEN 1
            WHEN delay_days <= 3 THEN 2
            WHEN delay_days <= 7 THEN 3
            ELSE 4
        END AS group_order,
        review_score_mean
    FROM mart.order_summary
    WHERE is_valid_delivery AND review_score_mean IS NOT NULL
)
SELECT
    group_order,
    (ARRAY['В срок', '1–3 дня', '4–7 дней', 'Более 7 дней'])[group_order] AS delay_group,
    COUNT(*)                                AS orders,
    AVG(review_score_mean)::numeric(4, 2)   AS mean_score
FROM g
GROUP BY group_order
ORDER BY group_order;
-- <<< sql/60_mart/630_delivery_marts.sql

-- >>> sql/60_mart/640_v_kpi.sql
-- object : mart.v_kpi
-- grain  : 1 строка = ключевые показатели площадки за весь период
-- source : mart.order_summary
-- cc     : средний чек и доли — неаддитивны, считаются на грануле заказа/покупателя, а не суммой срезов
-- why    : одна точка правды для строки KPI на странице и для слайдов

CREATE VIEW mart.v_kpi AS
WITH customers AS (
    SELECT customer_unique_id, COUNT(*) AS orders
    FROM mart.order_summary
    GROUP BY customer_unique_id
)
SELECT
    (SELECT SUM(goods_value) FROM mart.order_summary WHERE is_revenue)                    AS revenue,
    (SELECT COUNT(*) FROM mart.order_summary WHERE is_revenue)                            AS delivered_orders,
    (SELECT ROUND(SUM(order_value) / COUNT(*), 2) FROM mart.order_summary WHERE is_revenue) AS avg_check,
    (SELECT COUNT(*) FROM customers)                                                      AS customers,
    (SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE orders >= 2) / COUNT(*), 2) FROM customers) AS repeat_pct,
    (SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE delay_days > 0) / COUNT(*), 2)
       FROM mart.order_summary WHERE is_valid_delivery)                                   AS late_pct,
    (SELECT ROUND((percentile_cont(0.5) WITHIN GROUP (ORDER BY delivery_days))::numeric, 1)
       FROM mart.order_summary WHERE is_valid_delivery)                                   AS median_delivery_days;
-- <<< sql/60_mart/640_v_kpi.sql

-- >>> sql/60_mart/650_metric_catalog.sql
-- object : mart.metric_catalog
-- grain  : 1 строка = 1 метрика (metric_code), 20 метрик
-- source : справочник; формулы считаются над mart.v_sales_item, mart.order_summary, mart.v_kpi
-- cc     : FR-30 выручка = Σ price по is_revenue; неаддитивные метрики (средний чек, доли, медиана, уникальные) не суммируются по срезам
-- why    : одна точка правды для формул, единиц и допустимых срезов: API /api/query, агент и подписи дашбордов

CREATE TABLE mart.metric_catalog (
    metric_code text PRIMARY KEY,
    name        text NOT NULL,
    description text NOT NULL,
    formula_sql text NOT NULL,
    source_view text NOT NULL,
    grain       text NOT NULL,
    additivity  text NOT NULL CHECK (additivity IN ('additive', 'semi', 'non')),
    is_additive boolean GENERATED ALWAYS AS (additivity = 'additive') STORED,
    unit        text NOT NULL CHECK (unit IN ('BRL', 'count', 'pct', 'days', 'score')),
    allowed_dims text[] NOT NULL,
    note        text
);

INSERT INTO mart.metric_catalog
    (metric_code, name, description, formula_sql, source_view, grain, additivity, unit, allowed_dims, note)
VALUES
    ('revenue', 'Выручка', 'Сумма цен позиций доставленных заказов, без фрахта',
     $f$SUM(price) FILTER (WHERE is_revenue)$f$,
     'mart.v_sales_item', 'позиция заказа', 'additive', 'BRL',
     ARRAY['month', 'customer_state', 'order_status', 'seller_state', 'seller_id', 'category'], NULL),
    ('units_sold', 'Продано единиц', 'Число позиций доставленных заказов',
     $f$COUNT(*) FILTER (WHERE is_revenue)$f$,
     'mart.v_sales_item', 'позиция заказа', 'additive', 'count',
     ARRAY['month', 'customer_state', 'order_status', 'seller_state', 'seller_id', 'category'], NULL),
    ('freight_total', 'Фрахт', 'Сумма стоимости доставки по позициям доставленных заказов',
     $f$SUM(freight_value) FILTER (WHERE is_revenue)$f$,
     'mart.v_sales_item', 'позиция заказа', 'additive', 'BRL',
     ARRAY['month', 'customer_state', 'order_status', 'seller_state', 'seller_id', 'category'], NULL),
    ('sellers_active', 'Активные продавцы', 'Число продавцов с доставленными позициями',
     $f$COUNT(DISTINCT seller_id) FILTER (WHERE is_revenue)$f$,
     'mart.v_sales_item', 'позиция заказа', 'non', 'count',
     ARRAY['month', 'customer_state', 'order_status', 'seller_state', 'seller_id', 'category'],
     'Уникальные: сумма по срезам завышает итог'),
    ('orders_total', 'Заказы', 'Число заказов во всех статусах',
     $f$COUNT(*)$f$,
     'mart.order_summary', 'заказ', 'additive', 'count',
     ARRAY['month', 'customer_state', 'order_status'], NULL),
    ('orders_delivered', 'Доставленные заказы', 'Число заказов со статусом, дающим выручку',
     $f$COUNT(*) FILTER (WHERE is_revenue)$f$,
     'mart.order_summary', 'заказ', 'additive', 'count',
     ARRAY['month', 'customer_state', 'order_status'], NULL),
    ('orders_canceled', 'Отменённые заказы', 'Число заказов со статусом canceled',
     $f$COUNT(*) FILTER (WHERE order_status = 'canceled')$f$,
     'mart.order_summary', 'заказ', 'additive', 'count',
     ARRAY['month', 'customer_state', 'order_status'], NULL),
    ('cancel_rate_pct', 'Доля отмен', 'Доля отменённых заказов от всех, %',
     $f$ROUND(100.0 * COUNT(*) FILTER (WHERE order_status = 'canceled') / NULLIF(COUNT(*), 0), 2)$f$,
     'mart.order_summary', 'заказ', 'non', 'pct',
     ARRAY['month', 'customer_state', 'order_status'], 'Доля: не суммируется по срезам'),
    ('gmv_with_freight', 'GMV с доставкой', 'Сумма цен и фрахта доставленных заказов',
     $f$SUM(order_value) FILTER (WHERE is_revenue)$f$,
     'mart.order_summary', 'заказ', 'additive', 'BRL',
     ARRAY['month', 'customer_state', 'order_status'], 'Справочно; выручка считается без фрахта'),
    ('avg_check', 'Средний чек', 'Средняя стоимость доставленного заказа (цены + фрахт)',
     $f$ROUND(SUM(order_value) FILTER (WHERE is_revenue) / NULLIF(COUNT(*) FILTER (WHERE is_revenue), 0), 2)$f$,
     'mart.order_summary', 'заказ', 'non', 'BRL',
     ARRAY['month', 'customer_state', 'order_status'], 'Отношение: не суммируется по срезам'),
    ('avg_items_per_order', 'Позиций в заказе', 'Среднее число позиций в доставленном заказе',
     $f$ROUND(AVG(line_count) FILTER (WHERE is_revenue), 2)$f$,
     'mart.order_summary', 'заказ', 'non', 'count',
     ARRAY['month', 'customer_state', 'order_status'], NULL),
    ('payments_total', 'Сумма оплат', 'Сумма платежей по доставленным заказам',
     $f$SUM(payment_value) FILTER (WHERE is_revenue)$f$,
     'mart.order_summary', 'заказ', 'additive', 'BRL',
     ARRAY['month', 'customer_state', 'order_status'], NULL),
    ('payment_mismatch_orders', 'Заказы с расхождением оплаты', 'Число заказов, где оплата не равна стоимости позиций',
     $f$COUNT(*) FILTER (WHERE reconciliation = 'Расхождение')$f$,
     'mart.order_summary', 'заказ', 'additive', 'count',
     ARRAY['month', 'customer_state', 'order_status'], NULL),
    ('customers', 'Покупатели', 'Число уникальных покупателей (customer_unique_id)',
     $f$COUNT(DISTINCT customer_unique_id)$f$,
     'mart.order_summary', 'заказ', 'non', 'count',
     ARRAY['month', 'customer_state', 'order_status'], 'Уникальные: сумма по срезам завышает итог'),
    ('late_pct', 'Доля опозданий', 'Доля доставок позже обещанной даты среди корректных доставок, %',
     $f$ROUND(100.0 * COUNT(*) FILTER (WHERE is_valid_delivery AND delay_days > 0) / NULLIF(COUNT(*) FILTER (WHERE is_valid_delivery), 0), 2)$f$,
     'mart.order_summary', 'заказ', 'non', 'pct',
     ARRAY['month', 'customer_state', 'order_status'], 'Доля: не суммируется по срезам'),
    ('avg_delivery_days', 'Средний срок доставки', 'Среднее число дней от покупки до вручения',
     $f$ROUND((AVG(delivery_days) FILTER (WHERE is_valid_delivery))::numeric, 1)$f$,
     'mart.order_summary', 'заказ', 'non', 'days',
     ARRAY['month', 'customer_state', 'order_status'], NULL),
    ('median_delivery_days', 'Медианный срок доставки', 'Медиана дней от покупки до вручения',
     $f$ROUND((percentile_cont(0.5) WITHIN GROUP (ORDER BY delivery_days) FILTER (WHERE is_valid_delivery))::numeric, 1)$f$,
     'mart.order_summary', 'заказ', 'non', 'days',
     ARRAY['month', 'customer_state', 'order_status'], NULL),
    ('avg_review_score', 'Средняя оценка', 'Среднее значение средних оценок заказов',
     $f$ROUND(AVG(review_score_mean), 2)$f$,
     'mart.order_summary', 'заказ', 'non', 'score',
     ARRAY['month', 'customer_state', 'order_status'], NULL),
    ('reviewed_orders_pct', 'Доля заказов с отзывом', 'Доля заказов хотя бы с одним отзывом, %',
     $f$ROUND(100.0 * COUNT(*) FILTER (WHERE review_count > 0) / NULLIF(COUNT(*), 0), 2)$f$,
     'mart.order_summary', 'заказ', 'non', 'pct',
     ARRAY['month', 'customer_state', 'order_status'], 'Доля: не суммируется по срезам'),
    ('repeat_customers_pct', 'Доля повторных покупателей', 'Доля покупателей с двумя и более заказами, %',
     $f$MAX(repeat_pct)$f$,
     'mart.v_kpi', 'площадка за весь период', 'non', 'pct',
     ARRAY[]::text[], 'Только итог за период, срезов нет');

COMMENT ON TABLE mart.metric_catalog IS 'Каталог метрик: формула, источник, аддитивность, единица и допустимые срезы';
-- <<< sql/60_mart/650_metric_catalog.sql

-- >>> sql/60_mart/655_dimension_catalog.sql
-- object : mart.dimension_catalog
-- grain  : 1 строка = 1 срез (dim_code)
-- source : справочник; колонки mart.order_summary и mart.v_sales_item
-- cc     : срез допустим для метрики только если его колонка есть в source_view метрики
-- why    : API и агент проверяют допустимость срезов по каталогу, а не по зашитым спискам

CREATE TABLE mart.dimension_catalog (
    dim_code     text PRIMARY KEY,
    name         text NOT NULL,
    column_name  text NOT NULL,
    dim_type     text NOT NULL CHECK (dim_type IN ('categorical', 'time')),
    source_views text[] NOT NULL
);

INSERT INTO mart.dimension_catalog (dim_code, name, column_name, dim_type, source_views) VALUES
    ('month',          'Месяц покупки',     'purchase_month',  'time',        ARRAY['mart.order_summary', 'mart.v_sales_item']),
    ('customer_state', 'Штат покупателя',   'customer_state',  'categorical', ARRAY['mart.order_summary', 'mart.v_sales_item']),
    ('order_status',   'Статус заказа',     'order_status',    'categorical', ARRAY['mart.order_summary', 'mart.v_sales_item']),
    ('seller_state',   'Штат продавца',     'seller_state',    'categorical', ARRAY['mart.v_sales_item']),
    ('seller_id',      'Продавец',          'seller_id',       'categorical', ARRAY['mart.v_sales_item']),
    ('category',       'Категория товара',  'category_label',  'categorical', ARRAY['mart.v_sales_item']);

COMMENT ON TABLE mart.dimension_catalog IS 'Каталог срезов: код, колонка и представления, где срез применим';
-- <<< sql/60_mart/655_dimension_catalog.sql

-- >>> sql/60_mart/660_ops_views.sql
-- object : mart.build_params, mart.etl_runs, mart.stream_status, mart.reconcile_result
-- grain  : как у одноимённых таблиц ops.*
-- source : ops.build_params, ops.etl_runs, ops.stream_status, ops.reconcile_result
-- cc     : K0 §3.2, §4.3
-- why    : API и Grafana читают только mart под app_ro; тонкие views дают доступ к служебным данным без прав на ops

CREATE VIEW mart.build_params AS SELECT * FROM ops.build_params;
CREATE VIEW mart.etl_runs AS SELECT * FROM ops.etl_runs;
CREATE VIEW mart.stream_status AS SELECT * FROM ops.stream_status;
CREATE VIEW mart.reconcile_result AS SELECT * FROM ops.reconcile_result;
-- <<< sql/60_mart/660_ops_views.sql

-- >>> sql/60_mart/665_replay_view.sql
-- object : mart.replay_runs
-- grain  : как у ops.replay_runs
-- source : ops.replay_runs
-- cc     : K2 §6 п.3
-- why    : API (/api/status, «Контроль») читает только mart под app_ro; view даёт доступ к итогам реплея без прав на ops

CREATE VIEW mart.replay_runs AS SELECT * FROM ops.replay_runs;
-- <<< sql/60_mart/665_replay_view.sql

-- >>> sql/60_mart/670_v_payment.sql
-- object : mart.v_payment
-- grain  : 1 строка = 1 платёж заказа (order_id, payment_sequential), все статусы заказа
-- source : core.fact_order_payment, mart.order_summary
-- cc     : 1 заказ без оплаты не попадает в витрину (нет платежа); значения оплаты как в core, расхождение с позициями не правим
-- why    : срез способов оплаты для D1 без JOIN фактов в панелях: платёж ровно один раз, срезы заказа берутся из order_summary

CREATE VIEW mart.v_payment AS
SELECT
    p.order_id,
    p.payment_sequential,
    o.purchase_month,
    o.customer_state,
    p.payment_type,
    p.payment_installments  AS installments,
    p.payment_value,
    COALESCE(o.is_revenue, FALSE) AS is_revenue
FROM core.fact_order_payment p
LEFT JOIN mart.order_summary o ON o.order_id = p.order_id;

COMMENT ON VIEW mart.v_payment IS 'Платёж заказа: способ, рассрочка, сумма и срезы месяц/штат покупателя/is_revenue';
-- <<< sql/60_mart/670_v_payment.sql

-- >>> sql/60_mart/671_v_delivery.sql
-- object : mart.v_delivery
-- grain  : 1 строка = 1 заказ со статусом delivered; PK order_id
-- source : mart.order_summary, core.fact_order_item, core.dim_seller, core.dim_product, core.dim_category
-- cc     : 8 delivered без даты вручения и невалидные даты: has_valid_dates = FALSE, флаги и late_bucket = NULL; доставка и опоздание не пересчитываются
-- why    : основной продавец и категория заказа (по наибольшей сумме price, при равенстве по id/названию) дают срез D2 без JOIN фактов в панелях

CREATE VIEW mart.v_delivery AS
WITH seller_pick AS (
    SELECT DISTINCT ON (order_id) order_id, seller_state
    FROM (
        SELECT i.order_id, i.seller_id, s.state_normalized AS seller_state, SUM(i.price) AS price_sum
        FROM core.fact_order_item i
        LEFT JOIN core.dim_seller s ON s.seller_id = i.seller_id
        GROUP BY i.order_id, i.seller_id, s.state_normalized
    ) t
    ORDER BY order_id, price_sum DESC NULLS LAST, seller_id
),
category_pick AS (
    SELECT DISTINCT ON (order_id) order_id, category_label
    FROM (
        SELECT i.order_id, c.label AS category_label, SUM(i.price) AS price_sum
        FROM core.fact_order_item i
        LEFT JOIN core.dim_product p  ON p.product_id = i.product_id
        LEFT JOIN core.dim_category c ON c.category_key = COALESCE(p.category_key, '__unknown__')
        GROUP BY i.order_id, c.label
    ) t
    ORDER BY order_id, price_sum DESC NULLS LAST, category_label
)
SELECT
    o.order_id,
    o.purchase_month,
    o.customer_state,
    sp.seller_state                                  AS seller_state_main,
    cp.category_label                                AS category_main,
    o.delivery_days,
    o.delay_days,
    CASE WHEN o.is_valid_delivery THEN o.delay_days <= 0 END AS is_on_time,
    CASE WHEN o.is_valid_delivery THEN o.delay_days > 0 END  AS is_late,
    o.is_valid_delivery                              AS has_valid_dates,
    o.review_score_mean,
    CASE
        WHEN NOT o.is_valid_delivery THEN NULL
        WHEN o.delay_days <= 0       THEN 'on_time'
        WHEN o.delay_days <= 3       THEN '1-3'
        WHEN o.delay_days <= 7       THEN '4-7'
        ELSE '8+'
    END                                              AS late_bucket
FROM mart.order_summary o
LEFT JOIN seller_pick   sp ON sp.order_id = o.order_id
LEFT JOIN category_pick cp ON cp.order_id = o.order_id
WHERE o.order_status = 'delivered';

COMMENT ON VIEW mart.v_delivery IS 'Delivered-заказ: срок и опоздание из order_summary, основной продавец/категория, корзина опоздания';
-- <<< sql/60_mart/671_v_delivery.sql

-- >>> sql/60_mart/672_v_delivery_item.sql
-- object : mart.v_delivery_item
-- grain  : 1 строка = 1 позиция delivered-заказа (order_id, order_item_id)
-- source : core.fact_order_item, core.fact_order, core.dim_seller, mart.order_summary
-- cc     : is_shipped_late = передача перевозчику позже shipping_limit; NULL, если одной из дат нет; даты как в core
-- why    : срез по продавцу для D2 на грануле позиции без JOIN фактов в панелях; оценка и штат покупателя берутся из order_summary

CREATE VIEW mart.v_delivery_item AS
SELECT
    i.order_id,
    i.order_item_id,
    os.purchase_month,
    i.seller_id,
    s.state_normalized                                          AS seller_state,
    os.customer_state,
    o.delivered_carrier_at > i.shipping_limit_at                AS is_shipped_late,
    EXTRACT(EPOCH FROM o.delivered_carrier_at - i.shipping_limit_at) / 86400 AS ship_delay_days,
    os.review_score_mean
FROM core.fact_order_item i
LEFT JOIN core.fact_order o     ON o.order_id = i.order_id
LEFT JOIN core.dim_seller s     ON s.seller_id = i.seller_id
LEFT JOIN mart.order_summary os ON os.order_id = i.order_id
WHERE o.order_status = 'delivered';

COMMENT ON VIEW mart.v_delivery_item IS 'Позиция delivered-заказа: опоздание передачи перевозчику относительно shipping_limit, срезы продавец/штат';
-- <<< sql/60_mart/672_v_delivery_item.sql

-- >>> sql/60_mart/673_v_customer.sql
-- object : mart.v_customer
-- grain  : 1 строка = 1 покупатель (customer_unique_id), все статусы заказов; ключ customer_unique_id
-- source : mart.order_summary, mart.v_sales_item
-- cc     : покупатель = customer_unique_id; выручка = Σ goods_value по is_revenue (без freight); first_category = категория первой позиции первого заказа
-- why    : гранула покупателя для D3 (доля вернувшихся, выручка и заказы на покупателя) без пересчёта в панелях; orders_count совпадает с customers в mart.v_kpi

CREATE VIEW mart.v_customer AS
WITH order_category AS (
    SELECT DISTINCT ON (order_id) order_id, category_label
    FROM mart.v_sales_item
    ORDER BY order_id, order_item_id
),
orders AS (
    SELECT
        os.customer_unique_id,
        os.customer_state,
        os.purchase_month,
        os.is_revenue,
        os.goods_value,
        oc.category_label,
        ROW_NUMBER() OVER (PARTITION BY os.customer_unique_id ORDER BY os.purchased_at, os.order_id)           AS seq_first,
        ROW_NUMBER() OVER (PARTITION BY os.customer_unique_id ORDER BY os.purchased_at DESC, os.order_id DESC) AS seq_last
    FROM mart.order_summary os
    LEFT JOIN order_category oc ON oc.order_id = os.order_id
)
SELECT
    customer_unique_id,
    MAX(purchase_month)  FILTER (WHERE seq_first = 1)                 AS first_order_month,
    MAX(category_label)  FILTER (WHERE seq_first = 1)                 AS first_category,
    MAX(customer_state)  FILTER (WHERE seq_last = 1)                  AS last_state,
    COUNT(*)                                                          AS orders_count,
    COUNT(*)             FILTER (WHERE is_revenue)                    AS delivered_orders,
    COALESCE(SUM(goods_value) FILTER (WHERE is_revenue), 0)           AS revenue_total,
    COUNT(*) >= 2                                                     AS is_repeat
FROM orders
GROUP BY customer_unique_id;

COMMENT ON VIEW mart.v_customer IS 'Покупатель (customer_unique_id): первый месяц и категория, последний штат, заказы, выручка, признак повторного';
-- <<< sql/60_mart/673_v_customer.sql

-- >>> sql/60_mart/674_v_cohort.sql
-- object : mart.v_order_seq, mart.v_cohort_retention
-- grain  : v_order_seq = 1 заказ (order_id, все статусы); v_cohort_retention = когорта × месяц жизни × штат первого заказа × категория первого заказа
-- source : mart.order_summary, mart.v_sales_item, mart.v_order_seq
-- cc     : покупатель = customer_unique_id; когорта = месяц первого заказа; удержание неаддитивно: SUM(active_customers) / SUM(cohort_size), не AVG(retention_rate)
-- why    : номер заказа покупателя для «новые / повторные» и матрица удержания 0..24 месяца для D3; месяцы вне наблюдаемого периода не выводятся, чтобы не занижать долю

CREATE VIEW mart.v_order_seq AS
WITH order_category AS (
    SELECT DISTINCT ON (order_id) order_id, category_label
    FROM mart.v_sales_item
    ORDER BY order_id, order_item_id
)
SELECT
    os.order_id,
    os.customer_unique_id,
    os.customer_state,
    os.purchase_month,
    FIRST_VALUE(oc.category_label) OVER (
        PARTITION BY os.customer_unique_id ORDER BY os.purchased_at, os.order_id
    )                                                                                          AS first_category,
    ROW_NUMBER() OVER (PARTITION BY os.customer_unique_id ORDER BY os.purchased_at, os.order_id) AS customer_order_seq,
    ROW_NUMBER() OVER (PARTITION BY os.customer_unique_id ORDER BY os.purchased_at, os.order_id) = 1 AS is_first_order
FROM mart.order_summary os
LEFT JOIN order_category oc ON oc.order_id = os.order_id;

COMMENT ON VIEW mart.v_order_seq IS 'Заказ с порядковым номером у покупателя (customer_unique_id) и категорией его первого заказа';

CREATE VIEW mart.v_cohort_retention AS
WITH firsts AS (
    SELECT customer_unique_id,
           purchase_month  AS cohort_month,
           customer_state  AS first_state,
           first_category
    FROM mart.v_order_seq
    WHERE is_first_order
),
cohorts AS (
    SELECT cohort_month, first_state, first_category, COUNT(*) AS cohort_size
    FROM firsts
    GROUP BY cohort_month, first_state, first_category
),
activity AS (
    SELECT
        f.cohort_month,
        f.first_state,
        f.first_category,
        ((EXTRACT(YEAR FROM s.purchase_month) - EXTRACT(YEAR FROM f.cohort_month)) * 12
         + EXTRACT(MONTH FROM s.purchase_month) - EXTRACT(MONTH FROM f.cohort_month))::int AS month_offset,
        COUNT(DISTINCT s.customer_unique_id) AS active_customers
    FROM mart.v_order_seq s
    JOIN firsts f ON f.customer_unique_id = s.customer_unique_id
    GROUP BY 1, 2, 3, 4
),
bounds AS (
    SELECT MAX(purchase_month) AS last_month FROM mart.v_order_seq
)
SELECT
    c.cohort_month,
    g.month_offset,
    c.first_state,
    c.first_category,
    c.cohort_size,
    COALESCE(a.active_customers, 0)                                         AS active_customers,
    ROUND(COALESCE(a.active_customers, 0)::numeric / c.cohort_size, 4)      AS retention_rate
FROM cohorts c
CROSS JOIN bounds b
CROSS JOIN generate_series(0, 24) AS g(month_offset)
LEFT JOIN activity a
       ON a.cohort_month = c.cohort_month
      AND a.month_offset = g.month_offset
      AND a.first_state IS NOT DISTINCT FROM c.first_state
      AND a.first_category IS NOT DISTINCT FROM c.first_category
WHERE (c.cohort_month + make_interval(months => g.month_offset))::date <= b.last_month;

COMMENT ON VIEW mart.v_cohort_retention IS 'Удержание: когорта (месяц 1-го заказа) × месяц жизни 0..24 × штат × категория 1-го заказа; только наблюдаемые месяцы';
-- <<< sql/60_mart/674_v_cohort.sql

-- >>> sql/60_mart/675_v_stream_throughput.sql
-- object : mart.v_stream_throughput
-- grain  : 1 строка = 1 минута (UTC, date_trunc по received_at) за последние 60 минут
-- source : landing.events
-- cc     : K0 §4.2 (received_at UTC, status), K4 §4 (источник D4 timeseries)
-- why    : пропускная способность потока по минутам для панели D4 Pipeline; VIEW — данные потока видны сразу, без REFRESH

CREATE VIEW mart.v_stream_throughput AS
SELECT
    date_trunc('minute', received_at) AS minute,
    COUNT(*) AS events,
    COUNT(*) FILTER (WHERE status = 'applied') AS applied,
    COUNT(*) FILTER (WHERE status = 'error') AS errors
FROM landing.events
WHERE received_at >= (now() AT TIME ZONE 'utc') - INTERVAL '60 minutes'
GROUP BY date_trunc('minute', received_at);
-- <<< sql/60_mart/675_v_stream_throughput.sql

-- >>> sql/70_answers/700_answers_q01_q05.sql
-- object : mart.q01..q05 — ответы на вопросы аналитиков (docs/tasks.md, блок А)
-- grain  : по каждому вопросу — своя (месяц / продавец / одна строка / категория)
-- source : только mart.* и core.* — не raw
-- cc     : контрольные цифры проверяются в sql/80_dq/810_dq_checks.sql
-- why    : вопрос = view поверх витрины; новый вопрос добавляется одним view

-- Q1. Выручка и число заказов по месяцам, 2016-09..2018-08 (24 строки, 2016-11 = 0)
CREATE VIEW mart.q01_revenue_by_month AS
SELECT month, orders, revenue
FROM mart.v_sales_month
WHERE month BETWEEN DATE '2016-09-01' AND DATE '2018-08-01'
ORDER BY month;

-- Q2. Топ-10 продавцов по выручке — только их позиции
CREATE VIEW mart.q02_top_sellers AS
SELECT seller_id, city, state, orders, units, revenue
FROM mart.v_seller_sales
ORDER BY revenue DESC, seller_id
LIMIT 10;

-- Q3. Средний чек — на уровне заказа (товар + доставка), плюс строки и единицы на заказ
CREATE VIEW mart.q03_avg_check AS
SELECT
    ROUND(SUM(order_value) / COUNT(*), 2)  AS avg_check,
    ROUND(AVG(line_count), 4)              AS avg_lines,
    ROUND(AVG(line_count), 4)              AS avg_units
FROM mart.order_summary
WHERE is_revenue;

-- Q4. Покупатели (customer_unique_id) и доля вернувшихся за второй покупкой
CREATE VIEW mart.q04_repeat_customers AS
WITH c AS (
    SELECT customer_unique_id, COUNT(*) AS orders
    FROM mart.order_summary
    GROUP BY customer_unique_id
)
SELECT
    COUNT(*)                                                        AS customers,
    COUNT(*) FILTER (WHERE orders >= 2)                             AS returned,
    ROUND(100.0 * COUNT(*) FILTER (WHERE orders >= 2) / COUNT(*), 2) AS returned_pct
FROM c;

-- Q5. Выручка по категориям с долей; unknown — отдельная категория, сумма = общей выручке
CREATE VIEW mart.q05_revenue_by_category AS
SELECT label AS category, revenue, share_pct
FROM mart.v_category_sales
ORDER BY revenue DESC;
-- <<< sql/70_answers/700_answers_q01_q05.sql

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

-- >>> sql/80_dq/805_dq_marts.sql
-- object : mart.v_layer_rows, mart.v_raw_missingness
-- grain  : таблица источника; колонка источника
-- source : raw.*, core.*
-- cc     : строки не теряются между raw и core; пропуски в raw сохраняются, а не «лечатся»
-- why    : самопроверка видна на странице, а не только в логе сборки

-- при заданном cutoff (ops.build_params) raw-сторона заказов и их позиций/платежей/отзывов считается с тем же фильтром, что в stg (K3 §3.1)
CREATE VIEW mart.v_layer_rows AS
WITH p AS (
    SELECT (SELECT cutoff FROM ops.build_params WHERE id = 1) AS cutoff
),

ro AS (
    SELECT NULLIF(TRIM(o.order_id), '') AS order_id
    FROM raw.orders AS o
    CROSS JOIN p
    WHERE p.cutoff IS NULL
        OR NULLIF(TRIM(o.order_purchase_timestamp), '')::timestamp < p.cutoff
)

SELECT * FROM (VALUES
    ('orders',              (SELECT COUNT(*) FROM ro),                               (SELECT COUNT(*) FROM core.fact_order)),
    ('order_items',         (SELECT COUNT(*) FROM raw.order_items AS t, p
                             WHERE p.cutoff IS NULL OR EXISTS (SELECT 1 FROM ro WHERE ro.order_id = NULLIF(TRIM(t.order_id), ''))),
                            (SELECT COUNT(*) FROM core.fact_order_item)),
    ('order_payments',      (SELECT COUNT(*) FROM raw.order_payments AS t, p
                             WHERE p.cutoff IS NULL OR EXISTS (SELECT 1 FROM ro WHERE ro.order_id = NULLIF(TRIM(t.order_id), ''))),
                            (SELECT COUNT(*) FROM core.fact_order_payment)),
    ('order_reviews',       (SELECT COUNT(*) FROM raw.order_reviews AS t, p
                             WHERE p.cutoff IS NULL OR EXISTS (SELECT 1 FROM ro WHERE ro.order_id = NULLIF(TRIM(t.order_id), ''))),
                            (SELECT COUNT(*) FROM core.fact_order_review)),
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
-- <<< sql/80_dq/805_dq_marts.sql

-- >>> sql/80_dq/810_dq_checks.sql
-- object : проверки DQ (наполнение mart.dq_result)
-- grain  : 1 INSERT = 1 проверка
-- source : raw.*, core.*, mart.*
-- cc     : DQ-xx из ТЗ §9; контроли Q1–Q5 из tasks.md; инварианты EDA-ноутбука (notebooks/01_*)
-- why    : новая проверка = новая строка в VALUES по этому же шаблону;
--          при cutoff (ops.build_params) константные эталоны (is_const) пишутся passed=true, expected='skip: cutoff' (K3 §3.1)

-- 1. Полнота: ни одна строка raw не потеряна в модели
INSERT INTO mart.dq_result (check_id, description, expected, actual, passed)
SELECT 'DQ-01-' || source_table, 'строк в модели столько же, сколько в raw.' || source_table,
       raw_rows::text, model_rows::text, raw_rows = model_rows
FROM mart.v_layer_rows;

-- 2. Инварианты данных и контроли вопросов
INSERT INTO mart.dq_result (check_id, description, expected, actual, passed)
SELECT
    t.check_id,
    t.description,
    CASE WHEN t.is_const AND c.cutoff IS NOT NULL THEN 'skip: cutoff' ELSE t.expected END,
    t.actual,
    (t.is_const AND c.cutoff IS NOT NULL) OR t.expected = t.actual
FROM (VALUES
    ('DQ-02', 'нет статусов unknown',
     '0', (SELECT COUNT(*)::text FROM core.fact_order WHERE order_status = 'unknown'), FALSE),
    ('DQ-03', 'заказов без позиций (сохраняются, не удаляются)',
     '775', (SELECT COUNT(*)::text FROM mart.order_summary WHERE NOT has_items), TRUE),
    ('DQ-04', 'заказов без оплаты',
     '1', (SELECT COUNT(*)::text FROM mart.order_summary WHERE NOT has_payments), TRUE),
    ('DQ-05', 'заказов с несколькими отзывами (все отзывы сохранены)',
     '547', (SELECT COUNT(*)::text FROM mart.order_summary WHERE review_count > 1), TRUE),
    ('DQ-06', 'товаров без категории → __unknown__',
     '610', (SELECT COUNT(*)::text FROM core.dim_product WHERE is_missing_category), TRUE),
    ('DQ-07', 'категорий без перевода',
     '2', (SELECT COUNT(*)::text FROM core.dim_category WHERE is_untranslated), TRUE),
    ('DQ-08', 'расхождений оплаты: всего / больше копейки',
     '639 / 366', (SELECT COUNT(*) FILTER (WHERE reconciliation = 'Расхождение') || ' / '
                       || COUNT(*) FILTER (WHERE ABS(payment_delta) > 0.01) FROM mart.order_summary), TRUE),
    ('DQ-09', 'delivered без даты вручения (в продажах есть, в сроках нет)',
     '8', (SELECT COUNT(*)::text FROM mart.order_summary WHERE order_status = 'delivered' AND delivered_customer_at IS NULL), TRUE),
    ('DQ-10', 'сумма позиций по заказам = сумме позиций',
     (SELECT SUM(price)::text FROM core.fact_order_item), (SELECT SUM(goods_value)::text FROM mart.order_summary), FALSE),
    ('DQ-11', 'сумма оплат по заказам = сумме оплат',
     (SELECT SUM(payment_value)::text FROM core.fact_order_payment), (SELECT SUM(payment_value)::text FROM mart.order_summary), FALSE),
    ('DQ-12', 'выручка: по продавцам = по категориям = по месяцам',
     (SELECT SUM(revenue)::text FROM mart.v_sales_month),
     (SELECT CASE WHEN (SELECT SUM(revenue) FROM mart.v_seller_sales) = (SELECT SUM(revenue) FROM mart.v_category_sales)
                  THEN (SELECT SUM(revenue)::text FROM mart.v_seller_sales) ELSE 'не сходится' END), FALSE),
    ('Q1-CTRL', 'Q1: 24 месяца, итого выручка',
     '24 / 13221498.11', (SELECT COUNT(*) || ' / ' || SUM(revenue) FROM mart.q01_revenue_by_month), TRUE),
    ('Q1-ZERO', 'Q1: один месяц без выручки — 2016-11',
     '2016-11-01', (SELECT string_agg(month::text, ',') FROM mart.q01_revenue_by_month WHERE revenue = 0), TRUE),
    ('Q2-CTRL', 'Q2: выручка первого продавца',
     '226987.93', (SELECT revenue::text FROM mart.q02_top_sellers LIMIT 1), TRUE),
    ('Q3-CTRL', 'Q3: средний чек заказа',
     '159.88', (SELECT avg_check::text FROM mart.q03_avg_check), TRUE),
    ('Q4-CTRL', 'Q4: покупателей / вернулись, %',
     '96096 / 3.12', (SELECT customers || ' / ' || returned_pct FROM mart.q04_repeat_customers), TRUE),
    ('Q5-CTRL', 'Q5: категорий / у крупнейшей / сумма',
     '74 / 1233131.72 / 13221498.11',
     (SELECT COUNT(*) || ' / ' || MAX(revenue) || ' / ' || SUM(revenue) FROM mart.q05_revenue_by_category), TRUE)
) AS t(check_id, description, expected, actual, is_const)
CROSS JOIN (SELECT (SELECT cutoff FROM ops.build_params WHERE id = 1) AS cutoff) AS c;
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

-- >>> sql/90_grants/900_grants.sql
-- object : гранты ролей app_ro и ingestor
-- grain  : -
-- source : -
-- cc     : NFR (разграничение доступа), K0 §3.3, §4.4
-- why    : схемы stg/core/mart пересоздаются на каждой сборке и теряют GRANT, поэтому гранты
--          выдаются в последнем файле бандла; GRANT идемпотентен

-- app_ro: только чтение mart (core, raw, landing, ops недоступны)
GRANT USAGE ON SCHEMA mart TO app_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA mart TO app_ro;

-- ingestor: запись событий в landing и применение их в core
GRANT USAGE, CREATE ON SCHEMA landing TO ingestor;
GRANT ALL ON ALL TABLES IN SCHEMA landing TO ingestor;
GRANT ALL ON ALL SEQUENCES IN SCHEMA landing TO ingestor;

GRANT USAGE ON SCHEMA core TO ingestor;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA core TO ingestor;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA core TO ingestor;

-- ingestor: статус потока и параметры сборки
-- SELECT на stream_status нужен для UPDATE ... WHERE id = 1
GRANT USAGE ON SCHEMA ops TO ingestor;
GRANT SELECT, UPDATE ON ops.stream_status TO ingestor;
GRANT SELECT ON ops.build_params TO ingestor;
-- <<< sql/90_grants/900_grants.sql

-- >>> sql/90_grants/910_grants_batch.sql
-- object : гранты ingestor на ops.stream_pause
-- grain  : -
-- source : -
-- cc     : K3 §3.3, K0 §4.4
-- why    : протокол паузы: ingestor делает SELECT ... FOR SHARE, а FOR SHARE требует права UPDATE;
--          гранты в конце бандла, чтобы пережить пересоздание схем (900_grants.sql не меняется)

GRANT SELECT, UPDATE ON ops.stream_pause TO ingestor;
-- <<< sql/90_grants/910_grants_batch.sql

-- >>> sql/90_grants/920_grants_stream.sql
-- object : гранты ingestor на ops.replay_runs
-- grain  : -
-- source : -
-- cc     : K2 §6 п.3, ASSUMPTION-K2-1 (пробел K0)
-- why    : ingestor пишет итоги реплея и отмечает догон; 900_grants.sql не меняем, гранты потока — здесь

GRANT SELECT, INSERT, UPDATE ON ops.replay_runs TO ingestor;
-- <<< sql/90_grants/920_grants_stream.sql

COMMIT;
