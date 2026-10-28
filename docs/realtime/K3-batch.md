# Этап K3. Ночная сборка (Airflow) и демо-режим cutoff
*Спецификация v1, 2026-10-28. Опирается на: `K0-contracts.md` (§2, §3, §4.3, §4.5), `realtime-plan.md` (§1.1, §5). Предположения: `ASSUMPTION`.*

## 1. Цель и границы
Batch-путь как шаги-функции для `make etl` и DAG `capibara_daily`; `cutoff` для демо «история + хвост»; пауза потока на время сборки (вариант A).
Входит: фильтр cutoff в stg и DQ; рефакторинг `pipeline/`; учёт в `ops.etl_runs`; reconcile; HTML-отчёт; DAG; профиль `airflow`; цели `demo-prep`, `demo-reset`, `airflow`.
НЕ входит: ingestor, генератор, сброс брокера (K2); API (K1); Grafana (K4); страница «Контроль»; теневые схемы; рассылка.

## 2. Пользовательские истории
Аналитик: US-1 ежедневный `output/daily/<ds>.html`. Оператор: US-2 граф DAG и логи; US-3 `failed`/`blocked` в `ops.etl_runs`. Демонстратор: US-4 `demo-prep`; US-5 `demo-reset`.

## 3. Контракты

### 3.1 Фильтр cutoff
Значение и семантика — K0 §4.5.
1. `200_stg_orders`: `cutoff IS NULL OR purchased_at < cutoff`; `purchased_at IS NULL` при заданном cutoff исключается.
2. `210/220/230`: только заказы из `stg.orders` (`EXISTS`, не JOIN); при `cutoff IS NULL` фильтр обходится целиком (сироты сохраняются). `240–270`, `stg.customers` — без фильтра.
3. При `cutoff IS NOT NULL` проверки с `raw.*` (`805_dq_marts`, DQ-01) считают raw-сторону с тем же фильтром; константные эталоны (DQ-03..09, Q1-ZERO, Q*-CTRL) пишутся `passed=true, expected='skip: cutoff'`; DQ-10..12 как есть. `ASSUMPTION K3-1`.

### 3.2 Шаги (поведение `make etl` прежнее: вывод, коды выхода, импорт ноутбуков)
`pipeline/steps.py`:
- `ensure_ops()` — применяет `002`, `055`, `056` (идемпотентны) до первой сборки.
- `open_run(ds, kind, cutoff) -> run_id` — `running`; старая `running` того же `(ds, kind)` → `failed`, `note='superseded'`.
- `extract(run_id, ds)` — `data/*.csv`: имя, строки (>0), sha256 → `output/manifest/<ds>.json`; иначе исключение.
- `load_raw(run_id, force=False)` — прежняя логика (не перезаливает без `force` или пустого raw).
- `build(run_id, cutoff)` — `pause_stream`, запись cutoff в `ops.build_params`, `bundle.build()` одной транзакцией.
- `dq(run_id) -> (passed, total)` — прежний отчёт; пишет `dq_passed/dq_total`.
- `publish(run_id)` — `published`, `finished_at`, `resume_stream`.
- `mark_failed(run_id, ds, error)` — `failed` (`blocked` не меняет), `note`, `resume_stream`; без `run_id` — `open_run`.
- `pause_stream(run_id)`, `resume_stream()` — 3.3.
`pipeline/reconcile.py`: `snapshot_stream(run_id)`, `reconcile(run_id, strict=True)`. `pipeline/daily_report.py`: `report(run_id, ds) -> Path`. `pipeline/demo.py`: `prep(cutoff)`, `reset(cutoff)`.
`kind` = `batch` (`make etl`, DAG) или `demo`. Каждый запуск пишет свой cutoff в `build_params` (env `CUTOFF`, пусто = `NULL`; DAG — `dag_run.conf.cutoff`). Строка `etl_runs` пишется отдельным autocommit-соединением, откат сборки её не затрагивает. `make etl` и demo не вызывают `extract`, `snapshot_stream`, `reconcile`, `report`.

### 3.3 Пауза потока (контракт для K2)
`ops.stream_pause` (`sql/05_landing/056_ops_stream_pause.sql`): `id smallint PK CHECK (id=1)`, `run_id bigint NULL`, `paused_at timestamp NULL`; сид `(1,NULL,NULL)`. Гранты `ingestor`: `SELECT, UPDATE` (`910_grants_batch.sql`).
1. `pause_stream`: `UPDATE … SET run_id, paused_at=now()`. Ждёт `COMMIT` текущих батчей ingestor (row lock), новые видят паузу.
2. Ingestor первым в транзакции батча: `SELECT run_id, paused_at FROM ops.stream_pause WHERE id=1 FOR SHARE`. `run_id IS NOT NULL` и `paused_at` моложе 30 мин → `ROLLBACK`, offset не коммитить, спать 1 с. Реализует K2.
3. `resume_stream` (`run_id=NULL`) вызывают `publish`, `mark_failed`, `blocked`: на любой исход пауза снимается, ingestor догоняет из брокера и `landing`.

### 3.4 Reconcile (допуск 0.00)
1. `snapshot_stream` (после паузы, до `build`): по `core` за каждый день `purchased_at::date` — `orders_count`, `revenue_sum` (Σ `price`, `is_revenue`), `payments_sum` (Σ `payment_value`) и итог (`day IS NULL`) → `ops.reconcile_result(stream_value, is_ok=false)`. Пустого `core` нет — строк нет. Только `kind=batch`, `cutoff IS NULL`.
2. `reconcile` (после `build`): те же агрегаты по новой модели → `batch_value`, `is_ok = diff=0`; `etl_runs.reconcile_diff` = Σ|diff| итогов. Нет снимка → `note='reconcile_skipped'`, без ошибки.
3. Есть `is_ok=false` при `strict` → `status=blocked` и исключение. Модель уже закоммичена (вариант A): блокировка = нет `published` и алерт.
Колонки `core` уточняет исполнитель (`ASSUMPTION K3-2`).

### 3.5 Отчёт и DAG
`report` → `output/daily/<ds>.html` (stdlib, `html.escape`): за день `ds` заказы, выручка, средний чек; накопительно до `ds` заказы, выручка, доля просрочек, топ-5 категорий; DQ `passed/total`; `reconcile_diff`; длительность. Падение отчёта статус `published` не меняет.
`airflow/dags/capibara_daily.py`: `@daily`, `catchup=True`, `max_active_runs=1`, `start_date` из env `CAPIBARA_START_DATE` (по умолчанию 2026-10-20; `ASSUMPTION K3-3`). `PythonOperator`: `extract → load_raw → snapshot_stream → build → dq → reconcile → publish → report`, `ds` из контекста, `run_id` через XCom `extract`; `retries=3` у `extract`, у прочих 0; `on_failure_callback` → `mark_failed`.

### 3.6 Airflow и make
Версия: **Airflow 2.11.x, Python 3.12, пин и constraints в `docker/airflow.Dockerfile`**. Причина: 3 контейнера (3.x требует api-server, dag-processor, triggerer и меняет импорты). `ASSUMPTION K3-4`: патч-тег проверить по Docker Hub.
`docker-compose.airflow.yml`, профиль `airflow`: `airflow-init` (БД `airflow` в том же Postgres, `db migrate`, `admin/admin`), `airflow-scheduler`, `airflow-webserver` (:8082). `LocalExecutor`, `LOAD_EXAMPLES=false`; монтируются `./` (`PYTHONPATH`) и `airflow/dags`; `PG*` как у `etl`.
`make/batch.mk`: `airflow`, `airflow-down`, `demo-prep`, `demo-reset` (`$(COMPOSE) run --rm etl python -m pipeline.demo …`, `CUTOFF` по умолчанию `2018-08-01`).

### 3.7 Демо
`prep`: `ensure_ops`, `open_run(demo)`, `load_raw`, `build(cutoff)`, `dq`, `publish`. `reset` = `prep` + под паузой `TRUNCATE landing.events` и обнуление `ops.stream_status`. Финал демо — запуск DAG без cutoff (полная сборка + reconcile).

## 4. Аудит
`ops.etl_runs` (каждый запуск), `ops.reconcile_result`. Содержимое DQ и логи Airflow не дублируем.

## 5. Страницы
Airflow UI `:8082` (admin/admin, локально). Страницы приложения не затрагиваются.

## 6. Критерии приёмки (минимум крупного, не TDD)
- A-1 `cutoff=NULL`: `make etl` зелёный, DQ 15/15, `fact_order`=99 441, Q1–Q5 как в K0 A-1, вывод и код выхода прежние.
- A-2 `cutoff=2018-08-01`: `fact_order`=92 909, `MAX(purchased_at)<cutoff`, позиций/платежей/отзывов чужих заказов 0, `dim_product/seller/customer` как при NULL.
- A-3 При cutoff сборка не откатывается; DQ-01 и DQ-10..12 pass, константные эталоны `skip: cutoff`.
- A-4 Запуск пишет `etl_runs`: `published`, `dq_passed=dq_total`, `finished_at`, `cutoff`; второй `running` того же `(ds, kind)` → прежний `failed/superseded`.
- A-5 Принудительный сбой сборки (strict): код 1, `failed`, `stream_pause.run_id IS NULL`, прежняя модель цела.
- A-6 Открытая транзакция с `FOR SHARE` на `stream_pause` задерживает `pause_stream` до `COMMIT`; после `publish` `run_id IS NULL`.
- A-7 Снимок, затем удалён заказ в `core`: `reconcile` → `blocked`, `is_ok=false`, `diff≠0`. Без правок: все `is_ok`, `reconcile_diff=0.00`, у каждого `check_code` есть строка `day IS NULL`.
- A-8 Нет/пустой `core` → `reconcile_skipped`, без ошибки.
- A-9 `report` создаёт `output/daily/<ds>.html` с выручкой и `DQ x/y`; ошибка отчёта оставляет `published`.
- A-10 `DagBag` без import errors; `@daily`, `catchup=True`, `max_active_runs=1`, 8 задач в порядке 3.5, `on_failure_callback` задан.
- A-11 `airflow dags test capibara_daily <ds>`: 8 задач success, `published`.
- A-12 `docker compose … --profile airflow config` валиден, 3 сервиса, :8082 отвечает 200.
- A-13 `make demo-prep`: `build_params.cutoff=2018-08-01`, `fact_order`=92 909, `kind=demo`, `published`.
- A-14 `make demo-reset` после строк в `landing.events` и `core`: `landing.events` пуст, `stream_status` нули, `fact_order`=92 909.

## 7. Нефункциональные требования
Схема — только `sql/` (`056`, `910`). Новых зависимостей в `pipeline/` нет; Airflow — только в образе, с пином. Сборка < 30 с (условие варианта A).
Конкурентность: запуски не накладываются (`max_active_runs=1`, supersede в `open_run`); пауза — row lock на `ops.stream_pause`; `build_params`/`stream_pause` — одна строка (`CHECK (id=1)`).

### 7.1 Зависимость от K0
`ops.build_params(id, cutoff, updated_at)`; `ops.etl_runs(run_id, ds, kind, status, started_at, finished_at, dq_passed, dq_total, reconcile_diff, cutoff, note)`; `ops.reconcile_result(run_id, ds, day, check_code, batch_value, stream_value, diff, is_ok, checked_at)` (`batch_value`/`stream_value` должны быть nullable — проверить в K0 T1); `ops.stream_status`; `landing.events`; `mart.dq_result`; `core.dim_order_status.is_revenue`; роли `hack` (пишет `ops`), `ingestor`; порядок бандла `00_setup → 05_landing → … → 90_grants` (`056` и `910` идут после K0-файлов).

## 8. MVP-срез и Later
Must: 3.1–3.4, 3.7, DAG, compose, A-1..A-14. Should: топ-категории в отчёте. Later: срез `landing` в `extract`, проверка заголовков CSV, email/Telegram, теневые схемы.

## 9. Решения по умолчанию
| # | Вопрос | Решение |
|---|---|---|
| 1 | Механизм паузы | таблица, не advisory lock: пауза живёт дольше одного процесса задачи Airflow |
| 2 | cutoff ночной сборки | DAG пишет `NULL` (полная) |
| 3 | `ds` у `make etl` | `CURRENT_DATE` |

## 10. План реализации
| № | Задача | Файлы | Образец | Исполнитель | Волна | Почему |
|---|---|---|---|---|---|---|
| T1 | cutoff в stg и DQ + проверки A-1..A-3 | `sql/20_staging/200,210,220,230_*.sql`, `sql/80_dq/805_dq_marts.sql`, `810_dq_checks.sql`, `tests/batch/test_cutoff.py` | те же файлы | python-developer, standard | 1 | >3 файлов, DQ |
| T2 | Шаги, пауза, `run_etl` | `pipeline/steps.py`, `pipeline/run_etl.py`, `sql/05_landing/056_ops_stream_pause.sql`, `sql/90_grants/910_grants_batch.sql` | `run_etl.py`, `055_ops_tables.sql` | python-developer, standard | 1 | гранты, блокировки |
| T3 | Reconcile и отчёт | `pipeline/reconcile.py`, `pipeline/daily_report.py` | `run_etl.report` | python-developer, standard | 1 | деньги, 3.4 |
| T5 | compose, образ, make | `docker-compose.airflow.yml`, `docker/airflow.Dockerfile`, `make/batch.mk` | `docker-compose.app.yml`, `docker/python.Dockerfile` | devops, standard | 1 | инфраструктура |
| T4 | DAG + проверка импорта | `airflow/dags/capibara_daily.py`, `tests/airflow/test_dag_import.py` | — | python-developer, standard | 2 | нужны T2, T3 |
| T6 | Демо-режим | `pipeline/demo.py` | `run_etl.main` | python-developer, standard | 2 | нужен T2 |
| T7 | Интеграция: `make reset`, A-1..A-14, `dist/` | `dist/build_model.sql` | — | python-developer, standard | 3 | сквозная проверка |

Lite-задач нет. Сигнатуры из 3.2 фиксированы, поэтому T3/T4/T6 стартуют по ним. Коммиты — K0 §2.

### 10.1 Пересечения
С K1 (`app/api/`), K2 (`stream/`), K4 (`dashboards/grafana/`) файлы не пересекаются. Раздельные файлы: K2 — `docker-compose.realtime.yml`, `make/stream.mk`; K3 — `docker-compose.airflow.yml`, `make/batch.mk`. Единственную правку `Makefile` (`-include make/*.mk` в конце) делает оркестратор до волны; агенты `Makefile` не трогают. `dist/` коммитит только T7. Открыто для K2: протокол паузы 3.3 и сброс топика/consumer group.
