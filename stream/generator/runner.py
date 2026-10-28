"""CLI генератора: python -m stream.generator [--cutoff D] [--duration S] [--max-gap G] [--noise] (K2 §4)."""

import argparse
import logging
import sys
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from confluent_kafka import Producer

from stream.common import (
    DATA_DIR,
    EXPECTED_FULL,
    REPLAY_KEY,
    TOPIC_EVENTS,
    TYPE_REPLAY,
    admin_client,
    dumps,
    ensure_topics,
    kafka_conf,
    make_envelope,
)
from stream.generator.dataset import Event, Replay, build_replay, envelope
from stream.generator.noise import add_noise
from stream.generator.schedule import schedule

log = logging.getLogger("stream.generator")

PROGRESS_EVERY = 5000


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m stream.generator", description=__doc__)
    parser.add_argument("--cutoff", "--from", dest="cutoff", type=date.fromisoformat,
                        help="заказы с purchased_at >= даты (YYYY-MM-DD); без параметра - весь датасет")
    parser.add_argument("--duration", type=float, help="длительность реплея, секунд; без параметра 1 день = 1 с")
    parser.add_argument("--max-gap", type=float, default=0.2, help="максимальная пауза между событиями, секунд")
    parser.add_argument("--noise", action="store_true", help="~1%% дублей и перестановок событий разных заказов")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="каталог с olist_*_dataset.csv")
    args = parser.parse_args(argv)
    if args.duration is not None and args.duration <= 0:
        parser.error("--duration must be positive")
    if args.max_gap <= 0:
        parser.error("--max-gap must be positive")
    return args


class Sender:
    def __init__(self) -> None:
        self.producer = Producer(kafka_conf(**{"client.id": "capibara-generator", "enable.idempotence": True,
                                               "linger.ms": 5}))
        self.failed = 0

    def _delivered(self, err, _msg) -> None:
        if err is not None:
            self.failed += 1
            log.error("delivery failed: %s", err)

    def send(self, key: str, message: dict) -> None:
        while True:
            try:
                self.producer.produce(TOPIC_EVENTS, key=key, value=dumps(message), on_delivery=self._delivered)
                break
            except BufferError:
                self.producer.poll(0.1)
        self.producer.poll(0)

    def flush(self) -> None:
        self.producer.flush()
        if self.failed:
            raise RuntimeError(f"{self.failed} messages were not delivered")


def replay_event(replay_id: str, cutoff: date | None, events_total: int, orders_total: int,
                 last_ts: datetime) -> dict:
    payload = {
        "replay_id": replay_id,
        "cutoff": cutoff.isoformat() if cutoff else None,
        "events_total": events_total,
        "orders_total": orders_total,
        "expected": EXPECTED_FULL,
    }
    return make_envelope(TYPE_REPLAY, None, last_ts, payload, replay_id)


def play(sender: Sender, messages: list[Event], pauses: list[float]) -> None:
    started = time.monotonic()
    due = 0.0
    for sent, (event, pause) in enumerate(zip(messages, pauses), start=1):
        due += pause
        delay = started + due - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        sender.send(event.order_id, envelope(event))
        if sent % PROGRESS_EVERY == 0:
            log.info("sent %d/%d events, %.1f s", sent, len(messages), time.monotonic() - started)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    args = parse_args(argv)

    replay: Replay = build_replay(args.data_dir, args.cutoff)
    messages = add_noise(replay.events) if args.noise else replay.events
    pauses = schedule([event.sort_ts for event in messages], args.duration, args.max_gap)
    log.info("orders=%d events=%d messages=%d planned=%.1f s",
             replay.orders_total, len(replay.events), len(messages), sum(pauses))

    ensure_topics(admin_client())
    sender = Sender()
    play(sender, messages, pauses)
    sender.flush()

    last_ts = max((event.event_ts for event in replay.events),
                  default=datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0))
    done = replay_event(str(uuid.uuid4()), args.cutoff, len(replay.events), replay.orders_total, last_ts)
    sender.send(REPLAY_KEY, done)
    sender.flush()
    log.info("replay.completed sent: replay_id=%s", done["payload"]["replay_id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
