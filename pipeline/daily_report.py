"""Ежедневный HTML-отчёт (K3 §3.5): `output/daily/<ds>.html`. Только stdlib, читает витрины `mart` и `ops.etl_runs`.

Показатели: за день ds — заказы, выручка, средний чек; накопительно до ds включительно — заказы, выручка,
доля просрочек, топ-5 категорий; DQ passed/total; reconcile_diff; длительность запуска.
Формулы как в `mart.v_kpi`: выручка = Σ goods_value по is_revenue, средний чек = Σ order_value / число заказов is_revenue,
просрочки = доля delay_days > 0 среди is_valid_delivery. Статус запуска отчёт не меняет.
"""

import datetime as dt
import html
from decimal import Decimal
from pathlib import Path

import psycopg2

from pipeline.bundle import ROOT
from pipeline.run_etl import DSN

OUT_DIR = ROOT / "output" / "daily"
CENT = Decimal("0.01")

ORDERS_SQL = """
    SELECT COUNT(*),
           COALESCE(SUM(goods_value) FILTER (WHERE is_revenue), 0),
           COUNT(*) FILTER (WHERE is_revenue),
           COALESCE(SUM(order_value) FILTER (WHERE is_revenue), 0),
           COUNT(*) FILTER (WHERE is_valid_delivery),
           COUNT(*) FILTER (WHERE is_valid_delivery AND delay_days > 0)
    FROM mart.order_summary
    WHERE purchased_at::date {op} %s
"""
TOP_SQL = """
    SELECT COALESCE(category_label, '(без категории)'), SUM(price) FILTER (WHERE is_revenue) AS revenue
    FROM mart.v_sales_item
    WHERE purchase_ts::date <= %s
    GROUP BY 1
    HAVING SUM(price) FILTER (WHERE is_revenue) IS NOT NULL
    ORDER BY revenue DESC, 1
    LIMIT 5
"""


def _money(value) -> str:
    return f"{Decimal(value).quantize(CENT):,.2f}".replace(",", " ")


def _pct(part: int, whole: int) -> str:
    return f"{(Decimal(100) * part / whole).quantize(CENT)}%" if whole else "—"


def _duration(started: dt.datetime, finished: dt.datetime | None) -> str:
    if finished is None:
        return "—"
    secs = int((finished - started).total_seconds())
    return f"{secs // 60} мин {secs % 60} с"


def _collect(run_id: int, ds: dt.date) -> dict:
    with psycopg2.connect(**DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status, started_at, finished_at, dq_passed, dq_total, reconcile_diff, cutoff, note "
            "FROM ops.etl_runs WHERE run_id = %s",
            (run_id,),
        )
        run = cur.fetchone()
        if run is None:
            raise ValueError(f"запуск {run_id} не найден в ops.etl_runs")
        cur.execute(ORDERS_SQL.format(op="="), (ds,))
        day = cur.fetchone()
        cur.execute(ORDERS_SQL.format(op="<="), (ds,))
        total = cur.fetchone()
        cur.execute(TOP_SQL, (ds,))
        top = cur.fetchall()
    return {"run": run, "day": day, "total": total, "top": top}


def _table(rows: list[tuple[str, str]]) -> str:
    body = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>" for k, v in rows)
    return f"<table>{body}</table>"


def _render(run_id: int, ds: dt.date, data: dict) -> str:
    status, started, finished, dq_passed, dq_total, rec_diff, cutoff, note = data["run"]
    d_orders, d_rev, d_rev_orders, d_rev_value, _, _ = data["day"]
    t_orders, t_rev, _, _, t_valid, t_late = data["total"]

    day_rows = [
        ("Заказы", str(d_orders)),
        ("Выручка, BRL", _money(d_rev)),
        ("Средний чек, BRL", _money(Decimal(d_rev_value) / d_rev_orders) if d_rev_orders else "—"),
    ]
    total_rows = [
        ("Заказы", str(t_orders)),
        ("Выручка, BRL", _money(t_rev)),
        ("Доля просрочек", _pct(t_late, t_valid)),
    ]
    run_rows = [
        ("Статус", status),
        ("Проверки качества", f"DQ {dq_passed}/{dq_total}" if dq_total is not None else "—"),
        ("Расхождение сверки (Σ|diff|)", _money(rec_diff) if rec_diff is not None else "—"),
        ("Длительность", _duration(started, finished)),
        ("Cutoff", str(cutoff) if cutoff else "нет"),
    ]
    if note:
        run_rows.append(("Примечание", note))
    top = "".join(
        f"<tr><td>{html.escape(name)}</td><td class='n'>{_money(rev)}</td></tr>" for name, rev in data["top"]
    ) or "<tr><td colspan='2'>нет данных</td></tr>"

    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>Capibara: отчёт за {ds}</title>
<style>
body {{ font-family: sans-serif; margin: 2rem auto; max-width: 42rem; color: #222; }}
table {{ border-collapse: collapse; margin-bottom: 1.5rem; width: 100%; }}
th, td {{ border-bottom: 1px solid #ddd; padding: .35rem .6rem; text-align: left; }}
td.n {{ text-align: right; }}
</style></head><body>
<h1>Отчёт за {ds}</h1>
<p>Запуск {run_id}</p>
<h2>За день</h2>{_table(day_rows)}
<h2>Накопительно до {ds}</h2>{_table(total_rows)}
<h2>Топ-5 категорий по выручке</h2><table>{top}</table>
<h2>Запуск</h2>{_table(run_rows)}
</body></html>
"""


def report(run_id: int, ds: dt.date | str) -> Path:
    """Пишет `output/daily/<ds>.html` и возвращает путь."""
    ds = dt.date.fromisoformat(ds) if isinstance(ds, str) else ds
    content = _render(run_id, ds, _collect(run_id, ds))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{ds}.html"
    path.write_text(content, encoding="utf-8")
    return path
