"""Сверка core после реплея с контрольными цифрами (K2 §8 A-5, A-15).

python -m stream.verify [--replay-id UUID]: берёт последний догнанный реплей из mart.replay_runs
и сравнивает его expected с показателями модели (mart.v_kpi). Только чтение; код выхода 0 - всё
сошлось, 1 - расхождение или реплей не найден/не догнан. Для реплея с --cutoff expected - итоги
полного датасета, поэтому сверка имеет смысл только для полного реплея.
"""

import argparse
import sys
from decimal import Decimal

from stream.common import connect_pg

_RUN = """
SELECT replay_id, expected, caught_up_at
FROM mart.replay_runs
WHERE (%(replay_id)s::uuid IS NULL AND caught_up_at IS NOT NULL) OR replay_id = %(replay_id)s::uuid
ORDER BY received_at DESC
LIMIT 1
"""

_ACTUAL = """
SELECT (SELECT COUNT(*) FROM mart.order_summary) AS orders_total,
       revenue, avg_check, customers, repeat_pct
FROM mart.v_kpi
"""

_KEYS = ("orders_total", "revenue", "avg_check", "customers", "repeat_pct")


def compare(expected: dict, actual: dict) -> list[tuple[str, str, str, bool]]:
    """Строки (метрика, ожидается, получено, совпало); числа сравниваются как Decimal."""
    rows = []
    for key in _KEYS:
        want, got = expected.get(key), actual.get(key)
        try:
            same = Decimal(str(want)) == Decimal(str(got))
        except Exception:  # noqa: BLE001 - нечисловое значение = расхождение
            same = False
        rows.append((key, str(want), str(got), same))
    return rows


def run(replay_id: str | None = None) -> int:
    conn = connect_pg()
    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor() as cur:
            cur.execute(_RUN, {"replay_id": replay_id})
            run_row = cur.fetchone()
            if run_row is None:
                print("FAIL: нет реплея" + ("" if replay_id else " с caught_up_at"))
                return 1
            run_id, expected, caught_up_at = run_row
            if caught_up_at is None:
                print(f"FAIL: реплей {run_id} ещё не догнан (caught_up_at IS NULL)")
                return 1
            cur.execute(_ACTUAL)
            columns = [d[0] for d in cur.description]
            actual = dict(zip(columns, cur.fetchone()))
    finally:
        conn.close()

    rows = compare(expected, actual)
    print(f"replay {run_id}, caught_up_at {caught_up_at}")
    for key, want, got, same in rows:
        print(f"{'ok  ' if same else 'FAIL'} {key}: expected {want}, actual {got}")
    return 0 if all(row[3] for row in rows) else 1


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m stream.verify", description=__doc__.splitlines()[0])
    parser.add_argument("--replay-id", help="UUID реплея (по умолчанию последний догнанный)")
    sys.exit(run(parser.parse_args().replay_id))


if __name__ == "__main__":
    main()
