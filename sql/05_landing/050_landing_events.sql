-- object : landing.events
-- grain  : 1 строка = 1 событие orders.events (event_id)
-- source : Kafka topic orders.events
-- cc     : K0 §4.1, §4.2
-- why    : неизменяемый журнал входящих событий; PK event_id даёт идемпотентность
--          (ON CONFLICT DO NOTHING), IF NOT EXISTS — данные переживают пересборку

CREATE TABLE IF NOT EXISTS landing.events (
    event_id       uuid PRIMARY KEY,
    topic          text,
    partition      integer,
    kafka_offset   bigint,
    order_id       text,
    type           text NOT NULL CHECK (type IN (
                       'order.created', 'payment.captured', 'order.status_changed',
                       'review.posted', 'replay.completed')),
    schema_version smallint,
    payload        jsonb NOT NULL,
    event_ts       timestamp NOT NULL,
    produced_at    timestamp,
    received_at    timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    status         text NOT NULL DEFAULT 'received'
                       CHECK (status IN ('received', 'applied', 'skipped_stale', 'error')),
    error          text
);

CREATE INDEX IF NOT EXISTS ix_events_order_event_ts ON landing.events (order_id, event_ts);
CREATE INDEX IF NOT EXISTS ix_events_event_ts ON landing.events (event_ts);
CREATE INDEX IF NOT EXISTS ix_events_received_not_applied ON landing.events (received_at)
    WHERE status <> 'applied';

COMMENT ON TABLE landing.events IS 'Журнал событий orders.events: 1 строка = 1 event_id';
COMMENT ON COLUMN landing.events.kafka_offset IS 'Offset в партиции (offset — зарезервированное слово)';
