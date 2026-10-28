"""Графики по продажам: читают только mart.*."""

import pandas as pd

from app.charts._style import ACCENT, MONEY, MUTED, WARN, new_figure
from app.db import query_df
from app.registry import chart


@chart(
    "revenue_by_month",
    "Выручка по месяцам",
    "Выручка (сумма price по вручённым заказам) по месяцу оформления; 2016-11 — месяц без заказов, он показан нулём.",
    order=10,
)
def revenue_by_month(conn):
    df = query_df(conn, "SELECT month, orders, revenue FROM mart.q01_revenue_by_month")
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


@chart(
    "top_sellers",
    "Топ-10 продавцов по выручке",
    "Выручка продавца считается только по его позициям в доставленных заказах, а не по всему чеку заказа.",
    order=20,
)
def top_sellers(conn):
    df = query_df(conn, "SELECT seller_id, city, state, revenue FROM mart.q02_top_sellers").iloc[::-1]
    fig, ax = new_figure(10, 5)
    labels = df["city"] + "/" + df["state"] + " · " + df["seller_id"].str[-6:]
    vals = df["revenue"].astype(float)
    ax.barh(labels, vals, color=ACCENT)
    for y, v in enumerate(vals):
        ax.text(v, y, f" {v / 1e3:.1f} тыс", va="center", fontsize=8)
    ax.xaxis.set_major_formatter(MONEY)
    ax.set_xlim(0, vals.max() * 1.15)
    ax.grid(axis="y", alpha=0)
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    return fig


@chart(
    "revenue_by_category",
    "Выручка по категориям",
    "Топ-9 категорий и «Неизвестная категория» отдельно; остальные объединены только на графике, сумма равна общей выручке.",
    order=30,
)
def revenue_by_category(conn):
    df = query_df(conn, "SELECT label, is_unknown, revenue FROM mart.v_category_sales ORDER BY revenue DESC")
    top = pd.concat([df.head(9), df[df["is_unknown"] & ~df.index.isin(df.head(9).index)]])
    rest = df["revenue"].sum() - top["revenue"].sum()
    plot = pd.concat([top, pd.DataFrame([{"label": "Остальные категории", "is_unknown": False, "revenue": rest}])])
    plot = plot.sort_values("revenue")
    fig, ax = new_figure(10, 5.5)
    colors = [WARN if u else ACCENT for u in plot["is_unknown"]]
    ax.barh(plot["label"].str.replace("_", " "), plot["revenue"].astype(float), color=colors)
    ax.xaxis.set_major_formatter(MONEY)
    ax.grid(axis="y", alpha=0)
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    return fig


@chart(
    "seller_concentration",
    "Концентрация выручки по продавцам",
    "Накопленная доля выручки по продавцам от крупных к мелким; описывает вклад продавца, а не его качество.",
    order=40,
)
def seller_concentration(conn):
    df = query_df(conn, "SELECT revenue FROM mart.v_seller_sales ORDER BY revenue DESC")
    rev = df["revenue"].astype(float)
    x = (rev.index + 1) / len(rev) * 100
    y = rev.cumsum() / rev.sum() * 100
    fig, ax = new_figure(9, 5)
    ax.plot(x, y, color=ACCENT)
    ax.plot([0, 100], [0, 100], color=MUTED, linestyle="--", label="равномерный вклад")
    top20 = y[x <= 20].iloc[-1]
    ax.annotate(f"20% продавцов = {top20:.0f}% выручки", xy=(20, top20), xytext=(35, top20 - 20),
                arrowprops={"arrowstyle": "->", "color": MUTED})
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 101)
    ax.set_xlabel("доля продавцов, %")
    ax.set_ylabel("накопленная доля выручки, %")
    ax.legend(frameon=False)
    fig.tight_layout()
    return fig
