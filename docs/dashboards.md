# Дашборды: выбор BI и концепция (DL-4)

Это блок «Фронт» из `architecture.md`. Контракт с аналитикой — К5. Дашборды читают **только** `mart.*` под ролью `analyst` (только чтение).

## 1. Выбор инструмента

| Инструмент | PG16 | macOS | Лицензия, цена | docker-compose | as-code / git | Скорость за хакатон | На защите | Неаддитивные по срезам |
|---|---|---|---|---|---|---|---|---|
| Power BI | ✔ | ✘ Desktop только Windows | Pro для публикации | ✘ | ~ (PBIP/TMDL) | ~ | ✔ | ✔ DAX-меры |
| Apache Superset | ✔ | ✔ через docker | Apache-2.0 | ~ тяжёлый | ~ YAML export | ~ 2–3 ч | ✔ | ✔ SQL-метрики датасета |
| Metabase | ✔ | ✔ | AGPL OSS | ✔ один контейнер | ✘ (только платно) | ✔ GUI | ✔ | ✔ на атомарной грануле |
| **Grafana OSS** | ✔ | ✔ | AGPL, бесплатно | ✔ лёгкий | ✔ provisioning YAML + JSON | ✔ панель = SQL | ~ «ops-вид» | ✔ SQL на панель |
| Yandex DataLens | ✔ | ✔ | бесплатно | ~ OSS тяжёлый | ✘ | ~ облаку нужен публичный PG | ✔ | ✔ |
| Tableau / Public | ~ Public без PG | ✔ | Desktop платный | ✘ | ~ .twb XML | ~ | ✔ | ✔ LOD |
| Looker Studio | ~ PG из интернета | ✔ | бесплатно | ✘ | ✘ | ~ | ~ | ~ |
| **Streamlit** / Plotly Dash | ✔ psycopg2 | ✔ | Apache/MIT | ✔ | ✔ код | ~ график = код | ~ | ✔ считаем в SQL |
| Evidence.dev | ✔ | ✔ (Node.js) | MIT | ✔ | ✔ MD + SQL | ✔ | ✔ | ✔ SQL на блок |

**DECISION-10 (BI).** Рекомендация: **основной — Grafana OSS**, **запасной — Streamlit**.
- Grafana поднимается из git одной командой (`make bi`) с готовыми datasource и дашбордами — тот же принцип «с нуля», что у модели. Лёгкий образ, macOS через docker, без лицензий, anonymous Viewer без паролей.
- Неаддитивные: панель = свой SQL к mart, фильтры идут в `WHERE`, поэтому `COUNT(DISTINCT)`, средние и доли пересчитываются на срезе.
- Минусы: «ops-вид», нет ad-hoc drill-down. Запасной Streamlit (`dashboards/streamlit/app.py`) — если не вытянем когорты или мешает docker.
- Superset — если есть опыт (сильнее как BI, дольше подъём). Metabase быстрее всех, но в OSS не воспроизводим из git. Power BI отпадает: macOS.
- ASSUMPTION-9: образ `grafana/grafana-oss:11.x` (пин в W6d), плагин PostgreSQL встроен.

Развёртывание без правки compose кейса: `docker-compose.bi.yml` (сервис `grafana`, `profiles: [tools]`, порт 3000, сеть общая с `postgres`); `make bi` = `docker compose -f docker-compose.yml -f docker-compose.bi.yml --profile tools up -d grafana`.

## 2. Концепция: 3 дашборда

Почему три: данные надёжно покрывают продажи, сроки (5 дат + shipping_limit) и покупателей. Отзывы — следствие доставки, поэтому блок в D2; платежи — вкладка D1. Общие фильтры: период по `purchase_month`, штат покупателя, штат продавца, категория. По умолчанию выручка = delivered (FR-30), переключатель «определение выручки» показывает формулу из `metric_catalog`.

**НА** — неаддитивный: на каждом срезе считается SQL заново, итог — отдельным запросом, не суммой строк.

### D1. Продажи и выручка
- **Зачем:** куда растёт GMV и за счёт чего. Решения: какие категории продвигать, каких продавцов развивать, где выручка концентрируется.
- **Пользователь:** коммерческий директор, категорийные менеджеры. **Обновление:** ежедневно (в baseline — после `make model`).

| Показатель | Формула | Гранула | Источник | Вид | НА |
|---|---|---|---|---|---|
| Выручка | Σ price, is_revenue | позиция | v_sales_item | stat + тренд по месяцам | нет |
| Заказы | COUNT(DISTINCT order_id), is_revenue | заказ | v_order | stat, столбцы | **да** при срезе по продавцу/категории (заказ с 2+ продавцами) |
| Средний чек | AVG(items_price_sum + items_freight_sum) | заказ | v_order | stat | **да** |
| Единицы | COUNT(*) | позиция | v_sales_item | stat | нет |
| Доля категории | Σ revenue по категории / Σ revenue всего | позиция | v_sales_item | bar-gauge топ-15 | **да** (доли не суммируются при других фильтрах) |
| Топ-10 продавцов | Σ price, заказы, единицы | позиция | v_sales_item | таблица | заказы — **да** |
| Выручка по штату продавца / покупателя | Σ price | позиция | v_sales_item | таблица / geomap по штатам | нет |
| Структура оплат (вкладка) | Σ payment_value, доля типа | платёж | v_payment | pie, таблица | доля — **да** |
| GMV с доставкой (справочно) | Σ gross_value | позиция | v_sales_item | stat | нет |

```
[фильтры: период | штат покупателя | штат продавца | категория]
[Выручка][Заказы][Средний чек][Единицы][% к пред. периоду]
[Тренд: выручка (столбцы) + заказы (линия) по месяцам — 2/3][Доля категорий топ-15 — 1/3]
[Топ-10 продавцов: город, штат, заказы, единицы, выручка][Выручка по штатам]
[вкладка: способы оплаты, рассрочка]
```

### D2. Доставка, SLA продавцов и отзывы
- **Зачем:** обещание срока — главный драйвер оценки. Решения: каким продавцам грозят санкции или нужно обучение за просрочку отгрузки, где пересчитать обещанную дату по штатам, какие маршруты (штат продавца → штат покупателя) проблемные.
- **Пользователь:** руководитель логистики, менеджер по работе с продавцами. **Обновление:** ежедневно.

| Показатель | Формула | Гранула | Источник | Вид | НА |
|---|---|---|---|---|---|
| Доля в срок | AVG(is_on_time) по заказам с валидными датами | заказ | v_delivery | stat + тренд | **да** |
| Срок доставки | AVG и p50/p90 (delivered_customer − purchase), дни | заказ | v_delivery | stat, box/histogram | **да** |
| Опоздание | AVG(delay_days) where is_late | заказ | v_delivery | stat | **да** |
| Просрочка отгрузки | AVG(is_shipped_late): carrier > shipping_limit | позиция × продавец | v_delivery_item | таблица продавцов, порог ≥ 20 позиций | **да** |
| Срок по маршруту | AVG delivery_days | заказ | v_delivery | heatmap штат→штат | **да** |
| Средняя оценка | AVG(review_score) актуального отзыва | заказ | v_order | stat, столбцы по бакетам опоздания | **да** |
| Доля 1–2 звёзд | share score ≤ 2 | заказ | v_order | stat | **да** |
| Аномалии дат | COUNT по флагам CC-06/07 | заказ | v_delivery | таблица-«качество данных» | нет |

```
[фильтры: период | штат продавца | штат покупателя | категория]
[В срок %][Срок p50][Срок p90][Опоздание, дн][Ср. оценка][1–2★ %]
[Тренд «в срок %» и оценки по месяцам][Оценка × бакет опоздания (0, 1–3, 4–7, 8+ дн)]
[Heatmap маршрутов штат→штат][Продавцы: позиций, % просрочки отгрузки, ср. оценка]
[Плашка: исключено N заказов с невалидными датами (CC-06/07)]
```

### D3. Покупатели и удержание
- **Зачем:** повторных покупок 3.12 %, то есть рост держится на привлечении. Решения: бюджет на удержание или привлечение, в каких штатах и категориях запускать повторные кампании.
- **Пользователь:** директор по маркетингу, CRM. **Обновление:** еженедельно.

| Показатель | Формула | Гранула | Источник | Вид | НА |
|---|---|---|---|---|---|
| Покупатели | COUNT(DISTINCT customer_unique_id) | покупатель | v_customer | stat | **да** (по месяцам не суммируется) |
| Вернувшиеся, % | покупатели с orders_count ≥ 2 / все | покупатель | v_customer | stat | **да** |
| Новые и повторные по месяцам | COUNT DISTINCT по is_first_order | заказ | v_order | stacked bars | **да** |
| Когортное удержание | active(cohort, offset) / cohort_size | когорта × месяц | v_cohort_retention | heatmap-таблица | **да** |
| Выручка на покупателя | Σ revenue / COUNT DISTINCT покупателей | покупатель | v_customer | stat | **да** |
| Покупатели по штатам | COUNT DISTINCT | покупатель | v_customer | geomap / таблица | **да** между штатами при переезде (252 человека) |

```
[фильтры: когорта (месяц 1-го заказа) | штат | категория 1-го заказа]
[Покупатели][Вернувшиеся %][Выручка на покупателя][Заказов на покупателя]
[Новые vs повторные по месяцам — 2/3][Покупатели по штатам — 1/3]
[Когортная таблица удержания: строки — когорты, колонки — месяц 0..12]
```

**Ограничения данных** (плашка на дашборде): края периода (2016-09..12, 2018-09/10) вырождены, тренды с 2017-01; строка = 1 единица; 768 заказов без отзыва; 290 одновременных заказов = повтор (CC-16); нет маржи и затрат; снимок без инкремента.

## 3. Контракт Аналитика → Фронт (К5)

Все views создаются в W6 (T19). Дашборды собираются без доработок модели.

| View | Гранула / ключ | Колонки | Питает |
|---|---|---|---|
| `mart.v_sales_item` | позиция / (order_id, order_item_id) | purchase_ts, purchase_month, delivered_month, status_code, is_revenue, seller_id, seller_city, seller_state, product_id, category_name_pt, category_name_en, customer_unique_id, customer_state, price, freight_value, gross_value, revenue | D1 |
| `mart.v_order` | заказ / order_id | customer_unique_id, customer_state, purchase_month, status_code, is_revenue, is_canceled, items_count, items_price_sum, items_freight_sum, order_value, payments_sum, seller_count, review_score, has_review, customer_order_seq, is_first_order | D1, D2, D3 |
| `mart.v_payment` | платёж / (order_id, payment_sequential) | purchase_month, payment_type_code, installments, payment_value, is_revenue | D1 (вкладка) |
| `mart.v_delivery` | заказ (delivered) / order_id | purchase_month, customer_state, seller_state_main, delivery_days, promised_days, delay_days, is_on_time, is_late, has_valid_dates, review_score, флаги CC-06/07 | D2 |
| `mart.v_delivery_item` | позиция / (order_id, order_item_id) | seller_id, seller_state, shipping_limit_ts, delivered_carrier_ts, is_shipped_late, ship_delay_days | D2 |
| `mart.v_customer` | покупатель / customer_unique_id | first_order_month, first_category, last_state, orders_count, delivered_orders, revenue_total, is_repeat | D3 |
| `mart.v_cohort_retention` | когорта × offset / (cohort_month, month_offset) | cohort_size, active_customers, retention_rate | D3 |
| `mart.metric_catalog` | метрика / metric_code | name, formula_sql, grain, source_view, additivity (additive / semi / non), note | все: подписи и плашки НА |

Правило К5: в панелях нет `JOIN` фактов разной гранулы, нужная гранула уже есть в view.

## 4. Как код (папки)

```
docker-compose.bi.yml                      сервис grafana, profile tools, anonymous Viewer
dashboards/grafana/provisioning/datasources/pg.yml      PG → роль analyst, из .env
dashboards/grafana/provisioning/dashboards/provider.yml
dashboards/grafana/json/d1_sales.json  d2_delivery.json  d3_customers.json
dashboards/streamlit/app.py                запасной вариант (DECISION-10)
tests/test_dashboards.py                   каждый rawSql из JSON выполняется; KPI D1 = golden Q-1
```

**Волна W6d** (опциональная, ⇄ W7) — в `architecture.md` §f. Checkpoint: `make bi` → http://localhost:3000, 3 дашборда без логина; KPI «Выручка» = 13 221 498.11; `test_dashboards.py` зелёный.
