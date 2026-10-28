"""Графики качества данных: самопроверки модели, читают mart.* (DQ-витрины)."""

import numpy as np

from app.charts._style import ACCENT, MUTED, WARN, new_figure
from app.db import query_df
from app.registry import chart

SECTION = "Качество данных"


@chart(
    "layer_rows",
    "Строки: raw → модель",
    "Каждая таблица источника перенесена в модель без потерь: число строк в raw и в core совпадает.",
    order=10,
    section=SECTION,
)
def layer_rows(conn):
    df = query_df(conn, "SELECT source_table, raw_rows, model_rows FROM mart.v_layer_rows ORDER BY raw_rows")
    y = np.arange(len(df))
    fig, ax = new_figure(10, 5)
    ax.barh(y - 0.18, df["raw_rows"], height=0.34, color=MUTED, label="raw")
    ax.barh(y + 0.18, df["model_rows"], height=0.34, color=ACCENT, label="модель")
    ax.set_yticks(y, df["source_table"])
    for i, v in enumerate(df["model_rows"]):
        ax.text(v, i + 0.18, f" {v:,}".replace(",", " "), va="center", fontsize=8)
    ax.set_xlim(0, df["raw_rows"].max() * 1.18)
    ax.grid(axis="y", alpha=0)
    ax.grid(axis="x", alpha=0.3)
    ax.legend(frameon=False, loc="lower right")
    fig.tight_layout()
    return fig


@chart(
    "raw_missingness",
    "Где в источнике пропуски",
    "Пропуски сохраняются как есть: пустой текст отзыва — норма, пустая категория получает явную метку unknown.",
    order=20,
    section=SECTION,
)
def raw_missingness(conn):
    df = query_df(conn, """
        SELECT source_table || '.' || column_name AS col, missing_pct
        FROM mart.v_raw_missingness WHERE missing > 0
        ORDER BY missing_pct DESC LIMIT 14
    """).iloc[::-1]
    fig, ax = new_figure(10, 5.5)
    ax.barh(df["col"], df["missing_pct"].astype(float), color=MUTED)
    ax.set_xlabel("доля пропусков, %")
    ax.set_xlim(0, 100)
    ax.tick_params(axis="y", labelsize=8)
    ax.grid(axis="y", alpha=0)
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    return fig


@chart(
    "payment_reconciliation",
    "Сверка оплаты с суммой заказа",
    "Отсутствие позиций или оплаты отделено от ненулевой разницы сумм; причины расхождений в данных не установлены.",
    order=30,
    section=SECTION,
)
def payment_reconciliation(conn):
    df = query_df(conn, """
        SELECT reconciliation, COUNT(*) AS orders
        FROM mart.order_summary GROUP BY 1 ORDER BY 2
    """)
    fig, ax = new_figure(9, 4.2)
    colors = [ACCENT if s == "Совпадает" else WARN for s in df["reconciliation"]]
    ax.barh(df["reconciliation"], df["orders"], color=colors)
    for y, n in enumerate(df["orders"]):
        ax.text(n, y, f" {n:,}".replace(",", " "), va="center")
    ax.set_xscale("log")
    ax.set_xlabel("заказов (логарифмическая шкала)")
    ax.grid(axis="y", alpha=0)
    fig.tight_layout()
    return fig
