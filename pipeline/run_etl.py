"""ETL одним запуском: raw (если пусто) → bundle → stg/core/mart одной транзакцией → отчёт DQ
→ импорт графиков из ноутбуков (notebooks/*.ipynb, *.ipynb в корне).

    python -m pipeline.run_etl

Переменные окружения:
    PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD — подключение (по умолчанию localhost, hack/hack)
    FORCE_RAW=1    — перезалить raw, даже если там уже есть данные
    DQ_MODE=report — не откатывать сборку при упавших проверках (по умолчанию strict)
    CUTOFF=YYYY-MM-DD — собрать модель только из заказов до этой даты (пусто = полная сборка)
    EXECUTE=1      — перевыполнить ноутбуки против базы перед импортом графиков
"""

import os
import sys
import time
from datetime import date

import psycopg2

from pipeline import steps
from pipeline.import_notebook import main as import_notebooks
from pipeline.steps import DSN, step


def wait_for_db(timeout: int = 60) -> None:
    deadline = time.time() + timeout
    while True:
        try:
            psycopg2.connect(**DSN, connect_timeout=3).close()
            return
        except psycopg2.OperationalError:
            if time.time() > deadline:
                raise
            time.sleep(1)


def main() -> int:
    step(f"Жду базу {DSN['host']}:{DSN['port']}")
    wait_for_db()

    cutoff_raw = os.getenv("CUTOFF", "").strip()
    cutoff = date.fromisoformat(cutoff_raw) if cutoff_raw else None
    steps.ensure_ops()
    with steps.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT CURRENT_DATE")
        ds = cur.fetchone()[0]
    run_id = steps.open_run(ds, "batch", cutoff)

    try:
        steps.load_raw(run_id, force=os.getenv("FORCE_RAW") == "1")

        step("Собираю модель: raw → stg → core → mart (+DQ)")
        try:
            steps.build(run_id, cutoff)
        except psycopg2.Error as e:
            print(f"\nСБОРКА ОТКАЧЕНА: {e.pgerror or e}", file=sys.stderr)
            steps.mark_failed(run_id, ds, e.pgerror or e)
            return 1

        step("Результат")
        passed, total = steps.dq(run_id)
        steps.publish(run_id)
    except BaseException as e:
        steps.mark_failed(run_id, ds, f"{type(e).__name__}: {e}")
        raise
    print("\nГотово." if passed == total else "\nЕсть упавшие проверки (DQ_MODE=report).")

    step("Импорт графиков из ноутбуков")
    try:
        import_notebooks([])
    except Exception as e:  # кривой ноутбук не должен ронять сборку модели
        print(f"  ! импорт ноутбуков не удался: {type(e).__name__}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
