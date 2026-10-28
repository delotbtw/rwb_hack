"""Графики по продажам. Шаблон для переноса графиков из ноутбука."""

from app.charts._style import ACCENT, MONEY, MUTED, new_figure
from app.db import query_df
from app.registry import chart


@chart(
    "revenue_by_month",
    "Выручка по месяцам",
    "Выручка (сумма price по вручённым заказам) по месяцу оформления; 2016-11 — месяц без заказов, он показан нулём.",
    order=10,
)
def revenue_by_month(conn):
    df = query_df(conn, """
        SELECT month, orders, revenue
        FROM mart.v_sales_month
        WHERE month BETWEEN DATE '2016-09-01' AND DATE '2018-08-01'
        ORDER BY month
    """)
    fig, ax = new_figure()
    labels = df["month"].map(lambda d: d.strftime("%Y-%m"))
    ax.bar(labels, df["revenue"].astype(float), color=ACCENT)
    ax.yaxis.set_major_formatter(MONEY)
    ax.set_ylabel("выручка, BRL")
    ax.tick_params(axis="x", rotation=60, labelsize=8)

    ax2 = ax.twinx()
    ax2.plot(labels, df["orders"], color=MUTED, marker="o", markersize=3)
    ax2.set_ylabel("заказов")
    ax2.spines[["top"]].set_visible(False)
    fig.tight_layout()
    return fig
