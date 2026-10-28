# K1. API
*Спека v1, 2026-10-28. Опирается на: K0-contracts §2, §3, §4.3–4.6, §5; realtime-plan §6–8. Допущения: `ASSUMPTION`.*

## 1. Границы
Read-only слой над `mart.*` для Streamlit, агента (K6) и CSV. Трогает только `app/api/`, `app/main.py` (include_router), `tests/api/`. НЕ входит: `/api/agent`, Streamlit, правки `sql/` (нужна — сообщить оркестратору). `ASSUMPTION K1-1`: без аутентификации, API внутри compose-сети.

## 2. Ручки
Общее: sync-эндпоинты; `app/api/db.py: connect_ro()` под `app_ro` (env `API_PGHOST/PORT/DB/USER/PASSWORD`, по умолчанию `app_ro`/`app_ro`), опции `statement_timeout=5000`, `default_transaction_read_only=on`; `app/db.py` не менять. Каталоги читаются на каждый запрос.

Ошибки: `{error, allowed: list[str], detail?}`, свой handler вместо стандартного 422.
| HTTP | error | allowed |
|---|---|---|
| 422 | `unknown_metric` / `unknown_dim` | коды метрик / срезов каталога |
| 422 | `dim_not_allowed` | `allowed_dims` метрики (для `date_*` без `month` — `[]`) |
| 422 | `non_additive_rollup` | `["with_total=false"]` |
| 422 | `invalid_request` | `[]`; форма, `group_by`>2 или дубли, `limit`∉1..1000, >10 значений, >6 фильтров, `date_from>date_to`, `grain` |
| 504/503/500 | `query_timeout`/`db_unavailable`/`internal` | `[]`; SQL и текст исключения не отдаём, только в лог |

Порядок проверок: форма → metric → dims (`group_by`, `filters`) → rollup.

**GET /api/metrics** → `{metrics[{code,name,description,unit,additivity,is_additive,source_view,grain,allowed_dims,note,formula_sql}], dimensions[{code,name,dim_type,source_views}], grains, limits{default,max}}`.

**POST /api/query**. Вход — K0 §5 + `grain: day|week|month = month`, `sort: asc|desc|null` (по метрике), `with_total: bool = false`. Выход — K0 §5 + `total: float|null`. Правила:
1. SQL — §3. `columns`: dims в порядке `group_by` (имя = dim_code), затем метрика.
2. Порядок: `sort` задан → по метрике; иначе при `month` — по нему asc, иначе по метрике desc; далее по остальным dims.
3. `LIMIT limit+1`; лишняя строка отбрасывается, `truncated=true`.
4. `grain` влияет только на dim `month` (значение = дата начала периода), без него игнорируется (`ASSUMPTION K1-2`).
5. `date_from/date_to` включительно, по `purchase_ts`; метрика без `month` в `allowed_dims` → `dim_not_allowed`.
6. `with_total=true` только при `additivity='additive'`, иначе `non_additive_rollup`. Итог — отдельный запрос без `group_by` с теми же фильтрами, не сумма строк; итог неаддитивной метрики клиент берёт запросом с `group_by=[]`.
7. Decimal→number, даты ISO. `explain.sql` — текст с `%s`, `explain.params` — bind-значения.

**GET /api/status** → `{server_time, stream{mart.stream_status}, last_batch{последняя mart.etl_runs kind='batch'}, last_published{status='published'}, dq{passed,total,failed[]}, reconcile{run_id,ok,items[≤50, is_ok=false первыми]}, last_replay{последняя mart.replay_runs по received_at: replay_id,cutoff,events_total,orders_total,expected,received_at,caught_up_at}}`. Нет данных → секция `null`, пустой поток → нули. `dq.passed/total` = `dq_passed/dq_total` последнего batch; `failed` из `mart.dq_result WHERE NOT passed` (`check_id, description, expected, actual`; таблица в `mart`, `app_ro` читает по `900_grants.sql`). В `reconcile.items` `batch_value`/`stream_value` могут быть `null`. `last_replay` — источник страницы «Контроль» (сверка модели с `expected` после `caught_up_at`), зависит от K2 (§6).

**GET /api/export.csv**: `metric`, `group_by` (повтор), `filters` (JSON-строка), `date_from/date_to`, `grain`, `sort`, `limit` (1..50000, 10000). Конвейер и ошибки (JSON) как у `/api/query`. Ответ `text/csv; charset=utf-8`, заголовок = `columns`, `Content-Disposition: attachment; filename="{metric}.csv"`, `X-Truncated: true|false`. Строка, начинающаяся с `= + - @`, получает префикс `'`.

## 3. Сборка SQL и безопасность
1. В текст SQL попадает только каталожное: `formula_sql`, `source_view`, `column_name`. Всё от клиента — ключ словаря каталога или bind.
2. Идентификаторы — `psycopg2.sql.Identifier`; `source_view` ~ `^mart\.[a-z_]+$`, `column_name` ~ `^[a-z_][a-z0-9_]*$`, иначе 500.
3. `grain`/`sort` — фиксированные словари (`date_trunc('day'|'week')`, `ASC|DESC`), `limit` — bind int. Время для `day/week` и `date_*`: `TIME_COLUMN = {'mart.v_sales_item': 'purchase_ts', 'mart.order_summary': 'purchased_at'}` (в `order_summary` колонка называется `purchased_at`; `mart.v_kpi` времени не имеет, `allowed_dims=[]`); при `month` — `column_name` среза.
4. Фильтр: `{column}::text = ANY(%s)`, числа → `str`, `month` = `YYYY-MM-01`; значение ≤100 символов.
5. Срез допустим, если он в `dimension_catalog` и в `allowed_dims` метрики (`filters` и `group_by` одинаково).
6. Алиасы — `Identifier(dim_code|metric_code)`; конкатенации ввода нет, включая `ORDER BY`/`LIMIT`. Запись и доступ вне `mart` закрыты ролью (K0 §4.4).

## 4. Критерии приёмки
`T` — pytest (§5), `R` — ревью/curl-смоук исполнителя.
| ID | Условие → результат | Пр. |
|---|---|---|
| A-1 | `POST /api/query {metric:revenue}` → 200, 1 строка, `abs(value−13221498.11)<0.005` | T |
| A-2 | `metric:"nope"` → 422 `unknown_metric`, `allowed` содержит `revenue` | T |
| A-3 | `group_by:["foo"]` или ключ `foo` в `filters` → 422 `unknown_dim` | R |
| A-4 | `orders_total` по `seller_state` → 422 `dim_not_allowed`; `repeat_customers_pct`+`date_from` → то же, `allowed=[]` | R |
| A-5 | `avg_check`+`with_total` → 422 `non_additive_rollup`; `revenue`+`with_total` → `total` = запрос без `group_by` | R |
| A-6 | 3 элемента `group_by`, дубль, `limit` 0/1001, `date_from>date_to`, `grain:"year"` → 422 `invalid_request` | R |
| A-7 | `revenue` по `month`, `grain=day`/`week` → даты начала периода; сумма строк = итогу при `month` | R |
| A-8 | `limit:3` по `seller_id` → 3 строки, `truncated=true`; `limit` ≥ групп → `false` | R |
| A-9 | Фильтр `"SP'; DROP TABLE x;--"` → 200, пусто; значения в `explain.sql` нет | R |
| A-10 | `/api/metrics` → 20 метрик, 6 срезов, у метрик `formula_sql`, `allowed_dims` | R |
| A-11 | `/api/status` при пустых `ops.*` → 200, `null`/нули; с данными `stream` = `mart.stream_status`; нет `mart.replay_runs` или пуста → `last_replay=null` | R |
| A-12 | `/api/export.csv?metric=revenue&group_by=customer_state` → `text/csv`, заголовок `customer_state,revenue`, `X-Truncated: false`; ячейка `=cmd` → `'=cmd`; неизвестная метрика → 422 JSON | R |
| A-13 | Роль `app_ro`, `SHOW statement_timeout`=5s; запрос >5 с → 504 `query_timeout`; ошибки без SQL и текста исключения | R |

## 5. Задачи
Коммиты: сообщение без строки `Co-Authored-By` и без упоминаний Claude/ИИ. Тесты — только A-1, A-2 в `tests/api/test_query.py`, без TDD; нет БД или `app_ro` → `skip`.
| № | Задача | Файлы | Образец | Исполнитель | Волна |
|---|---|---|---|---|---|
| T1 | pydantic-модели, `ApiError`, handlers | `app/api/schemas.py`, `errors.py` | K0 §5 | python-developer | 1 |
| T2 | `connect_ro()`, загрузка каталогов | `app/api/db.py`, `catalog.py` | `app/db.py` | python-developer | 1 |
| T3 | сборка и выполнение запроса | `app/api/query_builder.py` | §3 | python-developer | 2 |
| T4 | `/api/status` | `app/api/status.py` | — | python-developer | 2 |
| T5 | роуты metrics/query/export, `router` | `app/api/routes.py`, `export.py`, `__init__.py` | — | python-developer | 3 |
| T6 | `include_router` + 2 теста | `app/main.py`, `tests/api/test_query.py`, `tests/api/__init__.py` | `app/main.py`, `tests/agent/test_llm_smoke.py` | python-developer-lite | 4 |
T1–T5 standard: роль БД, инъекции, CSV-injection, образца нет. T6 lite: по образцу, ≤3 файла. Задачи одной волны параллельны. После T6: `code-reviewer` + `security-engineer` параллельно.

## 6. Зависимость от K0 (для сверки)
- `mart.metric_catalog`: `metric_code, name, description, formula_sql, source_view, grain, additivity (additive|semi|non), is_additive, unit, allowed_dims, note`; 20 строк.
- `mart.dimension_catalog`: `dim_code, name, column_name, dim_type, source_views`; коды `month, customer_state, order_status, seller_state, seller_id, category`.
- Источники: `mart.v_sales_item` (`purchase_ts, purchase_month`), `mart.order_summary` (`purchased_at, purchase_month`; `purchase_ts` там нет), `mart.v_kpi` (без времени).
- `mart.stream_status`: `last_event_ts, events_total, events_per_sec, lag_events, lag_sec, dlq_count, updated_at`.
- `mart.etl_runs`: `run_id, ds, kind, status, started_at, finished_at, dq_passed, dq_total, reconcile_diff, cutoff, note`.
- `mart.reconcile_result`: `run_id, ds, day, check_code, batch_value, stream_value, diff, is_ok, checked_at`; `day`, `batch_value`, `stream_value` nullable (`055_ops_tables.sql`).
- Роль `app_ro`: пароль = имя, `SELECT` на `mart`, `statement_timeout=5s`, read-only. `mart.dq_result(check_id, description, expected, actual, passed, checked_at)` — `sql/80_dq/800_dq_framework.sql`, читается `app_ro`.
- Эталон: revenue без фильтров = 13221498.11.

## 6.1 Зависимость от K2
- `mart.replay_runs` (`sql/60_mart/665_replay_view.sql` над `ops.replay_runs`, `sql/05_landing/057_replay_runs.sql`) — для `last_replay` и страницы «Контроль». До слияния K2 `last_replay=null` (view нет → секция `null`, не 500).
- Факт K2: `mart.v_sales_month`, `order_summary`, `v_seller_sales`, `v_category_sales` (600–620) становятся обычными `VIEW` (данные потока видны сразу). Запросы K1 идут к обычным view; если медленно (>5 с `statement_timeout`) — запасной `ops.refresh_marts()`, решение пользователя.

## 7. Решения по умолчанию
`grain`, `sort`, `with_total`, `total`, `invalid_request`, `last_replay` расширяют K0 §5 — согласовать с K6. Колонка `month` содержит дату начала периода и при `day/week`.
