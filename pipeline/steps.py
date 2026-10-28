"""Шаги сборки для `make etl` и DAG `capibara_daily`: каждый шаг — отдельная функция.

Строка ops.etl_runs и пауза потока пишутся отдельными autocommit-соединениями:
откат сборки их не затрагивает.

Переменные окружения: PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD, DQ_MODE (strict|report).
"""

import contextlib
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import date

import psycopg2

from pipeline.bundle import ROOT, build as bundle_build

DSN = dict(
    host=os.getenv("PGHOST", "localhost"),
    port=int(os.getenv("PGPORT", "5432")),
    dbname=os.getenv("PGDATABASE", "marketplace"),
    user=os.getenv("PGUSER", "hack"),
    password=os.getenv("PGPASSWORD", "hack"),
)

OPS_FILES = (
    "sql/00_setup/002_persistent_schemas.sql",
    "sql/05_landing/055_ops_tables.sql",
    "sql/05_landing/056_ops_stream_pause.sql",
)
NOTE_MAX = 2000
UTC_NOW = "now() AT TIME ZONE 'utc'"


def step(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


@contextlib.contextmanager
def connect():
    """Соединение с коммитом при успехе, откатом при ошибке и обязательным закрытием."""
    conn = psycopg2.connect(**DSN)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def ensure_ops() -> None:
    """Применяет идемпотентные файлы схем landing/ops до первой сборки."""
    with connect() as conn, conn.cursor() as cur:
        for rel in OPS_FILES:
            cur.execute((ROOT / rel).read_text(encoding="utf-8"))


def open_run(ds: date, kind: str, cutoff: date | None) -> int:
    """Создаёт запуск `running`; незавершённый запуск того же (ds, kind) помечается failed/superseded."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE ops.etl_runs SET status = 'failed', finished_at = {UTC_NOW}, note = 'superseded' "
            "WHERE ds = %s AND kind = %s AND status = 'running'",
            (ds, kind),
        )
        cur.execute(
            "INSERT INTO ops.etl_runs (ds, kind, status, started_at, cutoff) "
            f"VALUES (%s, %s, 'running', {UTC_NOW}, %s) RETURNING run_id",
            (ds, kind, cutoff),
        )
        return cur.fetchone()[0]


def extract(run_id: int, ds: date) -> dict:
    """Манифест data/*.csv (имя, строки, sha256) в output/manifest/<ds>.json; пустой набор — исключение."""
    files = sorted((ROOT / "data").glob("*.csv"))
    if not files:
        raise RuntimeError("extract: в data/ нет CSV-файлов")
    manifest = {"run_id": run_id, "ds": str(ds), "files": []}
    for f in files:
        digest = hashlib.sha256()
        with f.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        with f.open(newline="", encoding="utf-8") as fh:
            rows = sum(1 for _ in csv.reader(fh)) - 1  # минус заголовок; csv учитывает переносы в кавычках
        if rows <= 0:
            raise RuntimeError(f"extract: {f.name} не содержит строк данных")
        manifest["files"].append({"name": f.name, "rows": rows, "sha256": digest.hexdigest()})
    out = ROOT / "output" / "manifest" / f"{ds}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def raw_is_loaded() -> bool:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('raw.orders') IS NOT NULL")
        if not cur.fetchone()[0]:
            return False
        cur.execute("SELECT EXISTS (SELECT 1 FROM raw.orders)")
        return cur.fetchone()[0]


def load_raw(run_id: int, force: bool = False) -> None:
    """Заливает raw из data/*.csv; без force и при непустом raw ничего не делает."""
    if not force and raw_is_loaded():
        step("raw уже загружен — пропускаю (FORCE_RAW=1 чтобы перезалить)")
        return
    step("Загружаю raw из data/*.csv")
    # load_raw.py делает DROP TABLE raw.*, а views stg и DQ-витрины зависят от raw — сносим слои модели,
    # она всё равно пересобирается следующим шагом
    with connect() as conn, conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS stg CASCADE; DROP SCHEMA IF EXISTS mart CASCADE")
    cmd = [
        sys.executable, str(ROOT / "scripts" / "load_raw.py"),
        "--host", DSN["host"], "--port", str(DSN["port"]), "--db", DSN["dbname"],
        "--user", DSN["user"], "--password", DSN["password"],
    ]
    subprocess.run(cmd, check=True)


def pause_stream(run_id: int) -> None:
    """Ставит паузу потока; ждёт COMMIT батчей ingestor, держащих FOR SHARE на строке. Идемпотентно."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE ops.stream_pause SET run_id = %s, paused_at = {UTC_NOW} WHERE id = 1",
            (run_id,),
        )
        if cur.rowcount != 1:
            raise RuntimeError("ops.stream_pause не инициализирована (ensure_ops не вызывался?)")


def _resume(cur) -> None:
    cur.execute("UPDATE ops.stream_pause SET run_id = NULL, paused_at = NULL WHERE id = 1")


def resume_stream() -> None:
    with connect() as conn, conn.cursor() as cur:
        _resume(cur)


def _set_cutoff(cutoff: date | None) -> date | None:
    """Пишет cutoff в ops.build_params, возвращает прежнее значение."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT cutoff FROM ops.build_params WHERE id = 1 FOR UPDATE")
        prev = cur.fetchone()[0]
        cur.execute(
            f"UPDATE ops.build_params SET cutoff = %s, updated_at = {UTC_NOW} WHERE id = 1",
            (cutoff,),
        )
    return prev


def build(run_id: int, cutoff: date | None) -> None:
    """Пауза потока, cutoff в build_params, сборка модели одной транзакцией (транзакцией управляет скрипт)."""
    pause_stream(run_id)
    prev_cutoff = _set_cutoff(cutoff)
    sql = bundle_build().read_text(encoding="utf-8")
    conn = psycopg2.connect(**DSN)
    conn.autocommit = True  # транзакцией управляет сам скрипт (BEGIN ... COMMIT)
    try:
        with conn.cursor() as cur:
            cur.execute("SET capibara.dq_mode = %s", (os.getenv("DQ_MODE", "strict"),))
            t = time.perf_counter()
            try:
                cur.execute(sql)
            except BaseException:
                _set_cutoff(prev_cutoff)  # модель осталась прежней — параметры должны ей соответствовать
                raise
            print(f"модель собрана за {time.perf_counter() - t:.1f} с")
    finally:
        conn.close()  # при ошибке незакрытая транзакция откатывается


def dq(run_id: int) -> tuple[int, int]:
    """Печатает отчёт по слоям и DQ, пишет dq_passed/dq_total; возвращает (passed, total)."""
    with connect() as conn, conn.cursor() as cur:
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
        passed = sum(1 for r in rows if r[1])
        cur.execute(
            "UPDATE ops.etl_runs SET dq_passed = %s, dq_total = %s WHERE run_id = %s",
            (passed, len(rows), run_id),
        )
    print()
    for check_id, ok, expected, actual, desc in rows:
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {check_id:<8} {desc}  (ожидали {expected}, получили {actual})")
    return passed, len(rows)


def publish(run_id: int) -> None:
    """Запуск `published` и снятие паузы потока."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE ops.etl_runs SET status = 'published', finished_at = {UTC_NOW} "
            "WHERE run_id = %s AND status IN ('running', 'success')",
            (run_id,),
        )
        _resume(cur)


def mark_failed(run_id: int | None, ds: date, error) -> None:
    """Запуск `failed` с note=error и снятие паузы; blocked/published не меняет. Без run_id открывает запуск."""
    if run_id is None:
        run_id = open_run(ds, "batch", None)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE ops.etl_runs SET status = 'failed', finished_at = {UTC_NOW}, note = %s "
            "WHERE run_id = %s AND status NOT IN ('blocked', 'published')",
            (str(error)[:NOTE_MAX], run_id),
        )
        _resume(cur)
