"""Подключение к БД под ролью app_ro для API (только чтение).

    from app.api.db import connect_ro
    with connect_ro() as conn:
        ...
"""

import os
from contextlib import contextmanager

import psycopg2

STATEMENT_TIMEOUT_MS = 5000


@contextmanager
def connect_ro():
    conn = psycopg2.connect(
        host=os.getenv("API_PGHOST", "localhost"),
        port=int(os.getenv("API_PGPORT", "5432")),
        dbname=os.getenv("API_PGDATABASE", "marketplace"),
        user=os.getenv("API_PGUSER", "app_ro"),
        password=os.getenv("API_PGPASSWORD", "app_ro"),
        options=(
            f"-c statement_timeout={STATEMENT_TIMEOUT_MS} "
            "-c default_transaction_read_only=on"
        ),
    )
    try:
        yield conn
    finally:
        conn.close()
