"""ETL одним запуском: raw (если пусто) → bundle → stg/core/mart одной транзакцией → отчёт DQ
→ импорт графиков из ноутбуков (notebooks/*.ipynb, *.ipynb в корне).

    python -m pipeline.run_etl

Переменные окружения:
    PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD — подключение (по умолчанию localhost, hack/hack)
    FORCE_RAW=1    — перезалить raw, даже если там уже есть данные
    DQ_MODE=report — не откатывать сборку при упавших проверках (по умолчанию strict)
    EXECUTE=1      — перевыполнить ноутбуки против базы перед импортом графиков
"""

import os
import subprocess
import sys
import time

import psycopg2

from pipeline.bundle import ROOT, build
from pipeline.import_notebook import main as import_notebooks

DSN = dict(
    host=os.getenv("PGHOST", "localhost"),
    port=int(os.getenv("PGPORT", "5432")),
    dbname=os.getenv("PGDATABASE", "marketplace"),
    user=os.getenv("PGUSER", "hack"),
    password=os.getenv("PGPASSWORD", "hack"),
)


def step(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


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


def raw_is_loaded() -> bool:
    with psycopg2.connect(**DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('raw.orders') IS NOT NULL")
        if not cur.fetchone()[0]:
            return False
        cur.execute("SELECT EXISTS (SELECT 1 FROM raw.orders)")
        return cur.fetchone()[0]


def load_raw() -> None:
    # load_raw.py делает DROP TABLE raw.*, а views stg зависят от raw — сносим их, модель всё равно пересоберётся
    with psycopg2.connect(**DSN) as conn, conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS stg CASCADE")
    cmd = [
        sys.executable, str(ROOT / "scripts" / "load_raw.py"),
        "--host", DSN["host"], "--port", str(DSN["port"]), "--db", DSN["dbname"],
        "--user", DSN["user"], "--password", DSN["password"],
    ]
    subprocess.run(cmd, check=True)


def build_model() -> None:
    sql = build().read_text(encoding="utf-8")
    conn = psycopg2.connect(**DSN)
    conn.autocommit = True  # транзакцией управляет сам скрипт (BEGIN ... COMMIT)
    try:
        with conn.cursor() as cur:
            cur.execute("SET capibara.dq_mode = %s", (os.getenv("DQ_MODE", "strict"),))
            t = time.perf_counter()
            cur.execute(sql)
            print(f"модель собрана за {time.perf_counter() - t:.1f} с")
    finally:
        conn.close()  # при ошибке незакрытая транзакция откатывается


def report() -> bool:
    with psycopg2.connect(**DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT 'stg'  AS layer, count(*) FROM information_schema.views  WHERE table_schema = 'stg'
            UNION ALL
            SELECT 'core', count(*) FROM information_schema.tables WHERE table_schema = 'core'
            UNION ALL
            SELECT 'mart', count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                           WHERE n.nspname = 'mart' AND c.relkind IN ('r', 'v', 'm')
        """)
        for layer, n in cur.fetchall():
            print(f"  {layer:<5} объектов: {n}")
        cur.execute("SELECT check_id, passed, expected, actual, description FROM mart.dq_result ORDER BY check_id")
        rows = cur.fetchall()
    print()
    for check_id, passed, expected, actual, desc in rows:
        mark = "PASS" if passed else "FAIL"
        print(f"  [{mark}] {check_id:<8} {desc}  (ожидали {expected}, получили {actual})")
    return all(r[1] for r in rows)


def main() -> int:
    step(f"Жду базу {DSN['host']}:{DSN['port']}")
    wait_for_db()

    if os.getenv("FORCE_RAW") == "1" or not raw_is_loaded():
        step("Загружаю raw из data/*.csv")
        load_raw()
    else:
        step("raw уже загружен — пропускаю (FORCE_RAW=1 чтобы перезалить)")

    step("Собираю модель: raw → stg → core → mart (+DQ)")
    try:
        build_model()
    except psycopg2.Error as e:
        print(f"\nСБОРКА ОТКАЧЕНА: {e.pgerror or e}", file=sys.stderr)
        return 1

    step("Результат")
    ok = report()
    print("\nГотово." if ok else "\nЕсть упавшие проверки (DQ_MODE=report).")

    step("Импорт графиков из ноутбуков")
    try:
        import_notebooks([])
    except Exception as e:  # кривой ноутбук не должен ронять сборку модели
        print(f"  ! импорт ноутбуков не удался: {type(e).__name__}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
