"""Собирает sql/**/*.sql в один скрипт dist/build_model.sql (DL-1).

Порядок файлов = порядок их путей (префиксы NNN_), весь скрипт — одна транзакция.
Результат запускается и через psql, и через pipeline.run_etl.

    python -m pipeline.bundle
"""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"
OUT = ROOT / "dist" / "build_model.sql"


def build() -> pathlib.Path:
    files = sorted(SQL_DIR.rglob("*.sql"))
    if not files:
        raise SystemExit(f"Нет SQL-файлов в {SQL_DIR}")

    parts = [
        "-- Сгенерировано pipeline/bundle.py из sql/**. Не редактировать руками.",
        "-- Запуск: psql -v ON_ERROR_STOP=1 -f dist/build_model.sql",
        "BEGIN;",
    ]
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        parts.append(f"\n-- >>> {rel}\n{f.read_text(encoding='utf-8').strip()}\n-- <<< {rel}")
    parts.append("\nCOMMIT;\n")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(parts), encoding="utf-8")
    return OUT


if __name__ == "__main__":
    out = build()
    print(f"bundle: {out.relative_to(ROOT)} ({out.stat().st_size} байт)")
