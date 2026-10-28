"""Демо-режим «история + хвост»: модель собирается только из заказов до cutoff, хвост доигрывает поток.

    python -m pipeline.demo prep    # модель до cutoff, поток не трогаем
    python -m pipeline.demo reset   # prep + очистка landing.events, ops.replay_runs и ops.stream_status

Брокер (топики, consumer group) сбрасывает `make stream-reset` до `reset` (см. make/batch.mk, demo-reset).

Переменные окружения: PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD, CUTOFF=YYYY-MM-DD (по умолчанию 2018-08-01),
DQ_MODE (strict|report), FORCE_RAW=1.
"""

import os
import sys
from datetime import date

import psycopg2

from pipeline import steps
from pipeline.run_etl import wait_for_db
from pipeline.steps import DSN, UTC_NOW, step

DEFAULT_CUTOFF = "2018-08-01"
KIND = "demo"


def _today() -> date:
    with steps.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT CURRENT_DATE")
        return cur.fetchone()[0]


def _prep(ds: date, cutoff: date) -> int:
    """Собирает модель до cutoff; возвращает run_id опубликованного запуска. Сбой сборки → psycopg2.Error."""
    steps.ensure_ops()
    run_id = steps.open_run(ds, KIND, cutoff)
    try:
        steps.load_raw(run_id, force=os.getenv("FORCE_RAW") == "1")
        step(f"Собираю модель до cutoff {cutoff}: raw → stg → core → mart (+DQ)")
        steps.build(run_id, cutoff)
        step("Результат")
        steps.dq(run_id)
        steps.publish(run_id)
    except BaseException as e:
        steps.mark_failed(run_id, ds, f"{type(e).__name__}: {e}")
        raise
    return run_id


def prep(cutoff: date) -> int:
    """Демо-подготовка: ensure_ops, open_run(demo), load_raw, build(cutoff), dq, publish."""
    return _prep(_today(), cutoff)


def reset(cutoff: date) -> int:
    """prep + под паузой потока очистка landing.events, ops.replay_runs и обнуление ops.stream_status."""
    run_id = prep(cutoff)
    step("Сбрасываю landing, ops.replay_runs и ops.stream_status")
    steps.pause_stream(run_id)
    try:
        with steps.connect() as conn, conn.cursor() as cur:
            cur.execute("TRUNCATE landing.events, ops.replay_runs")
            cur.execute(
                "UPDATE ops.stream_status SET last_event_ts = NULL, events_total = 0, events_per_sec = 0, "
                f"lag_events = 0, lag_sec = 0, dlq_count = 0, updated_at = {UTC_NOW} WHERE id = 1"
            )
    finally:
        steps.resume_stream()
    return run_id


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("prep", "reset"):
        print("usage: python -m pipeline.demo prep|reset", file=sys.stderr)
        return 2
    cutoff = date.fromisoformat(os.getenv("CUTOFF", "").strip() or DEFAULT_CUTOFF)

    step(f"Жду базу {DSN['host']}:{DSN['port']}")
    wait_for_db()
    try:
        {"prep": prep, "reset": reset}[argv[0]](cutoff)
    except psycopg2.Error as e:
        print(f"\nСБОРКА ОТКАЧЕНА: {e.pgerror or e}", file=sys.stderr)
        return 1
    print(f"\nГотово: демо-режим {argv[0]}, cutoff {cutoff}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
