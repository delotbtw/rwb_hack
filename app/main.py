"""Веб-прототип: страница с PNG-графиками из mart, каждый рисуется по запросу.

    uvicorn app.main:app --port 8000

GET /                 — все графики карточками (PNG + легенда в одно предложение)
GET /chart/{id}.png   — один график; кэшируется до следующей сборки модели
GET /health           — проверка, что приложение видит базу
Графики из ноутбуков (pipeline/import_notebook.py) — отдельной секцией, PNG из app/static/notebook/.
"""

import io
import json
import pathlib
import traceback
from functools import lru_cache

import matplotlib

matplotlib.use("Agg")

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import HTMLResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

import app.charts  # noqa: E402,F401  регистрирует все графики
from app.db import build_version, connect, query_df  # noqa: E402
from app.registry import REGISTRY, by_section  # noqa: E402

HERE = pathlib.Path(__file__).parent
STATIC = HERE / "static"
NOTEBOOK_MANIFEST = STATIC / "notebook" / "manifest.json"
STATIC.mkdir(exist_ok=True)

app = FastAPI(title="Capibara: прототип дашборда")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


def notebook_charts() -> list[dict]:
    """Читается на каждом запросе: после `make notebook` перезапуск приложения не нужен."""
    try:
        return json.loads(NOTEBOOK_MANIFEST.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _to_png(fig: Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    return buf.getvalue()


def _error_png(chart_id: str, err: Exception) -> bytes:
    fig = Figure(figsize=(8, 2.5), dpi=110)
    fig.text(0.02, 0.5, f"{chart_id}: {type(err).__name__}: {err}"[:300], wrap=True, color="#b91c1c", va="center")
    return _to_png(fig)


def _fmt(value, kind: str) -> str:
    if value is None:
        return "—"
    if kind == "money":
        return f"{float(value):,.2f}".replace(",", " ")
    if kind == "int":
        return f"{int(value):,}".replace(",", " ")
    if kind == "pct":
        return f"{float(value):.2f} %"
    return f"{float(value):.1f}"


@lru_cache(maxsize=8)
def _kpi(version: str) -> dict:
    """Строка KPI из mart.v_kpi и сводка DQ — тоже кэшируются до следующей сборки."""
    with connect() as conn:
        k = query_df(conn, "SELECT * FROM mart.v_kpi").iloc[0]
        dq = query_df(conn, "SELECT count(*) AS total, count(*) FILTER (WHERE passed) AS passed FROM mart.dq_result").iloc[0]
    tiles = [
        ("Выручка, BRL", _fmt(k.revenue, "money"), "Σ price доставленных заказов"),
        ("Доставленных заказов", _fmt(k.delivered_orders, "int"), "статус delivered"),
        ("Средний чек, BRL", _fmt(k.avg_check, "money"), "товар + доставка, на заказ"),
        ("Покупателей", _fmt(k.customers, "int"), "по customer_unique_id"),
        ("Вернулись", _fmt(k.repeat_pct, "pct"), "2+ заказа"),
        ("Опоздали", _fmt(k.late_pct, "pct"), f"медиана доставки {_fmt(k.median_delivery_days, 'num')} дн"),
    ]
    return {"tiles": tiles, "dq_total": int(dq.total), "dq_passed": int(dq.passed)}


@lru_cache(maxsize=256)
def _render(chart_id: str, version: str) -> bytes:
    with connect() as conn:
        return _to_png(REGISTRY[chart_id].render(conn))


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    kpi = None
    try:
        with connect() as conn:
            version = build_version(conn)
        kpi = _kpi(version)
    except Exception as e:  # база или модель недоступна — страница всё равно открывается
        traceback.print_exc()
        version = f"модель недоступна: {e}"
    return templates.TemplateResponse(
        request, "index.html",
        {"sections": by_section(), "notebook_charts": notebook_charts(), "version": version, "kpi": kpi},
    )


@app.get("/chart/{chart_id}.png")
def chart_png(chart_id: str):
    if chart_id not in REGISTRY:
        raise HTTPException(404, f"Нет графика {chart_id!r}")
    try:
        with connect() as conn:
            version = build_version(conn)
        png = _render(chart_id, version)
    except Exception as e:
        traceback.print_exc()
        png = _error_png(chart_id, e)
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-cache"})


@app.get("/health")
def health():
    with connect() as conn:
        return {"status": "ok", "build": build_version(conn), "charts": len(REGISTRY),
                "notebook_charts": len(notebook_charts())}
