"""Подключение к базе и чтение витрин в DataFrame.

Используется и приложением, и ноутбуком:
    from app.db import connect, query_df
    with connect() as conn:
        df = query_df(conn, "SELECT * FROM mart.v_sales_month")
"""

import os
from contextlib import contextmanager

import pandas as pd
import psycopg2


@contextmanager
def connect():
    conn = psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "marketplace"),
        user=os.getenv("PGUSER", "hack"),
        password=os.getenv("PGPASSWORD", "hack"),
    )
    try:
        yield conn
    finally:
        conn.close()


def query_df(conn, sql: str, params=None) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


def build_version(conn) -> str:
    """Момент последней сборки модели — ключ кэша PNG."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('mart.build_info') IS NOT NULL")
        if not cur.fetchone()[0]:
            return "no-build"
        cur.execute("SELECT max(built_at)::text FROM mart.build_info")
        return cur.fetchone()[0] or "no-build"
