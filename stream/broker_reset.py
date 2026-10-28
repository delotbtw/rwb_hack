"""Сброс брокера для повторного реплея: python -m stream.broker_reset (K2 §5, ASSUMPTION-K2-5).

Удаляет топики orders.events, orders.dlq и consumer group capibara-ingestor.
Ingestor должен быть остановлен; топики пересоздаёт генератор.
"""

import logging
import sys
import time

from confluent_kafka import KafkaError

from stream.common import CONSUMER_GROUP, TOPIC_DLQ, TOPIC_EVENTS, admin_client

log = logging.getLogger("stream.broker_reset")

TOPICS = [TOPIC_EVENTS, TOPIC_DLQ]
WAIT_SECONDS = 30


def _code(exc: Exception):
    error = exc.args[0] if exc.args else None
    return error.code() if hasattr(error, "code") else None


def delete_topics(admin) -> None:
    for name, future in admin.delete_topics(TOPICS, operation_timeout=WAIT_SECONDS).items():
        try:
            future.result()
            log.info("topic %s deleted", name)
        except Exception as exc:
            if _code(exc) != KafkaError.UNKNOWN_TOPIC_OR_PART:
                raise
            log.info("topic %s absent", name)


def delete_group(admin) -> None:
    for name, future in admin.delete_consumer_groups([CONSUMER_GROUP]).items():
        try:
            future.result()
            log.info("group %s deleted", name)
        except Exception as exc:
            if _code(exc) != KafkaError.GROUP_ID_NOT_FOUND:
                raise
            log.info("group %s absent", name)


def wait_topics_gone(admin) -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if not set(TOPICS) & set(admin.list_topics(timeout=10).topics):
            return
        time.sleep(1)
    raise TimeoutError(f"topics {TOPICS} still exist after {WAIT_SECONDS} s")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    admin = admin_client()
    delete_group(admin)
    delete_topics(admin)
    wait_topics_gone(admin)
    log.info("broker reset done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
