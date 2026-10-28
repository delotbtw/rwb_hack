"""Логика GET /api/status: сборка StatusResponse из витрин mart.* (K1-api.md §2, §6.1).

    from app.api.db import connect_ro
    from app.api.status import build_status
    with connect_ro() as conn:
        response = build_status(conn)

Пустые таблицы дают валидный ответ: секции `null`, поток — нули.
Ошибки БД (таймаут, недоступность) не перехватываются: их превращают handlers из errors.py.
"""

from datetime import datetime, timezone

import psycopg2.errors
from psycopg2.extras import RealDictCursor

from app.api.schemas import (
    DqFailure,
    DqStatus,
    EtlRun,
    ReconcileItem,
    ReconcileStatus,
    ReplayRun,
    StatusResponse,
    StreamStatus,
)

MAX_RECONCILE_ITEMS = 50

_STREAM_SQL = """
SELECT last_event_ts, events_total, events_per_sec, lag_events, lag_sec, dlq_count, updated_at
FROM mart.stream_status
ORDER BY id
LIMIT 1
"""

_ETL_COLUMNS = (
    "run_id, ds, kind, status, started_at, finished_at, "
    "dq_passed, dq_total, reconcile_diff, cutoff, note"
)

_LAST_BATCH_SQL = f"""
SELECT {_ETL_COLUMNS}
FROM mart.etl_runs
WHERE kind = 'batch'
ORDER BY started_at DESC, run_id DESC
LIMIT 1
"""

_LAST_PUBLISHED_SQL = f"""
SELECT {_ETL_COLUMNS}
FROM mart.etl_runs
WHERE status = 'published'
ORDER BY started_at DESC, run_id DESC
LIMIT 1
"""

_DQ_FAILED_SQL = """
SELECT check_id, description, expected, actual
FROM mart.dq_result
WHERE NOT passed
ORDER BY check_id
"""

_RECONCILE_SQL = """
WITH last_run AS (
    SELECT max(run_id) AS run_id FROM mart.reconcile_result
)
SELECT r.run_id, r.day, r.check_code, r.batch_value, r.stream_value, r.diff, r.is_ok,
       bool_and(r.is_ok) OVER () AS run_ok
FROM mart.reconcile_result AS r
JOIN last_run AS l ON r.run_id = l.run_id
ORDER BY r.is_ok, r.day NULLS LAST, r.check_code
LIMIT %s
"""

_REPLAY_SQL = """
SELECT replay_id::text AS replay_id, cutoff, events_total, orders_total, expected,
       received_at, caught_up_at
FROM mart.replay_runs
ORDER BY received_at DESC
LIMIT 1
"""


def _fetch_one(cur, sql: str) -> dict | None:
    cur.execute(sql)
    return cur.fetchone()


def _stream(cur) -> StreamStatus:
    row = _fetch_one(cur, _STREAM_SQL)
    return StreamStatus(**row) if row else StreamStatus()


def _etl_run(cur, sql: str) -> EtlRun | None:
    row = _fetch_one(cur, sql)
    return EtlRun(**row) if row else None


def _dq(cur, last_batch: EtlRun | None) -> DqStatus | None:
    if last_batch is None or last_batch.dq_passed is None or last_batch.dq_total is None:
        return None
    cur.execute(_DQ_FAILED_SQL)
    failed = [DqFailure(**row) for row in cur.fetchall()]
    return DqStatus(passed=last_batch.dq_passed, total=last_batch.dq_total, failed=failed)


def _reconcile(cur) -> ReconcileStatus | None:
    cur.execute(_RECONCILE_SQL, (MAX_RECONCILE_ITEMS,))
    rows = cur.fetchall()
    if not rows:
        return None
    items = [
        ReconcileItem(**{k: v for k, v in row.items() if k not in ("run_id", "run_ok")})
        for row in rows
    ]
    return ReconcileStatus(run_id=rows[0]["run_id"], ok=rows[0]["run_ok"], items=items)


def _last_replay(conn, cur) -> ReplayRun | None:
    """До слияния K2 view mart.replay_runs может отсутствовать: тогда секция `null`, не 500."""
    try:
        row = _fetch_one(cur, _REPLAY_SQL)
    except psycopg2.errors.UndefinedTable:
        conn.rollback()
        return None
    return ReplayRun(**row) if row else None


def build_status(conn) -> StatusResponse:
    """Собирает ответ /api/status по соединению `connect_ro()` (только SELECT)."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        stream = _stream(cur)
        last_batch = _etl_run(cur, _LAST_BATCH_SQL)
        last_published = _etl_run(cur, _LAST_PUBLISHED_SQL)
        dq = _dq(cur, last_batch)
        reconcile = _reconcile(cur)
        last_replay = _last_replay(conn, cur)
    return StatusResponse(
        server_time=datetime.now(timezone.utc).replace(tzinfo=None),
        stream=stream,
        last_batch=last_batch,
        last_published=last_published,
        dq=dq,
        reconcile=reconcile,
        last_replay=last_replay,
    )
