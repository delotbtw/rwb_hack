"""Общее для генератора, ingestor и сброса брокера (K2, контракты K0 §4.1).

Топики и группа, ранги статусов, конверт события с детерминированным event_id,
валидаторы JSON Schema из contracts/events, клиенты Kafka и Postgres.
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
CONTRACTS_DIR = REPO_ROOT / "contracts" / "events"

TOPIC_EVENTS = "orders.events"
TOPIC_DLQ = "orders.dlq"
EVENTS_PARTITIONS = 3
DLQ_PARTITIONS = 1
CONSUMER_GROUP = "capibara-ingestor"
REPLAY_KEY = "replay"
SCHEMA_VERSION = 1

TYPE_CREATED = "order.created"
TYPE_PAYMENT = "payment.captured"
TYPE_STATUS = "order.status_changed"
TYPE_REVIEW = "review.posted"
TYPE_REPLAY = "replay.completed"
TYPE_CATEGORY = "product.category_changed"
TYPE_ADDRESS = "customer.address_changed"
EVENT_TYPES = (TYPE_CREATED, TYPE_PAYMENT, TYPE_STATUS, TYPE_REVIEW, TYPE_REPLAY, TYPE_CATEGORY, TYPE_ADDRESS)

# Ранги статусов (K2 §4 п.2): created < approved < invoiced < processing < shipped < delivered < unavailable = canceled.
# unknown приравнен к терминальным: статус не распознан, дальше его не повышают.
STATUS_RANK = {
    "created": 0,
    "approved": 1,
    "invoiced": 2,
    "processing": 3,
    "shipped": 4,
    "delivered": 5,
    "unavailable": 6,
    "canceled": 6,
    "unknown": 6,
}

# Итоги полного датасета (контрольные цифры docs/tasks.md); едут в replay.completed.expected при любом cutoff.
EXPECTED_FULL = {
    "orders_total": 99441,
    "revenue": "13221498.11",
    "avg_check": "159.88",
    "customers": 96096,
    "repeat_pct": "3.12",
}

# Неймспейс uuid5 для event_id: фиксирован, иначе повтор реплея даст другие id.
EVENT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://capibara.local/contracts/events")


def bootstrap_servers() -> str:
    return os.getenv("KAFKA_BOOTSTRAP", "localhost:19092")


def event_id(event_type: str, order_id: str | None, discriminator: str = "") -> str:
    """uuid5 от 'type:order_id:discriminator' (K0 §4.1)."""
    return str(uuid.uuid5(EVENT_NAMESPACE, f"{event_type}:{order_id or ''}:{discriminator}"))


def format_naive(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def make_envelope(
    event_type: str,
    order_id: str | None,
    event_ts: datetime,
    payload: dict,
    discriminator: str = "",
    produced_at: str | None = None,
) -> dict:
    return {
        "event_id": event_id(event_type, order_id, discriminator),
        "type": event_type,
        "order_id": order_id,
        "event_ts": format_naive(event_ts),
        "produced_at": produced_at or utc_now_iso(),
        "schema_version": SCHEMA_VERSION,
        "payload": payload,
    }


def dumps(message: dict) -> bytes:
    return json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def load_validator(name: str = "envelope"):
    """Валидатор JSON Schema 2020-12 для contracts/events/<name>.json; $ref между файлами разрешаются по $id."""
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    schemas = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in CONTRACTS_DIR.glob("*.json")}
    registry = Registry().with_resources(
        [(schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()]
    )
    return Draft202012Validator(schemas[name], registry=registry)


def kafka_conf(**extra) -> dict:
    return {"bootstrap.servers": bootstrap_servers(), **extra}


def admin_client():
    from confluent_kafka.admin import AdminClient

    return AdminClient(kafka_conf())


def ensure_topics(admin, attempts: int = 15) -> None:
    """Идемпотентно создаёт orders.events и orders.dlq; повторяет, пока брокер дозавершает удаление старых."""
    from confluent_kafka import KafkaError
    from confluent_kafka.admin import NewTopic

    wanted = {TOPIC_EVENTS: EVENTS_PARTITIONS, TOPIC_DLQ: DLQ_PARTITIONS}
    for attempt in range(attempts):
        existing = admin.list_topics(timeout=10).topics
        missing = [NewTopic(name, num_partitions=parts, replication_factor=1)
                   for name, parts in wanted.items() if name not in existing]
        if not missing:
            return
        failed = []
        for name, future in admin.create_topics(missing).items():
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001 - KafkaException несёт код в args[0]
                error = exc.args[0] if exc.args else None
                if getattr(error, "code", lambda: None)() != KafkaError.TOPIC_ALREADY_EXISTS:
                    failed.append((name, exc))
        if not failed:
            return
        if attempt == attempts - 1:
            raise RuntimeError(f"cannot create topics: {failed}")
        time.sleep(2)


def connect_pg():
    """Соединение с Postgres по PG* (по умолчанию как app/db.py); ingestor задаёт PGUSER=ingestor."""
    import psycopg2

    return psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "marketplace"),
        user=os.getenv("PGUSER", "hack"),
        password=os.getenv("PGPASSWORD", "hack"),
    )
