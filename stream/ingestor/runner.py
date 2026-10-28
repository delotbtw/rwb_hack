"""Цикл ingestor: пачка -> одна транзакция -> COMMIT -> DLQ -> commit offset (K2 §5)."""

import logging
import os
import signal
import sys
import time
from collections import deque
from datetime import datetime, timezone
from typing import NamedTuple

import psycopg2
from confluent_kafka import Consumer, KafkaError, KafkaException, Producer, TopicPartition

from stream.common import (
    CONSUMER_GROUP,
    TOPIC_DLQ,
    TOPIC_EVENTS,
    admin_client,
    connect_pg,
    dumps,
    ensure_topics,
    kafka_conf,
    load_validator,
)
from stream.ingestor.apply import BatchResult, Incoming, apply_batch
from stream.ingestor.validate import REASON_APPLY, Rejected, dlq_message, parse_message

log = logging.getLogger("stream.ingestor")

RATE_WINDOW_SEC = 5.0
HEARTBEAT_SEC = 2.0
PAUSE_RECHECK_SEC = 1.0
DB_RETRY_SEC = 2.0
PROGRESS_EVERY = 5000

_PAUSE_ACTIVE = """
SELECT COALESCE(run_id IS NOT NULL AND paused_at > (now() AT TIME ZONE 'utc') - interval '30 minutes', false)
FROM ops.stream_pause WHERE id = 1 FOR SHARE
"""

_UPDATE_STATUS = """
UPDATE ops.stream_status SET
    last_event_ts  = GREATEST(last_event_ts, %(last_event_ts)s::timestamp),
    events_total   = events_total + %(events)s,
    dlq_count      = dlq_count + %(dlq)s,
    events_per_sec = %(rate)s,
    lag_events     = COALESCE(%(lag)s, lag_events),
    lag_sec        = COALESCE(%(lag_sec)s, lag_sec),
    updated_at     = now() AT TIME ZONE 'utc'
WHERE id = 1
"""


class Entry(NamedTuple):
    """Сообщение брокера: конверт события либо причина отказа."""

    topic: str
    partition: int
    offset: int
    key: bytes | None
    raw: bytes | None
    parsed: dict | Rejected


def _parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(timezone.utc)


class Ingestor:
    def __init__(self) -> None:
        self.batch_max = int(os.getenv("BATCH_MAX", "500"))
        self.batch_wait = int(os.getenv("BATCH_WAIT_MS", "200")) / 1000
        self.validator = load_validator()
        self.consumer = Consumer(kafka_conf(**{
            "group.id": CONSUMER_GROUP,
            "client.id": "capibara-ingestor",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }))
        self.producer = Producer(kafka_conf(**{"client.id": "capibara-ingestor-dlq", "enable.idempotence": True}))
        self.conn = None
        self.use_pause = False
        self.stop = False
        self.applied: dict[int, int] = {}
        self.window: deque[tuple[float, int]] = deque()
        self.last_status = 0.0
        self.replay_pending = True
        self.paused = False
        self.processed = 0

    # --- Postgres ---

    def _connection(self):
        if self.conn is None:
            conn = connect_pg()
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('ops.stream_pause') IS NOT NULL")
                self.use_pause = cur.fetchone()[0]
            conn.commit()
            self.conn = conn
        return self.conn

    def _drop_connection(self) -> None:
        conn, self.conn = self.conn, None
        if conn is not None:
            try:
                conn.close()
            except psycopg2.Error:
                pass

    def _pause_active(self, cur) -> bool:
        if not self.use_pause:
            return False
        cur.execute(_PAUSE_ACTIVE)
        row = cur.fetchone()
        return bool(row and row[0])

    # --- Kafka ---

    def _collect(self) -> list[Entry]:
        entries = []
        for message in self.consumer.consume(self.batch_max, self.batch_wait):
            error = message.error()
            if error is not None:
                if error.fatal():
                    raise KafkaException(error)
                if error.code() != KafkaError._PARTITION_EOF:
                    log.warning("consumer: %s", error)
                continue
            raw = message.value()
            entries.append(Entry(message.topic(), message.partition(), message.offset(), message.key(), raw,
                                 parse_message(raw, self.validator)))
        return entries

    def _hold(self, seconds: float) -> None:
        """Ждёт, не теряя членства в группе: партиции на паузе, poll() держит max.poll.interval."""
        assignment = self.consumer.assignment()
        if assignment:
            self.consumer.pause(assignment)
        try:
            self.consumer.poll(seconds)
        finally:
            if assignment:
                self.consumer.resume(assignment)

    def _start_position(self, partition: TopicPartition, low: int) -> int:
        committed = self.consumer.committed([TopicPartition(partition.topic, partition.partition)], timeout=10)
        offset = committed[0].offset if committed else -1
        return offset if offset >= 0 else low

    def _lag(self, ahead: dict[int, int], fresh: bool = False) -> int | None:
        """Σ(watermark - позиция применённого); None, пока партиции не назначены.

        Кэшированный watermark обновляется выборкой и в рабочем цикле дёшев (запрос к брокеру ~0.4 с на вызов);
        на паузе и в простое выборки нет, поэтому там fresh=True.
        """
        assignment = self.consumer.assignment()
        if not assignment:
            return None
        total = 0
        for partition in assignment:
            low, high = self.consumer.get_watermark_offsets(partition, timeout=10, cached=not fresh)
            if high < 0:
                low, high = self.consumer.get_watermark_offsets(partition, timeout=10)
            position = ahead.get(partition.partition, self.applied.get(partition.partition))
            if position is None:
                position = self.applied[partition.partition] = self._start_position(partition, low)
            total += max(0, high - max(position, low))
        return total

    def _publish_dlq(self, items: list[tuple[str, str, Entry | Incoming, str | None]]) -> None:
        failed = []

        def delivered(err, _msg) -> None:
            if err is not None:
                failed.append(err)

        for code, detail, source, event_id in items:
            raw = source.raw if source.raw is not None else b""
            message = dlq_message(code, detail, source.topic, source.partition, source.offset, event_id,
                                  raw.decode("utf-8", errors="replace"))
            self.producer.produce(TOPIC_DLQ, key=source.key, value=dumps(message), on_delivery=delivered)
        self.producer.flush(30)
        if failed:
            raise RuntimeError(f"{len(failed)} DLQ messages were not delivered: {failed[0]}")

    # --- статус ---

    def _rate(self, now: float, extra: int) -> float:
        floor = now - RATE_WINDOW_SEC
        return round((sum(n for t, n in self.window if t > floor) + extra) / RATE_WINDOW_SEC, 2)

    def _record(self, now: float, count: int) -> None:
        self.window.append((now, count))
        floor = now - RATE_WINDOW_SEC
        while self.window and self.window[0][0] <= floor:
            self.window.popleft()

    def _mark_caught_up(self, lag: int | None) -> None:
        if lag != 0 or not self.replay_pending:
            return
        conn = self._connection()
        with conn.cursor() as cur:
            cur.execute("UPDATE ops.replay_runs SET caught_up_at = now() AT TIME ZONE 'utc' "
                        "WHERE caught_up_at IS NULL")
        conn.commit()
        self.replay_pending = False

    def _heartbeat(self) -> None:
        """Простой или пауза: раз в HEARTBEAT_SEC обновляет stream_status."""
        now = time.monotonic()
        if now - self.last_status < HEARTBEAT_SEC:
            return
        self.last_status = now
        try:
            conn = self._connection()
            lag = self._lag({}, fresh=True)
            with conn.cursor() as cur:
                cur.execute(_UPDATE_STATUS, {"last_event_ts": None, "events": 0, "dlq": 0,
                                             "rate": self._rate(now, 0), "lag": lag,
                                             "lag_sec": 0 if lag == 0 else None})
            conn.commit()
            self._mark_caught_up(lag)
        except psycopg2.Error as exc:
            log.warning("heartbeat failed: %s", exc)
            self._drop_connection()

    # --- пачка ---

    def _process(self, entries: list[Entry]) -> bool:
        """True - пачка закоммичена; False - поток на паузе (ROLLBACK, offset не тронут)."""
        conn = self._connection()
        with conn.cursor() as cur:
            if self._pause_active(cur):
                conn.rollback()
                return False
            result = apply_batch(conn, [
                Incoming(entry.parsed, entry.topic, entry.partition, entry.offset, entry.key, entry.raw)
                for entry in entries if not isinstance(entry.parsed, Rejected)
            ])

            dlq = [(entry.parsed.reason_code, entry.parsed.reason_detail, entry, entry.parsed.event_id)
                   for entry in entries if isinstance(entry.parsed, Rejected)]
            dlq += [(REASON_APPLY, detail, source, source.envelope["event_id"]) for source, detail in result.errors]

            ahead = {}
            for entry in entries:
                ahead[entry.partition] = max(ahead.get(entry.partition, 0), entry.offset + 1)
            now = time.monotonic()
            lag = self._lag(ahead)
            cur.execute(_UPDATE_STATUS, {
                "last_event_ts": result.last_event_ts,
                "events": result.new_events,
                "dlq": len(dlq),
                "rate": self._rate(now, len(entries)),
                "lag": lag,
                "lag_sec": self._lag_sec(entries),
            })
        conn.commit()
        self._record(now, len(entries))
        self.last_status = now

        if dlq:
            self._publish_dlq(dlq)
        self.consumer.commit(offsets=[TopicPartition(TOPIC_EVENTS, partition, offset)
                                      for partition, offset in ahead.items()], asynchronous=False)
        self.applied.update(ahead)
        self._after_commit(result, len(entries))
        return True

    @staticmethod
    def _lag_sec(entries: list[Entry]) -> float | None:
        for entry in reversed(entries):
            if not isinstance(entry.parsed, Rejected):
                produced = _parse_utc(entry.parsed["produced_at"])
                return round(max(0.0, (datetime.now(timezone.utc) - produced).total_seconds()), 2)
        return None

    def _after_commit(self, result: BatchResult, count: int) -> None:
        previous = self.processed
        self.processed += count
        if self.processed // PROGRESS_EVERY > previous // PROGRESS_EVERY:
            log.info("processed %d messages", self.processed)
        if result.replay_seen:
            self.replay_pending = True
        if self.replay_pending:
            try:
                self._mark_caught_up(self._lag({}))
            except psycopg2.Error as exc:
                log.warning("caught_up_at not set, will retry: %s", exc)
                self._drop_connection()

    # --- основной цикл ---

    def run(self) -> None:
        ensure_topics(admin_client())
        self.consumer.subscribe([TOPIC_EVENTS])
        log.info("started: group=%s topic=%s batch<=%d/%.0f ms", CONSUMER_GROUP, TOPIC_EVENTS, self.batch_max,
                 self.batch_wait * 1000)
        pending: list[Entry] | None = None
        while not self.stop:
            if pending is None:
                collected = self._collect()
                if not collected:
                    self._heartbeat()
                    continue
                pending = collected
            try:
                committed = self._process(pending)
            except psycopg2.Error as exc:
                log.warning("database error, retrying the batch: %s", exc)
                self._drop_connection()
                self._hold(DB_RETRY_SEC)
                continue
            if committed:
                pending = None
                if self.paused:
                    self.paused = False
                    log.info("stream resumed")
            else:
                if not self.paused:
                    self.paused = True
                    log.info("stream paused by ops.stream_pause, offsets are not committed")
                self._heartbeat()
                self._hold(PAUSE_RECHECK_SEC)
        self.close()

    def close(self) -> None:
        self.consumer.close()
        self._drop_connection()
        log.info("stopped")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ingestor = Ingestor()

    def request_stop(_signum, _frame) -> None:
        ingestor.stop = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    ingestor.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
