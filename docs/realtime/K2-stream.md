# K2. Поток: генератор, Redpanda, ingestor
*Спека v1, 2026-10-28. Опора: `K0-contracts.md` (§2-§4), `realtime-plan.md` (§1.1, §2, §4, §5.5), `CLAUDE.md`. Предположения: `ASSUMPTION-K2-n`.*

## 1. Цель и границы
Проиграть Olist потоком в Redpanda и идемпотентно применить в `core`: «история до cutoff (K3) + хвост» даёт Q1-Q5 = контрольным (`docs/tasks.md`). Входит: `stream/generator`, `stream/ingestor`, `stream/broker_reset.py`, `docker-compose.realtime.yml`, `make/stream.mk` (`live|demo-replay|stream-reset`), правки `sql/` под upsert. НЕ входит: фильтр cutoff, `demo-prep|reset`, Airflow (K3); API, «Контроль» (K1); Grafana (K4); правка `Makefile` (только оркестратор).

## 2. Зависимость от K0
- `contracts/events/{envelope,order.created,payment.captured,order.status_changed,review.posted,replay.completed,product.category_changed,customer.address_changed,dlq}.json`; топики `orders.events` (3 партиции, ключ заказных событий `order_id`, у `replay.completed` `replay`), `orders.dlq`.
- `landing.events` (`status` received|applied|skipped_stale|error); `ops.stream_status` (id=1: `last_event_ts, events_total, events_per_sec, lag_events, lag_sec, dlq_count, updated_at`).
- Роль `ingestor` по `900_grants.sql` (K0): `ALL` на `landing`, `SELECT/INSERT/UPDATE` на `core.*`, `SELECT/UPDATE` на `ops.stream_status`, `SELECT` на `ops.build_params`. Гранты K2 — только в `sql/90_grants/920_grants_stream.sql` (`900_grants.sql` не менять; K3 — `910_*`, K4 — `930_*`).

## 3. Клиент Kafka: `confluent-kafka`
librdkafka (≈650 событий/с с запасом), синхронный API ложится на «пачка → COMMIT в PG → `commit()`», есть `AdminClient`, wheels под linux/arm64. `aiokafka` — лишний asyncio при psycopg2; `kafka-python` слабо поддерживается. Пин точной версии (последняя стабильная, wheel под Python 3.12), K0 §2.4.

## 4. Генератор `python -m stream.generator`
Читает `data/*.csv`, дедуп/нормализация как в `sql/20_staging`, аномалии не правим. Параметры: `--cutoff D` (= `--from D`: заказы с `purchased_at >= D`, без него весь датасет), `--duration S`, `--max-gap` (0.2 с), `--noise` (Should: ~1 % дублей и перестановок).
1. События: `created` (`event_ts`=`purchased_at`, статус `created`), `payment.captured` (`purchased_at`), `status_changed`, `review.posted` (`review_created_at`). Конверт и `event_id` по K0 §4.1.
2. Статусы: метки approved_at / delivered_carrier_at / delivered_customer_at → approved / shipped / delivered, но не выше финального `f` из CSV (ранги: created < approved < invoiced < processing < shipped < delivered < unavailable = canceled); метки одного статуса — одно событие. Если `f` не получен из меток — событие `f` с `event_ts` = max меток. Макс. ранг заказа = `f`.
3. Порядок: `(event_ts, created < payment < status < review)`, `created` заказа всегда первый; ключ = `order_id`.
4. Время: пауза `min(k·Δevent_ts, max_gap)`; с `--duration` коэффициент `k` подбирается, сумма ≈ S (±10 %); без него 1 день = 1 с. `schedule()` — чистая функция.
5. Финал: `replay.completed` (`replay_id` uuid4, `events_total` без него, `orders_total` окна, `expected` = итоги полного датасета), `flush()`. Топики создаёт идемпотентно.

## 5. Ingestor `python -m stream.ingestor`
Группа `capibara-ingestor`, ручной commit, один экземпляр (ASSUMPTION-K2-3). Пачка ≤500 сообщений или 200 мс.
0. Пауза (протокол K3 §3.3, единый): первым в транзакции батча `SELECT run_id, paused_at FROM ops.stream_pause WHERE id=1 FOR SHARE`; `run_id IS NOT NULL` и `paused_at` моложе 30 мин → `ROLLBACK`, offset не коммитить, спать 1 с, повторить (ingestor сам «встаёт на паузу», брокер не трогает); иначе обычный батч в той же транзакции. Таблицу `ops.stream_pause` и гранты `SELECT, UPDATE` ingestor-у (`910_grants_batch.sql`) создаёт K3; K2 только читает. Нет таблицы (K3 не слит) → пауза считается снятой.
1. Валидация: не JSON → `invalid_json`; неизвестный `type` → `unknown_type`; `schema_version≠1` → `unsupported_version`; схемы → `schema_violation`. Уходит в `orders.dlq`, в `landing` не пишется.
2. Одна транзакция на пачку, SAVEPOINT на событие. `INSERT landing.events ON CONFLICT (event_id) DO NOTHING`; существующее `applied|skipped_stale` = дубль, пропуск; `received|error` — применить снова (ASSUMPTION-K2-4).
3. Ошибка применения: ROLLBACK TO SAVEPOINT, `status='error'`, DLQ `apply_error`, пачка идёт дальше.
4. `stream_status` в той же транзакции → COMMIT → flush DLQ → `consumer.commit()`. Ошибка БД (в т.ч. пересборка схем): ROLLBACK, переподключение, повтор пачки без commit offset.

Применение (всё upsert):
- `created`: `dim_customer` DO NOTHING; нет `seller_id`/`product_id` → заглушка `is_inferred=true` (товар: `category_key='__unknown__'`, `is_missing_category=true`); `fact_order` DO UPDATE лишь заполняет NULL и **не трогает `order_status`**; `fact_order_item` DO UPDATE тех же значений.
- `payment.captured`, `review.posted`: DO UPDATE по PK ядра. Заказа нет → ошибка применения.
- `status_changed`: `FOR UPDATE` заказа; метки времени `COALESCE(текущая, новая)` всегда; `order_status` только если ранг нового **строго выше** текущего, иначе `skipped_stale`. Коммутативно (ASSUMPTION-K2-2: цепочка Olist линейна, `event_ts` для решения не нужен).
- `product.category_changed`, `customer.address_changed`: `order_id=null`, `event_ts` — время начала действия версии; запись в постоянную историю `ops` по сущности и времени. При совпадении времени побеждает максимальный `event_id` (UUID), независимо от порядка доставки.
- Адрес заказа фиксируется из `order.created` в `ops.order_address_snapshot` и последующими изменениями адреса не обновляется. Категория позиции выбирается на момент покупки по паре продавец–товар; до первой версии используется исходная текущая категория `dim_product`. История и снимки переживают пересборку; Q1–Q5 остаются прежними.
- `replay.completed`: строка `ops.replay_runs`; `caught_up_at` ставится, когда после COMMIT `lag_events=0`.
- `stream_status`: `events_total`, `dlq_count` накопительные; `last_event_ts` = max `event_ts`; `events_per_sec` окно 5 с; `lag_events` = Σ(watermark − позиция); `lag_sec` = now − `produced_at`; в простое раз в 2 с.

`python -m stream.broker_reset` (для `demo-reset` K3): `AdminClient` удаляет топики `orders.events`, `orders.dlq` и consumer group `capibara-ingestor` (ingestor должен быть остановлен); топики пересоздаёт генератор. Без этого повторный реплей даёт те же `event_id` и старые offsets (`ASSUMPTION-K2-5`).

## 6. Правки `sql/`
PK уже есть у всех фактов и измерений (300, 310, 320, 330, 400-430) — `ON CONFLICT` работает, новых ключей не нужно. Нужно:
1. `310_dim_seller.sql`, `330_dim_product.sql`: последняя колонка `false AS is_inferred`.
2. `sql/60_mart/600`, `610`, `620` (2 объекта): `MATERIALIZED VIEW` → `VIEW`, убрать `UNIQUE INDEX` и `COMMENT ON MATERIALIZED`. Иначе Q1-Q5 не видят поток (`REFRESH` ingestor-у недоступен). Это факт, на который опираются K1 и K4 (их запросы идут к обычным view). Если `q01..q05` > 2 с — стоп, согласовать вариант с `ops.refresh_marts()` (решение пользователя).
3. `sql/05_landing/057_replay_runs.sql` (по образцу `055_ops_tables.sql`, `IF NOT EXISTS`): `ops.replay_runs(replay_id uuid PK, cutoff date, events_total bigint, orders_total bigint, expected jsonb NOT NULL, received_at timestamp NOT NULL, caught_up_at timestamp)`; `sql/60_mart/665_replay_view.sql` (`mart.replay_runs`); `sql/90_grants/920_grants_stream.sql`: `SELECT, INSERT, UPDATE ON ops.replay_runs` ingestor-у (ASSUMPTION-K2-1: пробел K0, нужен K1 — `/api/status`, «Контроль»). Нумерация `sql/05_landing`: 056 — K3 (`ops.stream_pause`), 057 — K2.
4. `make bundle` → `dist/`, `answers/`.

## 7. Инфраструктура
`docker-compose.realtime.yml` (профиль `realtime`; `docker-compose.yml` не менять): `redpanda` (пин тега, `dev-container`, `--smp 1 --memory 1G`, `redpanda:9092` / `localhost:19092`, healthcheck `rpk cluster health`), `redpanda-console` (пин, порт 8089: 8080 pgAdmin, 8082 Airflow, 3000 Grafana), `generator`, `ingestor` (`restart: unless-stopped`) на `capibara-python:dev`. Env в `.env.example`: `KAFKA_BOOTSTRAP, BATCH_MAX, BATCH_WAIT_MS, CUTOFF=2018-08-01, DURATION=60`.
`make/stream.mk` (единственная make-правка K2; `Makefile` не трогать — строку `-include make/*.mk` добавляет оркестратор): `COMPOSE_RT := $(COMPOSE) -f docker-compose.realtime.yml --profile realtime`. `make live`: `postgres`, `redpanda`, `redpanda-console`, `ingestor` до healthy. `make demo-replay`: `live` + `run --rm generator --cutoff $(CUTOFF) --duration $(DURATION)`, печать `stream_status`. `make stream-reset`: остановить `ingestor`, `run --rm … python -m stream.broker_reset`; ingestor остаётся остановленным до `make live`.

## 8. Критерии готовности
- A-1 `--cutoff 2018-08-01`: 6 532 заказа, 39 099 событий (±2 %) + один `replay.completed` (уточнено по факту §4 п.2: три статусных события на delivered-заказ).
- A-2 События валидны по `contracts/events`; `created` каждого заказа первый; ключ = `order_id`.
- A-3 Два запуска → одинаковые `event_id`.
- A-4 `schedule()`: порядок сохранён, пауза ≤ `max_gap`, сумма ∈ [0.9S, S] при S=60.
- A-5 `replay.completed` последний; без `--cutoff` `orders_total`=99 441, `expected` = 99441 / "13221498.11" / "159.88" / 96096 / "3.12".
- A-6 Макс. ранг статусов заказа = `order_status` из CSV (весь датасет).
- A-7 Битый JSON, схема, `type`, `schema_version=2` → запись в `orders.dlq` с верным `reason_code`; в `landing` нет.
- A-8 Повтор пачки не меняет count 4 фактов, Σ`price`, Σ`payment_value`, число строк `landing.events`.
- A-9 `delivered`, затем `approved` → `delivered`, `approved_at` заполнен, `approved` = `skipped_stale`; обратный порядок — то же состояние.
- A-10 Неизвестные продавец/товар → заглушка `is_inferred=true`, позиция сохранена.
- A-11 Событие несуществующего заказа → DLQ `apply_error`, `landing.status='error'`, остальные в пачке применены.
- A-12 Падение до COMMIT → повторная доставка, итог тот же.
- A-13 После реплея `lag_events=0`, `dlq_count` = числу в `orders.dlq`, `mart.replay_runs.caught_up_at IS NOT NULL`.
- A-14 `make reset`: DQ pass, Q1-Q5 прежние, `q01..q05` ≤ 2 с, `is_inferred=false` везде; ingestor может upsert, DELETE/TRUNCATE нет.
- A-15 `stream/verify.py` (без K3): отпечатки фактов (count, суммы, count по статусам, md5 строк) → под `hack` `TRUNCATE` 4 фактов и `landing.events` → полный реплей `--duration 120` → ждёт `caught_up_at` → отпечатки равны, Q1-Q5 контрольные.
- A-16 После K3 `demo-prep`: `make demo-replay` за 60±10 с → Q1-Q5 контрольные, DLQ=0; повтор после `demo-reset` — то же.
- A-17 `compose config` валиден, `git diff docker-compose.yml` пуст, K2 не правит `Makefile` (кроме строки оркестратора `-include make/*.mk`), Console на `localhost:8089`.
- A-18 Пауза (после K3): при `ops.stream_pause.run_id IS NOT NULL` ingestor не коммитит offset и не пишет в `landing`; после `run_id=NULL` догоняет без потерь.

## 9. Решения и тесты
- Конкурентность: дубль — PK `landing.events`; статус — `FOR UPDATE` + коммутативный ранг; факты — PK ядра; пауза — `FOR SHARE` на `ops.stream_pause` (K3 §3.3).
- Тесты минимум: `tests/stream/test_apply.py` (A-8..A-11, живая БД, без Kafka, `apply_batch(conn, events)`), `test_schedule.py` (A-4), `verify.py` (A-15).
- Риск: дедуп CSV в генераторе и заказы с `f='created'` и метками уточняются по расхождению A-15.
- Must: A-1…A-15, A-17. Should: `--noise`, A-16, A-18 (после K3).

## 10. План реализации
Все standard (гранты, конкурентность, схема); lite нет. Коммиты: сообщение без строки `Co-Authored-By` и без упоминаний Claude/ИИ.
| № | Задача | Файлы | Образец | Исполнитель | Волна |
|---|---|---|---|---|---|
| T1 | Compose, make, env, зависимость | `docker-compose.realtime.yml`, `make/stream.mk`, `.env.example`, `requirements.txt` | `docker-compose.app.yml`, `Makefile` | devops | 1 |
| T2 | SQL §6 + `make bundle` | `sql/30_core_dim/310*,330*`, `sql/60_mart/600*,610*,620*,665*`, `sql/05_landing/057*`, `sql/90_grants/920_grants_stream.sql`, `dist/`, `answers/` | `055_ops_tables.sql`, `660_ops_views.sql` | python-developer | 1 |
| T3 | Генератор, `stream/common.py`, `broker_reset.py` | `stream/__init__.py`, `common.py`, `broker_reset.py`, `generator/*` | — | python-developer | 1 |
| T4 | Ingestor | `stream/ingestor/*` | `stream/common.py` | python-developer | 2 (после T2, T3) |
| T5 | Тесты, `verify.py` | `tests/stream/*`, `stream/verify.py` | `tests/` | python-developer | 3 |
| T6 | Сквозной прогон A-12, A-13, A-15, A-17 | по результату | — | devops | 4 |
Параллельно с K1 (`app/api/`), K3 (`airflow/`, `pipeline/`), K4 (`dashboards/grafana/`); внутри K2 T1-T3 параллельны.

### Пересечения
- Владелец K2: `docker-compose.realtime.yml`, `make/stream.mk`, `stream/`, `sql/30_core_dim`, `sql/60_mart/600-620,665`, `sql/05_landing/057*`, `sql/90_grants/920_*`. Владелец K3: `sql/20_staging`, `sql/80_dq`, `sql/05_landing/056*`, `sql/90_grants/910_*`, `docker-compose.airflow.yml`, `make/batch.mk`. K4: `sql/60_mart/67x`, `sql/90_grants/930_*`, `make/bi.mk`.
- `Makefile`: единое правило — строку `-include make/*.mk` в конец добавляет оркестратор до первой волны; K2 пишет `make/stream.mk`, K3 `make/batch.mk`, K4 `make/bi.mk`; больше никто `Makefile` не правит. `requirements.txt`: K2 дописывает лишь `confluent-kafka`.
- `dist/`, `answers/` не мержить, а перегенерировать `make bundle`; финально — интеграция.
- K3: протокол паузы (§5 п.0, K3 §3.3). `demo-reset` (K3 §3.7) делает `make stream-reset` (брокер) и `TRUNCATE landing.events, ops.replay_runs`, обнуляет `ops.stream_status` (иначе `event_id` повторного реплея = дубли).
- K1: «Контроль» и `/api/status` (`last_replay`) читают `mart.replay_runs`, сверка модели с `expected` после `caught_up_at`.
