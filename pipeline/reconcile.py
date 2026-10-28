"""Сверка batch vs stream (K3 §3.4): снимок агрегатов `core` до сборки и сравнение после неё. Допуск 0.00.

    snapshot_stream(run_id)         — после паузы потока, до build: stream_value по дням и итогу
    reconcile(run_id, strict=True)  — после build: batch_value, is_ok, etl_runs.reconcile_diff

Проверки (`check_code`): orders_count, revenue_sum (Σ price по is_revenue), payments_sum (Σ payment_value).
Строка с `day IS NULL` — итог по всему `core`; по дням — заказы с известным purchased_at.
"""

from decimal import Decimal

import psycopg2
from psycopg2.extras import execute_values

from pipeline.run_etl import DSN

CENT = Decimal("0.01")
ZERO = Decimal("0.00")

# (day, check_code, value); GROUPING(day) = 1 — итоговая строка, заказы без purchased_at входят только в неё
AGG_SQL = """
WITH agg AS (
    SELECT o.purchased_at::date AS day, GROUPING(o.purchased_at::date) AS g,
           'orders_count' AS check_code, COUNT(*)::numeric AS value
    FROM core.fact_order o
    GROUP BY GROUPING SETS ((o.purchased_at::date), ())
    UNION ALL
    SELECT o.purchased_at::date, GROUPING(o.purchased_at::date),
           'revenue_sum', SUM(i.price) FILTER (WHERE s.is_revenue)
    FROM core.fact_order o
    LEFT JOIN core.fact_order_item i ON i.order_id = o.order_id
    LEFT JOIN core.dim_order_status s ON s.order_status = o.order_status
    GROUP BY GROUPING SETS ((o.purchased_at::date), ())
    UNION ALL
    SELECT o.purchased_at::date, GROUPING(o.purchased_at::date),
           'payments_sum', SUM(p.payment_value)
    FROM core.fact_order o
    LEFT JOIN core.fact_order_payment p ON p.order_id = o.order_id
    GROUP BY GROUPING SETS ((o.purchased_at::date), ())
)
SELECT day, check_code, COALESCE(value, 0)
FROM agg
WHERE g = 1 OR day IS NOT NULL
"""


class ReconcileError(RuntimeError):
    """Сверка не сошлась: запуск помечен blocked."""


def _money(value) -> Decimal:
    return Decimal(value).quantize(CENT)


def _aggregates(cur) -> dict[tuple, Decimal]:
    """Агрегаты `core`: {(day | None, check_code): value}; пустого или отсутствующего core — пустой словарь."""
    cur.execute("SELECT to_regclass('core.fact_order') IS NOT NULL")
    if not cur.fetchone()[0]:
        return {}
    cur.execute("SELECT EXISTS (SELECT 1 FROM core.fact_order)")
    if not cur.fetchone()[0]:
        return {}
    cur.execute(AGG_SQL)
    return {(day, code): _money(value) for day, code, value in cur.fetchall()}


def _run(cur, run_id: int) -> tuple:
    cur.execute("SELECT ds, kind, cutoff FROM ops.etl_runs WHERE run_id = %s", (run_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"запуск {run_id} не найден в ops.etl_runs")
    return row


def _append_note(cur, run_id: int, text: str) -> None:
    cur.execute(
        "UPDATE ops.etl_runs SET note = CASE WHEN note IS NULL THEN %s ELSE note || '; ' || %s END WHERE run_id = %s",
        (text, text, run_id),
    )


def snapshot_stream(run_id: int) -> int:
    """Фиксирует агрегаты `core` (то, что накопил поток) как stream_value. Возвращает число записанных строк.

    Только kind=batch и cutoff IS NULL; пустой core — строк нет.
    """
    with psycopg2.connect(**DSN) as conn, conn.cursor() as cur:
        ds, kind, cutoff = _run(cur, run_id)
        cur.execute("DELETE FROM ops.reconcile_result WHERE run_id = %s", (run_id,))  # повтор снимка идемпотентен
        if kind != "batch" or cutoff is not None:
            return 0
        rows = [(run_id, ds, day, code, value) for (day, code), value in _aggregates(cur).items()]
        if rows:
            execute_values(
                cur,
                "INSERT INTO ops.reconcile_result (run_id, ds, day, check_code, stream_value, is_ok) VALUES %s",
                rows,
                template="(%s, %s, %s, %s, %s, false)",
            )
        return len(rows)


def reconcile(run_id: int, strict: bool = True) -> bool:
    """Сверяет снимок с пересобранной моделью. True — всё сошлось (или сверка пропущена).

    Нет снимка → note='reconcile_skipped'. Расхождение при strict → status=blocked, снятие паузы потока и ReconcileError.
    """
    with psycopg2.connect(**DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, day, check_code, stream_value FROM ops.reconcile_result WHERE run_id = %s ORDER BY id",
            (run_id,),
        )
        snapshot = cur.fetchall()
        if not snapshot:
            _append_note(cur, run_id, "reconcile_skipped")
            return True

        batch = _aggregates(cur)
        stream = {(day, code): value for _, day, code, value in snapshot}
        # день, которого нет в снимке, поток видел как 0
        extra = [(k, ZERO) for k in batch if k not in stream]
        if extra:
            ds = _run(cur, run_id)[0]
            execute_values(
                cur,
                "INSERT INTO ops.reconcile_result (run_id, ds, day, check_code, stream_value, is_ok) VALUES %s",
                [(run_id, ds, day, code, value) for (day, code), value in extra],
                template="(%s, %s, %s, %s, %s, false)",
            )
            stream.update(extra)

        execute_values(
            cur,
            """
            UPDATE ops.reconcile_result r
            SET batch_value = v.batch_value, is_ok = (v.batch_value = r.stream_value)
            FROM (VALUES %s) AS v (run_id, day, check_code, batch_value)
            WHERE r.run_id = v.run_id AND r.check_code = v.check_code AND r.day IS NOT DISTINCT FROM v.day
            """,
            [(run_id, day, code, batch.get((day, code), ZERO)) for day, code in stream],
            template="(%s::bigint, %s::date, %s::text, %s::numeric)",
        )

        cur.execute(
            """
            SELECT COALESCE(SUM(ABS(diff)) FILTER (WHERE day IS NULL), 0), COUNT(*) FILTER (WHERE NOT is_ok)
            FROM ops.reconcile_result WHERE run_id = %s
            """,
            (run_id,),
        )
        diff_total, bad = cur.fetchone()
        cur.execute("UPDATE ops.etl_runs SET reconcile_diff = %s WHERE run_id = %s", (diff_total, run_id))
        if not bad:
            return True
        if not strict:
            _append_note(cur, run_id, f"reconcile_mismatch={bad}")
            return False
        cur.execute(
            "UPDATE ops.etl_runs SET status = 'blocked', finished_at = (now() AT TIME ZONE 'utc') WHERE run_id = %s",
            (run_id,),
        )
        _append_note(cur, run_id, f"reconcile_mismatch={bad}")

    from pipeline.steps import resume_stream  # пауза снимается на любой исход (K3 §3.3 п.3)

    resume_stream()
    raise ReconcileError(f"сверка не сошлась: {bad} расхождений, Σ|diff| итогов = {diff_total}")
