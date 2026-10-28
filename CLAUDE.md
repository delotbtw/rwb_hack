# Capibara: модель маркетплейса (хакатон, датасет Olist)

Назначение: из `raw` (8 CSV, 550 759 строк, 09.2016–10.2018) собрать модель `core` и витрины `mart` одним SQL-скриптом на чистой базе. Ответы Q1–Q10 считаются из модели. Требования — `docs/TZ.md`, архитектура — `docs/architecture.md`, дашборды — `docs/dashboards.md`.

## Стек
PostgreSQL 16 (docker, `hack/hack`, БД `marketplace`, :5432) · чистый SQL (без dbt) · make · Python 3.12 (pytest, psycopg2, sqlfluff) · Grafana OSS (опц.) · GitHub Actions.

## Команды
- `make all` — venv → raw → bundle → model (+DQ) → answers → docs → test
- `make reset` — снести БД и загрузить raw заново (`scripts/setup.sh --reset`)
- `make bundle` — собрать `sql/**` в `dist/build_model.sql` (DL-1)
- `make model` — выполнить сборку в одной транзакции; `DQ_MODE=report` — без падения
- `make dq` / `make answers` / `make docs` / `make test` / `make lint` / `make ci` / `make bi`

## Структура и слои
- `sql/NNN_*.sql`: 00 setup → 10 seed → 20 staging (`stg`, views) → 30 dim → 40 fact → 50 constraints → 60 mart-семантика → 70 ответы → 80 DQ. Префиксы глобально уникальны, порядок = порядок сборки.
- `tests/` — pytest; `answers/` и `dist/` — генерируются и коммитятся; `dashboards/` — BI как код.
- Блоки: БД / Бэк / Аналитика / Фронт; контракты К1–К5 описаны в `architecture.md`.

## Правила
- Имена: snake_case, английские, `dim_`, `fact_`, `stg_`, `v_`, `qNN_`; всегда с указанием схемы.
- Типы: деньги `numeric(12,2)`, моменты `timestamp`, флаги `boolean NOT NULL` (`is_`/`has_`); пустые строки → `NULLIF(TRIM(x),'')`.
- Покупатель = `customer_unique_id`. Выручка = Σ `price` по `dim_order_status.is_revenue` (delivered), без freight, месяц по purchase.
- Unknown-member `-1` в каждом измерении; JOIN только LEFT; строки не теряем.
- Каждый SQL-файл начинается с шапки `object / grain / source / cc / why` со ссылками на CC-ID.
- Аномалии не правим: значения как в raw + флаги.

## Запреты
- Не менять `raw`, CSV, `docker-compose.yml`, `scripts/setup.sh`, `load_raw.py`, `scripts/init/`.
- Не считать ответы из `raw` (в `60_*`/`70_*` не должно быть `raw.`).
- Без psql-метакоманд в `sql/`; без JOIN фактов разной гранулы без агрегации.
- Golden-ожидания меняются только с записью в `docs/decisions.md`.

## Quality gate
`make ci` зелёный: sqlfluff 0, сборка с нуля без ошибок, все DQ-01..15 = pass, контроли Q1–Q5 до копейки, pytest зелёный, `dist/` и `answers/` актуальны. Diff прошёл ревью, `docs/ai_usage.md` пополнен, открытые ASSUMPTION перечислены.
