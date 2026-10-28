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
