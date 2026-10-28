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
