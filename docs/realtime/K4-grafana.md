# K4. Grafana для бизнес-аналитиков
*Спецификация v1, 2026-10-28. Опирается на: `dashboards.md`, `realtime-plan.md` §7.1, `K0-contracts.md` §2–4. Предположения: `ASSUMPTION`.*

## 1. Цель и границы
Одна команда поднимает Grafana с datasource под `app_ro` и дашбордами D1–D4 из git. K4 трогает только `dashboards/grafana/`, `docker-compose.bi.yml`, `make/bi.mk` (`make bi`), `sql/60_mart/67x_*`. НЕ входит: geomap (нет карты штатов Бразилии, вместо неё bar), PDF-рассылка (нет в OSS, роль Airflow/K3), внешние каналы алертов, правка `Makefile` (строку `-include make/*.mk` добавляет оркестратор), аудит.

## 2. Что делаем
**Сервис.** `docker-compose.bi.yml`: `grafana`, `profiles: [bi]`, :3000, сеть `postgres`. Запуск: `docker compose -f docker-compose.yml -f docker-compose.bi.yml --profile bi up -d grafana` (в `make/bi.mk` — цель `bi`, тот же запуск). Образ `grafana/grafana-oss:11.6.0` (ASSUMPTION: Context7 недоступен, тег и формат provisioning сверить). Anonymous Viewer.
**Provisioning** (`dashboards/grafana/`): `provisioning/datasources/pg.yml` (uid `capibara-pg`, `postgres:5432`, БД `marketplace`, user `app_ro`, пароль `${GRAFANA_PG_PASSWORD:-app_ro}`); `provisioning/dashboards/provider.yml` (папка `Capibara`); `provisioning/alerting/alerts.yml`; `json/d1_sales.json`, `d2_delivery.json`, `d3_customers.json`, `d4_pipeline.json`.
**Правила панелей.**
1. Только `mart.*`, один view на панель, без JOIN фактов. Период: `purchase_month >= date_trunc('month',$__timeFrom()) AND purchase_month <= $__timeTo()`, по умолчанию `2016-09-01 … 2018-11-01`.
2. Переменные `customer_state`, `seller_state`, `category` (multi, All = `'*'`, фильтр `('*' IN ($v) OR col IN ($v))`, чтобы NULL не терялись), `gran` (week/month/quarter).
3. Неаддитивное (заказы, ср. чек, доли, p50/p90, покупатели, удержание) считается в SQL на срезе, итог отдельным запросом. Запрещены transformations `reduce, calculateField, groupBy, merge`.
4. Формулы дословно из `metric_catalog.formula_sql`; на каждом дашборде table «Определения».
5. `refresh`: D4 `5s`, D1–D3 `1m` (`statement_timeout` 5 с). CSV: Inspect → Data.

**D1 Продажи** (`v_sales_item`; период, оба штата, категория, gran): stat Выручка `SUM(price) FILTER (WHERE is_revenue)`, Единицы, GMV с доставкой; stat Заказы и Ср. чек из `order_summary` (без среза по продавцу/категории, ASSUMPTION, пометка в title); timeseries выручка+заказы по `date_trunc($gran, purchase_ts)`; bargauge топ-15 категорий, доля `SUM(price)/SUM(SUM(price)) OVER ()`; table топ-10 продавцов (заказы `COUNT(DISTINCT order_id)`); bar по штатам; pie+table оплаты (`v_payment`). Готовые `v_seller_sales`, `v_category_sales` не используются: они без фильтров периода и штата.
**D2 Доставка** (`v_delivery`, `v_delivery_item`): stat в срок %, p50, p90, опоздание, ср. оценка, 1–2★ %; timeseries по месяцам; bar оценка × `late_bucket`; table-матрица маршрутов (`groupingToMatrix`, ≥30 заказов); table продавцов (`HAVING COUNT(*) >= 20`, % `is_shipped_late`); stat «исключено N» (`NOT has_valid_dates`). Срез по продавцу/категории — по `seller_state_main`/`category_main`.
**D3 Покупатели** (`v_customer`, `v_order_seq`, `v_cohort_retention`; период = месяц 1-го заказа, штат, `first_category`): stat Покупатели, Вернувшиеся %, Выручка и Заказов на покупателя; stacked bar новые (`COUNT(*) FILTER (WHERE is_first_order)`) / повторные (`COUNT(DISTINCT customer_unique_id) FILTER (WHERE NOT is_first_order)`); bar по штатам; матрица когорт 0..12 из `SUM(active_customers)/SUM(cohort_size)`, не AVG от `retention_rate`; плашка ограничений данных (252 переехавших).
**D4 Pipeline** (без переменных): stat `lag_sec, lag_events, events_per_sec, dlq_count, last_event_ts`; timeseries `v_stream_throughput`; table 20 последних `etl_runs`; table `dq_result` (красным `passed=false`); table `reconcile_result` последнего `run_id`; `build_params.cutoff`; alert list.
**Алерты** (группа `capibara`, 1m, только UI): (1) есть `NOT passed` в `dq_result`; (2) `stream_status.lag_sec > 60` for 1m; (3) `NOT is_ok` в `reconcile_result` последнего `run_id`; (4) `late_pct` последнего месяца с ≥100 доставленных (`v_delivery`) > 15 % (порог ASSUMPTION, на полной сборке не срабатывает).

## 3. Зависимость от K0
Роль `app_ro` (SELECT на `mart`, `statement_timeout=5s`, пароль = имя роли); `mart.etl_runs, stream_status, reconcile_result, build_params` (§4.3; `reconcile_result.batch_value/stream_value` nullable — панели D4 это учитывают); `mart.dq_result(check_id, description, expected, actual, passed, checked_at)` (`sql/80_dq/800_dq_framework.sql`); `metric_catalog`, `dimension_catalog` (§4.6); `v_sales_item` (`purchase_ts, purchase_month, is_revenue, seller_state, customer_state, category_label, price, freight_value`); `order_summary` (время — `purchased_at`, не `purchase_ts`; `purchase_month, customer_state, customer_unique_id, is_revenue, goods_value, order_value, delivery_days, delay_days, is_valid_delivery, review_score_mean`); `v_kpi`; `v_delivery_review` (агрегат по группам опоздания, без фильтров); `900_grants.sql` (`SELECT ON ALL TABLES IN SCHEMA mart`) покрывает новые `mart.v_*`, отдельный `sql/90_grants/930_*` K4 не нужен (если понадобится — только этот номер).
Зависимость от K2: `mart.v_sales_month`, `order_summary`, `v_seller_sales`, `v_category_sales` (600–620) становятся обычными `VIEW` (факт K2 §6) — запросы D1–D3 идут к ним без `REFRESH`, данные потока видны сразу. Если панель >5 с — запасной `ops.refresh_marts()`, решение пользователя. Источник D4 `v_stream_throughput` — `landing.events` (K0).

## 4. Недостающие витрины (владелец K4; `VIEW`, LEFT JOIN)
Колонки `core` (проверено): `fact_order(purchased_at, approved_at, delivered_carrier_at, delivered_customer_at, estimated_delivery_at)`, `fact_order_item(shipping_limit_at, price, freight_value, seller_id, product_id)`, `fact_order_payment(payment_sequential, payment_type, payment_installments, payment_value)`. Витрины, где возможно, строятся поверх `mart.order_summary` (там уже есть `purchase_month`, `customer_state`, `customer_unique_id`, `is_revenue`, `delivery_days`, `delay_days`, `is_valid_delivery`, `review_score_mean`), а не пересчитывают их из `core`; `core` — только для продавца, категории, платежей и `delivered_carrier_at`/`shipping_limit_at`.
| Файл | View, гранула | Колонки |
|---|---|---|
| `670_v_payment.sql` | `v_payment`, платёж | `order_id, payment_sequential, purchase_month, customer_state, payment_type, installments (= payment_installments), payment_value, is_revenue` |
| `671_v_delivery.sql` | `v_delivery`, delivered-заказ (из `order_summary`) | `order_id, purchase_month, customer_state, seller_state_main, category_main, delivery_days, delay_days, is_on_time, is_late, has_valid_dates (= is_valid_delivery), review_score_mean, late_bucket` (on_time/1-3/4-7/8+; границы `delay_days` ≤0/≤3/≤7/>7 как у `v_delivery_review`, сверка: Σ по `late_bucket` при полном периоде = `v_delivery_review.orders`, `AVG` оценки = `mean_score`); `delivery_days`, `delay_days`, `review_score_mean` берутся из `order_summary`, не пересчитываются; флаги NULL при невалидных датах |
| `672_v_delivery_item.sql` | `v_delivery_item`, позиция | `order_id, order_item_id, purchase_month, seller_id, seller_state, customer_state, is_shipped_late, ship_delay_days, review_score_mean` (`is_shipped_late`: `delivered_carrier_at > shipping_limit_at`; `ship_delay_days` — их разница в днях) |
| `673_v_customer.sql` | `v_customer`, покупатель (из `order_summary`) | `customer_unique_id, first_order_month, first_category, last_state, orders_count` (все статусы, как `customers` в `v_kpi`), `delivered_orders, revenue_total (Σ goods_value по is_revenue), is_repeat` |
| `674_v_cohort.sql` | `v_order_seq`, заказ; `v_cohort_retention`, когорта×offset×штат×категория | seq: `order_id, customer_unique_id, customer_state, purchase_month, first_category, customer_order_seq, is_first_order`; cohort: `cohort_month, month_offset 0..24, first_state, first_category, cohort_size` (на каждом offset), `active_customers, retention_rate` |
| `675_v_stream_throughput.sql` | `v_stream_throughput`, минута за 60 мин | `minute (date_trunc('minute', received_at), UTC), events (COUNT(*)), applied (status='applied'), errors (status='error')` из `landing.events` |
Дубли отсутствуют: `v_sales_item`, `order_summary`, `v_kpi`, `v_delivery_review`, `v_seller_sales`, `v_category_sales`, `v_sales_month` — агрегаты без нужных срезов/гранулы (платёж, покупатель, когорта, минута потока) либо без фильтров; `v_delivery` и `v_customer` лишь надстраиваются над `order_summary`.

## 5. Критерии готовности (не TDD)
- A-1 Compose up: `/api/health` ok ≤60 с, :3000 без логина.
- A-2 Datasource `capibara-pg` health ok, `current_user` = `app_ro`.
- A-3 4 дашборда в папке `Capibara`; после рестарта и `make reset` на месте.
- A-4 Каждый `rawSql` (переменные по умолчанию) выполняется через `/api/ds/query` без ошибки (пусто допустимо только на D4).
- A-5 D1 «Выручка» = 13 221 498.11 при полной сборке.
- A-6 Покупатели 96 096; Вернувшиеся 3.12 %; Ср. чек 159.88; «В срок» и медиана срока = `v_kpi`.
- A-7 `customer_state=SP` → выручка = ручной `SUM` по `v_sales_item`, меньше итога; All включает NULL-штаты.
- A-8 Нет запрещённых transformations; stat-метрики каталога = выполнение их `formula_sql`.
- A-9 `refresh`: D4 5s, D1–D3 1m.
- A-10 4 правила загружены, health не `error`; при `lag_sec=120` правило лага уходит в Pending/Alerting ≤2 интервала.
- A-11 CSV выгружается с table/stat панели под Viewer.
- A-12 Новые views: ключ гранулы уникален, `app_ro` читает; `make ci` зелёный, Q1–Q5 без изменений.

## 6. НФТ и MVP-срез
Схема БД — только `67x_*`; панель ≤5 с. Must: A-1..A-8, A-12. Should: алерты, CSV, `make bi` (`make/bi.mk`). Later: внешний канал, geomap.

## 7. План реализации
| № | Задача | Файлы | Образец | Исполнитель | Волна |
|---|---|---|---|---|---|
| T1 | Compose, datasource, provider, make | `docker-compose.bi.yml`, `provisioning/datasources/pg.yml`, `provisioning/dashboards/provider.yml`, `make/bi.mk` | pgadmin в `docker-compose.yml` | devops, standard (доступ к БД) | 1 |
| T2 | `v_payment`, `v_delivery`, `v_delivery_item` | `670`, `671`, `672` | `610_order_summary.sql` | python-developer, standard | 1 |
| T3 | `v_customer`, `v_order_seq`, `v_cohort_retention` | `673`, `674` | `640_v_kpi.sql` | python-developer, standard | 1 |
| T4 | `v_stream_throughput` | `675` | `660_ops_views.sql` | python-developer-lite | 1 |
| T5 | D1 | `json/d1_sales.json` | — | python-developer, standard | 2 |
| T6 | D2 | `json/d2_delivery.json` | T5 | python-developer, standard | 2 |
| T7 | D3 | `json/d3_customers.json` | T5 | python-developer, standard | 2 |
| T8 | D4 + алерты | `json/d4_pipeline.json`, `provisioning/alerting/alerts.yml` | — | devops, standard | 2 |
| T9 | Прогон A-1..A-12, правки | зона K4 | — | devops, standard | 3 |
Файлы волны не пересекаются; K1/K2/K3 вне зоны K4; `Makefile` правит только оркестратор (`-include make/*.mk`). Коммиты: сообщение без строки `Co-Authored-By` и без упоминаний Claude/ИИ.
