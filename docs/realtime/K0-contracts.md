# K0. Контракты real-time
*Спецификация v1, 2026-10-28. Опирается на: `docs/realtime-plan.md` (§1.1, 4, 5, 6, 8), `docs/dashboards.md` §3, `CLAUDE.md`. Предположения: `ASSUMPTION`.*

## 1. Цель и границы
Зафиксировать контракты, от которых параллельно стартуют K1 API, K2 поток, K3 ночная сборка, K4 Grafana: схемы, DDL, каталоги, адаптер LLM. НЕ входит: ingestor, генератор, upsert в core, фильтрация по cutoff (K3), эндпоинты и pydantic-модели (K1), агент (K6).

## 2. Правила коммитов и чистоты (для исполнителей)
Репозиторий отдаётся организаторам.
1. Один коммит = одна законченная задача T*. Сообщение по-русски, conventional commits: `feat(K0-T2): таблица landing.events`, `fix(…)`, `docs(…)`. Без «wip», «fix typo 2», «test» и серий промежуточных фиксов: правки до коммита, затем повторный прогон.
2. В коммит только файлы своей задачи (`git add <путь>`, не `-A`/`.`). Нельзя коммитить: `.env` и ключи, `data/`, `output/`, `__pycache__`, `.DS_Store`, `.idea`, временные и отладочные скрипты, scratch-файлы, логи, дампы.
3. Без закомментированного кода и print-отладки. У каждого SQL-файла шапка `object/grain/source/cc/why` по `CLAUDE.md`.
4. Новые зависимости — только с пином версии в `requirements.txt`.
5. Без `push` и без переписывания истории (чистка истории — отдельно в конце).

## 3. Ключевые решения по БД
1. `000_schemas.sql` на каждой сборке делает `DROP SCHEMA stg/core/mart CASCADE`. Что должно пережить сборку (журнал, учёт запусков, параметры), живёт в схемах **`landing`** и **`ops`**: `IF NOT EXISTS`, не дропаются.
2. Имена `mart.etl_runs / stream_status / reconcile_result / build_params` — тонкие `VIEW` над `ops.*`. Сервисы пишут в `ops.*`, API/Grafana читают `mart.*` под `app_ro`.
3. `GRANT` теряются при пересоздании схем, поэтому все гранты — в последнем файле бандла. Порядок (сортировка путей): `00_setup` → `05_landing` → `10_seed` … → `90_grants`.

## 4. Контракты

### 4.1 События `orders.events` (`contracts/events/*.json`, JSON Schema 2020-12)
Файлы: `envelope.json`, `order.created.json`, `payment.captured.json`, `order.status_changed.json`, `review.posted.json`, `replay.completed.json`, `dlq.json`; `additionalProperties: false`.
Топик `orders.events`, 3 партиции, **ключ = `order_id`** (у `replay.completed` — `replay`). Глобального порядка нет: `replay.completed` несёт ожидаемые числа, сверка идёт «когда догнали».

Конверт (всё обязательно): `event_id` uuid — детерминированный uuid5 от `type:order_id:дискриминатор` (created — пусто; payment — `payment_sequential`; status_changed — новый статус; review — `review_id`), повтор реплея даёт тот же id; `type` ∈ 5 типов; `order_id` `^[0-9a-f]{32}$` (у `replay.completed` `null`); `event_ts` `YYYY-MM-DDTHH:MM:SS` naive (бизнес-время); `produced_at` UTC, оканчивается `Z`; `schema_version` const 1; `payload` по `type` (`if/then`). Деньги — строки `^-?\d+\.\d{2}$`. Статусы — из `core.dim_order_status` (в `status_changed` без `created`).

| type | payload |
|---|---|
| order.created | `order{order_id, customer_id, order_status, purchased_at, estimated_delivery_at?}`, `customer{customer_id, customer_unique_id, zip_prefix, city, state}`, `items[{order_item_id≥1, product_id, seller_id, shipping_limit_at?, price, freight_value}]` (minItems 0: 775 заказов без позиций) |
| payment.captured | `payment_sequential≥1, payment_type, payment_installments≥0, payment_value` |
| order.status_changed | `order_status`, `approved_at?`, `delivered_carrier_at?`, `delivered_customer_at?` |
| review.posted | `review_id, review_score 1..5, review_comment_title?, review_comment_message?, review_created_at, review_answered_at?` |
| replay.completed | `replay_id, cutoff (date\|null), events_total, orders_total, expected{orders_total, revenue, avg_check, customers, repeat_pct}`; для полного датасета 99441, "13221498.11", "159.88", 96096, "3.12" |

DLQ (`orders.dlq`, ключ = исходный): `{failed_at, reason_code ∈ invalid_json|schema_violation|unknown_type|unsupported_version|apply_error, reason_detail, source{topic, partition, offset}, event_id (nullable), original (string — исходное тело)}`.

### 4.2 `landing.events` (`sql/05_landing/050_landing_events.sql`)
`event_id uuid PK`, `topic text`, `partition int`, `kafka_offset bigint`, `order_id text NULL`, `type text NOT NULL CHECK (5 типов)`, `schema_version smallint`, `payload jsonb NOT NULL`, `event_ts timestamp NOT NULL`, `produced_at timestamp`, `received_at timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'utc')`, `status text NOT NULL DEFAULT 'received' CHECK (received|applied|skipped_stale|error)`, `error text`. Индексы: `(order_id, event_ts)`, `(event_ts)`, частичный `(received_at) WHERE status <> 'applied'`. (`kafka_offset`: `offset` зарезервировано.)

### 4.3 Служебные таблицы (`sql/05_landing/055_ops_tables.sql`, `IF NOT EXISTS`)
- `ops.build_params`: `id smallint PK CHECK (id=1)`, `cutoff date NULL`, `updated_at timestamp`; сид `(1, NULL)` `ON CONFLICT DO NOTHING`.
- `ops.etl_runs`: `run_id bigint identity PK`, `ds date NOT NULL`, `kind CHECK (batch|stream|demo)`, `status CHECK (running|success|failed|blocked|published)`, `started_at timestamp NOT NULL`, `finished_at`, `dq_passed smallint`, `dq_total smallint`, `reconcile_diff numeric(14,2)`, `cutoff date`, `note text`.
- `ops.stream_status`: одна строка (`id=1 CHECK`): `last_event_ts timestamp`, `events_total bigint`, `events_per_sec numeric(10,2)`, `lag_events bigint`, `lag_sec numeric(10,2)`, `dlq_count bigint`, `updated_at timestamp`; сид нулями.
- `ops.reconcile_result`: `id identity PK`, `run_id` FK `ops.etl_runs`, `ds date`, `day date NULL`, `check_code` (orders_count|revenue_sum|payments_sum), `batch_value`, `stream_value numeric(18,2)`, `diff numeric(18,2)` = batch−stream (generated), `is_ok boolean NOT NULL`, `checked_at timestamp`.
- `sql/60_mart/660_ops_views.sql`: четыре `mart.*` = `SELECT * FROM ops.*`.

### 4.4 Роли (`sql/00_setup/001_roles.sql`, `002_persistent_schemas.sql`, `sql/90_grants/900_grants.sql`)
Создание: `DO $$ … IF NOT EXISTS (SELECT FROM pg_roles …) THEN CREATE ROLE … $$`. Пользователь `hack` не меняется.
- `app_ro` LOGIN: `USAGE` на `mart`, `SELECT` на всё в `mart`; `ALTER ROLE … SET statement_timeout='5s'`, `default_transaction_read_only=on`. Доступа к `core/raw/landing/ops` нет.
- `ingestor` LOGIN: `ALL` на `landing`; `SELECT/INSERT/UPDATE` на таблицы `core`; `UPDATE` на `ops.stream_status`, `SELECT` на `ops.build_params`.
- `ASSUMPTION-K0-1`: роль `etl` из плана = `hack`; пароли демо = имя роли (локально).

### 4.5 Параметр cutoff
Контракт: `ops.build_params.cutoff` (`NULL` = полная сборка, цифры не меняются); сборка читает `(SELECT cutoff FROM ops.build_params WHERE id=1)`. Фильтр делает K3: `sql/20_staging/200_stg_orders.sql` — `WHERE cutoff IS NULL OR purchased_at < cutoff`; `210_stg_order_items`, `220_stg_order_payments`, `230_stg_order_reviews` — только заказы из `stg.orders`. Справочники (`240–270`, `stg.customers`) — целиком. K3 также правит эталонные DQ при `cutoff IS NOT NULL`. В K0 фильтров нет.

### 4.6 Каталоги (`sql/60_mart`)
`605_v_sales_item.sql`: обычный `VIEW mart.v_sales_item` (гранула позиции, `dashboards.md` §3; колонки: `order_id, order_item_id, purchase_ts, purchase_month, order_status, is_revenue, seller_id, seller_state, category_key, category_label, customer_unique_id, customer_state, price, freight_value`; только LEFT JOIN).

`655_dimension_catalog.sql`: `mart.dimension_catalog(dim_code PK, name, column_name, dim_type CHECK (categorical|time), source_views text[])`. Коды: `month`→`purchase_month`, `customer_state`, `order_status` (оба источника); `seller_state`, `seller_id`, `category`→`category_label` (только I). O=`mart.order_summary`, I=`mart.v_sales_item`.

`650_metric_catalog.sql`: `mart.metric_catalog(metric_code PK, name, description, formula_sql, source_view, grain, additivity CHECK (additive|semi|non), is_additive boolean GENERATED (additivity='additive'), unit CHECK (BRL|count|pct|days|score), allowed_dims text[] NOT NULL, note)`. `formula_sql` — агрегат над `source_view`, фильтры внутри `FILTER (WHERE …)`.

| metric_code | formula_sql | unit | add. | src / dims |
|---|---|---|---|---|
| revenue | `SUM(price) FILTER (WHERE is_revenue)` | BRL | additive | I, все 6 |
| units_sold | `COUNT(*) FILTER (WHERE is_revenue)` | count | additive | I, все 6 |
| freight_total | `SUM(freight_value) FILTER (WHERE is_revenue)` | BRL | additive | I, все 6 |
| sellers_active | `COUNT(DISTINCT seller_id) FILTER (WHERE is_revenue)` | count | non | I, все 6 |
| orders_total | `COUNT(*)` | count | additive | O: month, customer_state, order_status |
| orders_delivered | `COUNT(*) FILTER (WHERE is_revenue)` | count | additive | O |
| orders_canceled | `COUNT(*) FILTER (WHERE order_status='canceled')` | count | additive | O |
| cancel_rate_pct | `ROUND(100.0*COUNT(*) FILTER (WHERE order_status='canceled')/NULLIF(COUNT(*),0),2)` | pct | non | O |
| gmv_with_freight | `SUM(order_value) FILTER (WHERE is_revenue)` | BRL | additive | O |
| avg_check | `ROUND(SUM(order_value) FILTER (WHERE is_revenue)/NULLIF(COUNT(*) FILTER (WHERE is_revenue),0),2)` | BRL | non | O |
| avg_items_per_order | `ROUND(AVG(line_count) FILTER (WHERE is_revenue),2)` | count | non | O |
| payments_total | `SUM(payment_value) FILTER (WHERE is_revenue)` | BRL | additive | O |
| payment_mismatch_orders | `COUNT(*) FILTER (WHERE reconciliation='Расхождение')` | count | additive | O |
| customers | `COUNT(DISTINCT customer_unique_id)` | count | non | O |
| late_pct | `ROUND(100.0*COUNT(*) FILTER (WHERE is_valid_delivery AND delay_days>0)/NULLIF(COUNT(*) FILTER (WHERE is_valid_delivery),0),2)` | pct | non | O |
| avg_delivery_days | `ROUND((AVG(delivery_days) FILTER (WHERE is_valid_delivery))::numeric,1)` | days | non | O |
| median_delivery_days | `ROUND((percentile_cont(0.5) WITHIN GROUP (ORDER BY delivery_days) FILTER (WHERE is_valid_delivery))::numeric,1)` | days | non | O |
| avg_review_score | `ROUND(AVG(review_score_mean),2)` | score | non | O |
| reviewed_orders_pct | `ROUND(100.0*COUNT(*) FILTER (WHERE review_count>0)/NULLIF(COUNT(*),0),2)` | pct | non | O |
| repeat_customers_pct | `MAX(repeat_pct)` | pct | non | `mart.v_kpi`, dims `{}` |

`ASSUMPTION-K0-2`: `dashboards.md` §3 называет `v_order/v_delivery/v_customer`, в репозитории их нет (есть `order_summary`, `v_kpi`, `v_seller_sales`, `v_category_sales`); каталог строится на существующем.

## 5. chart_spec, /api/query, LLM

`contracts/chart_spec.json` (2020-12, `additionalProperties: false`): `type` ∈ bar|line|area|pie|table|map; `metric` (код); `x` (dim_code|null); `series` (dim_code|null, ≠ x); `filters` `{dim_code: [string|number]}` (≤10 значений) плюс `date_from`/`date_to`; `top_n` 1..50; `sort` asc|desc; `title` ≤120. `map` — только `x` ∈ {customer_state, seller_state}; `line/area` — только `x=month`. Допустимость кодов и срезов проверяет сервер по каталогу.

`POST /api/query` (pydantic делает K1): **QueryRequest** `{metric: str, group_by: list[str] ≤2, filters: dict[str, list[str|int]], date_from?: date, date_to?: date, limit: int 1..1000 = 500}`. **QueryResponse** `{metric{code, name, unit, additivity}, columns[{name, role: dim|metric}], rows: list[dict], row_count: int, truncated: bool, explain{formula_sql, source_view, sql, params}}`. Ошибка 422: `{error: unknown_metric|unknown_dim|dim_not_allowed|non_additive_rollup, allowed: list[str]}`.

`app/agent/llm.py`: `LLMSettings` (env: `YANDEX_AI_STUDIO_API_KEY`, `YANDEX_FOLDER_ID`, `LLM_BASE_URL`, `LLM_MODEL`), `build_model_uri(folder_id, model) -> "gpt://{folder}/{model}"`, `get_client(settings) -> OpenAI(api_key, base_url, project=folder_id)`. Ключ не логируется.
`tests/agent/test_llm_smoke.py`: `.env` подхватывается; без ключа или каталога `skip`. Один запрос с одним tool → `tool_calls[0].function.arguments` парсится как JSON. Отдельная проба `reasoning_effort` (и `thinking` через `extra_body`): при 400 — `warnings.warn` и вывод, тест не падает; результат исполнитель сообщает в отчёте.

## 6. Критерии готовности
- A-1 `make reset` с нуля проходит; все DQ = pass; Q1–Q5 без изменений (13 221 498.11 / 226 987.93 / 159.88 / 96 096 и 3.12 % / сумма категорий 13 221 498.11).
- A-2 Повторный `make etl` не теряет строки в `landing.*`, `ops.*`, не падает (роли и DDL идемпотентны).
- A-3 Есть `landing.events`, 4 таблицы `ops.*`, 4 views `mart.*`, `mart.metric_catalog` (20 строк), `mart.dimension_catalog`; `ops.build_params` — одна строка, `cutoff IS NULL`.
- A-4 Каждая `formula_sql` выполняется над своим `source_view`; `revenue`, `orders_total`, `avg_check`, `customers`, `repeat_customers_pct` равны эталонам; каждый `allowed_dims` есть в `dimension_catalog` и применим к `source_view`.
- A-5 `app_ro`: `SELECT` из `mart` работает; из `core`/`landing`, `INSERT` — отказ; `SHOW statement_timeout` = 5s. `ingestor`: `INSERT` в `landing.events` работает. `hack` как прежде.
- A-6 `jsonschema`: все схемы валидны; по одному валидному примеру каждого события, `chart_spec`, DLQ проходят; невалидные (лишнее поле, score=6, float вместо денег, кривой `order_id`) отклоняются. Примеры — `contracts/events/examples/`.
- A-7 Smoke LLM: зелёный с ключом или `skipped` без; `build_model_uri` проверяется без сети.

## 7. НФТ и MVP-срез
Схема меняется только SQL-файлами в `sql/`. Зависимости (`openai`, `jsonschema`, `python-dotenv`) — с пином. Конкурентность: `landing.events` — PK `event_id` (`ON CONFLICT DO NOTHING`); `build_params`/`stream_status` — одна строка по `CHECK (id=1)`.
Must: §4–5, A-1..A-6. Should: A-7 с живым ключом. Later: усиление паролей, `v_order/v_customer/v_cohort_retention`, правка `architecture.md` (DECISION-3), `deepseek-v4-pro`.

## 8. План реализации
Lite-задач нет: роли/гранты, секреты LLM и формулы с эталонами — standard. Правила коммитов — §2.
| № | Задача | Файлы | Образец | Исполнитель | Волна | Почему |
|---|---|---|---|---|---|---|
| T1 | Роли, схемы `landing`/`ops`, `landing.events`, `ops.*`, views, гранты | `sql/00_setup/001_roles.sql`, `002_persistent_schemas.sql`, `sql/05_landing/050_landing_events.sql`, `055_ops_tables.sql`, `sql/60_mart/660_ops_views.sql`, `sql/90_grants/900_grants.sql` | `000_schemas.sql`, `800_dq_framework.sql` | python-developer (standard) | 1 | авторизация, >3 файлов |
| T2 | `v_sales_item`, `dimension_catalog`, `metric_catalog` | `sql/60_mart/605_v_sales_item.sql`, `650_metric_catalog.sql`, `655_dimension_catalog.sql` | `640_v_kpi.sql`, `620_sales_marts.sql` | python-developer (standard) | 1 | формулы сверяются с эталонами |
| T3 | JSON Schema событий, DLQ, `chart_spec`, примеры, проверка | `contracts/events/*.json`, `contracts/events/examples/*.json`, `contracts/chart_spec.json`, `tests/contracts/test_schemas.py` | — | python-developer (standard) | 1 | >3 файлов, контракт 4 потребителей |
| T4 | Адаптер LLM, smoke-тест, зависимости | `app/agent/__init__.py`, `app/agent/llm.py`, `tests/agent/test_llm_smoke.py`, `requirements.txt` | `.env.example` | python-developer (standard) | 1 | секреты |
| T5 | Интеграция: `make bundle`, `make reset`, A-1..A-5, коммит `dist/build_model.sql` | `dist/build_model.sql` | — | python-developer (standard) | 2 | зависит от T1+T2 |

T1–T4 параллельны (файлы не пересекаются); `dist/` коммитит только T5.

## 9. Открытые вопросы
- `ASSUMPTION-K0-1`, `K0-2` — принять (рекомендация).
- `ASSUMPTION-K0-3`: `make build` в Makefile нет, используем `make reset` / `make etl`; алиас не добавлять.
- `ASSUMPTION-K0-4`: 3 партиции и `replay.completed` без гарантии порядка достаточны при сверке «догнали».
- `DEFERRED-K0-R` (ревью K0, решение команды — MVP без внешних пользователей): не чиним строгость JSON Schema (диапазоны дат, деньги ≥ 0, хвостовой `\n`, пустые строки), срезы `order_status` у выручечных метрик, `REVOKE TEMP` для `app_ro`, `GRANT ALL` у `ingestor` на `landing.events`, проверку `is_configured` в `llm.py`. Известные ограничения, озвучиваются на защите.
