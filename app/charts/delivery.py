"""Графики по доставке и отзывам: читают только mart.*."""

from app.charts._style import ACCENT, MUTED, WARN, new_figure
from app.db import query_df
from app.registry import chart

SECTION = "Доставка и отзывы"


@chart(
    "delivery_days",
    "Срок доставки",
    "Дни от покупки до вручения по валидным доставленным заказам; хвост не обрезан, 8 заказов без даты вручения не участвуют.",
    order=10,
    section=SECTION,
)
def delivery_days(conn):
    df = query_df(conn, "SELECT delivery_days FROM mart.order_summary WHERE is_valid_delivery")
    days = df["delivery_days"].astype(float)
    median, p90 = days.median(), days.quantile(0.9)
    fig, ax = new_figure()
    ax.hist(days, bins=60, color=ACCENT)
    ax.axvline(median, color=WARN, label=f"медиана {median:.1f} дн")
    ax.axvline(p90, color=MUTED, linestyle="--", label=f"P90 {p90:.1f} дн")
    ax.set_xlabel("дней от покупки до вручения")
    ax.set_ylabel("заказов")
    ax.legend(frameon=False)
    fig.tight_layout()
    return fig


@chart(
    "delivery_vs_review",
    "Опоздание и оценка заказа",
    "Чем сильнее опоздание относительно обещанной даты, тем ниже средняя оценка; это наблюдаемая связь, не доказанная причина.",
    order=20,
    section=SECTION,
)
def delivery_vs_review(conn):
    df = query_df(conn, "SELECT delay_group, orders, mean_score FROM mart.v_delivery_review ORDER BY group_order")
    fig, ax = new_figure()
    colors = [ACCENT] + [WARN] * (len(df) - 1)
    ax.bar(df["delay_group"], df["mean_score"].astype(float), color=colors)
    for x, row in enumerate(df.itertuples()):
        ax.text(x, float(row.mean_score) + 0.08, f"{row.mean_score} · n={row.orders:,}".replace(",", " "), ha="center")
    ax.set_ylim(0, 5.5)
    ax.set_ylabel("средняя оценка, 1–5")
    ax.set_xlabel("опоздание относительно обещанной даты")
    fig.tight_layout()
    return fig
