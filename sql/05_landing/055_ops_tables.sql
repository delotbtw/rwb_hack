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
