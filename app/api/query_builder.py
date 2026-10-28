"""Сборка и выполнение запроса к витринам по каталогу метрик и срезов.

Контракт: docs/realtime/K1-api.md §2 (POST /api/query), §3 (сборка SQL и безопасность).

    from app.api.catalog import load_catalog
    from app.api.query_builder import run_query

    with connect_ro() as conn:
        response = run_query(conn, load_catalog(conn), request)

В текст SQL попадает только каталожное (`formula_sql`, `source_view`, `column_name`) и фиксированные
словари; всё от клиента - ключ каталога или bind-параметр.
"""

import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg2.errors
from psycopg2 import sql

from app.api.catalog import Catalog, Dimension, Metric
from app.api.errors import ApiError
from app.api.schemas import (
    Column,
    ExportRequest,
    Explain,
    MetricBrief,
    QueryRequest,
    QueryResponse,
)

log = logging.getLogger("app.api")

SOURCE_VIEW_RE = re.compile(r"^mart\.[a-z_]+$")
COLUMN_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

TIME_COLUMN = {"mart.v_sales_item": "purchase_ts", "mart.order_summary": "purchased_at"}
MONTH_DIM = "month"
GRAIN_SQL = {"day": "day", "week": "week"}
SORT_SQL = {"asc": sql.SQL("ASC"), "desc": sql.SQL("DESC")}


def _internal(message: str, *args: Any) -> ApiError:
    log.error(message, *args)
    return ApiError.internal()


def _source_identifier(metric: Metric) -> sql.Identifier:
    if not SOURCE_VIEW_RE.fullmatch(metric.source_view):
        raise _internal("catalog: bad source_view of metric %s", metric.metric_code)
    schema, name = metric.source_view.split(".")
    return sql.Identifier(schema, name)


def _column_identifier(column_name: str, owner: str) -> sql.Identifier:
    if not COLUMN_NAME_RE.fullmatch(column_name):
        raise _internal("catalog: bad column_name of dimension %s", owner)
    return sql.Identifier(column_name)


def _time_identifier(metric: Metric) -> sql.Identifier:
    column = TIME_COLUMN.get(metric.source_view)
    if column is None:
        raise _internal("no time column for %s", metric.source_view)
    return sql.Identifier(column)


def _resolve_dims(
    catalog: Catalog, metric: Metric, req: QueryRequest | ExportRequest
) -> list[Dimension]:
    """Проверка срезов `group_by` и `filters`: каталог, затем `allowed_dims` метрики."""
    codes = list(req.group_by) + [c for c in req.filters if c not in req.group_by]
    for code in codes:
        if code not in catalog.dimensions:
            raise ApiError.unknown_dim(sorted(catalog.dimensions))
    for code in codes:
        dim = catalog.dimensions[code]
        if code not in metric.allowed_dims or metric.source_view not in dim.source_views:
            raise ApiError.dim_not_allowed(list(metric.allowed_dims))
    if (req.date_from or req.date_to) and MONTH_DIM not in metric.allowed_dims:
        raise ApiError.dim_not_allowed([])
    return [catalog.dimensions[code] for code in req.group_by]


def _dim_expression(dim: Dimension, metric: Metric, grain: str) -> sql.Composable:
    """Выражение среза; `month` при grain day/week - начало периода по времени источника."""
    if dim.dim_code == MONTH_DIM and grain in GRAIN_SQL:
        return sql.SQL("date_trunc({}, {})::date").format(
            sql.Literal(GRAIN_SQL[grain]), _time_identifier(metric)
        )
    return _column_identifier(dim.column_name, dim.dim_code)


def _where(
    catalog: Catalog, metric: Metric, req: QueryRequest | ExportRequest
) -> tuple[sql.Composable, list[Any]]:
    parts: list[sql.Composable] = []
    params: list[Any] = []
    for code, values in req.filters.items():
        if not values:
            continue
        column = _column_identifier(catalog.dimensions[code].column_name, code)
        parts.append(sql.SQL("{}::text = ANY(%s)").format(column))
        params.append([str(v) for v in values])
    if req.date_from:
        parts.append(sql.SQL("{} >= %s").format(_time_identifier(metric)))
        params.append(req.date_from)
    if req.date_to:
        parts.append(sql.SQL("{} < %s").format(_time_identifier(metric)))
        params.append(req.date_to + timedelta(days=1))
    if not parts:
        return sql.SQL(""), params
    return sql.SQL(" WHERE ") + sql.SQL(" AND ").join(parts), params


def _order_by(
    req: QueryRequest | ExportRequest, dims: list[Dimension], metric: Metric
) -> sql.Composable:
    if not dims:
        return sql.SQL("")
    metric_alias = sql.Identifier(metric.metric_code)
    month_first = req.sort is None and any(d.dim_code == MONTH_DIM for d in dims)
    if req.sort is not None:
        items = [sql.SQL("{} {} NULLS LAST").format(metric_alias, SORT_SQL[req.sort])]
    elif month_first:
        items = [sql.SQL("{} ASC").format(sql.Identifier(MONTH_DIM))]
    else:
        items = [sql.SQL("{} DESC NULLS LAST").format(metric_alias)]
    items += [
        sql.SQL("{} ASC").format(sql.Identifier(d.dim_code))
        for d in dims
        if not (month_first and d.dim_code == MONTH_DIM)
    ]
    return sql.SQL(" ORDER BY ") + sql.SQL(", ").join(items)


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _json_params(params: list[Any]) -> list[Any]:
    return [[_json_value(v) for v in p] if isinstance(p, list) else _json_value(p) for p in params]


def run_query(
    conn, catalog: Catalog, req: QueryRequest | ExportRequest
) -> QueryResponse:
    """Проверяет запрос по каталогу, собирает SQL и выполняет его на `conn` (роль app_ro).

    Порядок проверок: metric, срезы (group_by, filters, date_*), rollup. Ошибки - `ApiError`;
    превышение statement_timeout превращается в `ApiError.query_timeout()`.
    Для `ExportRequest` `with_total` считается false.
    """
    metric = catalog.metrics.get(req.metric)
    if metric is None:
        raise ApiError.unknown_metric(sorted(catalog.metrics))
    dims = _resolve_dims(catalog, metric, req)
    with_total = getattr(req, "with_total", False)
    if with_total and metric.additivity != "additive":
        raise ApiError.non_additive_rollup()

    source = _source_identifier(metric)
    where, where_params = _where(catalog, metric, req)
    formula = sql.SQL(metric.formula_sql)
    metric_select = sql.SQL("{} AS {}").format(formula, sql.Identifier(metric.metric_code))

    select_items = [
        sql.SQL("{} AS {}").format(_dim_expression(d, metric, req.grain), sql.Identifier(d.dim_code))
        for d in dims
    ] + [metric_select]
    group = sql.SQL("")
    if dims:
        group = sql.SQL(" GROUP BY ") + sql.SQL(", ").join(
            _dim_expression(d, metric, req.grain) for d in dims
        )
    query = (
        sql.SQL("SELECT {} FROM {}").format(sql.SQL(", ").join(select_items), source)
        + where
        + group
        + _order_by(req, dims, metric)
        + sql.SQL(" LIMIT %s")
    )
    params = [*where_params, req.limit + 1]

    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            names = [d.name for d in cur.description]
            fetched = cur.fetchall()
            total = None
            if with_total:
                total_query = sql.SQL("SELECT {} FROM {}").format(formula, source) + where
                cur.execute(total_query, where_params)
                raw_total = cur.fetchone()[0]
                total = None if raw_total is None else float(raw_total)
        explain_sql = query.as_string(conn)
    except psycopg2.errors.QueryCanceled as exc:
        log.warning("query timeout for metric %s: %s", metric.metric_code, exc)
        raise ApiError.query_timeout() from exc

    truncated = len(fetched) > req.limit
    rows = [
        {name: _json_value(value) for name, value in zip(names, row)}
        for row in fetched[: req.limit]
    ]
    columns = [Column(name=d.dim_code, role="dim") for d in dims] + [
        Column(name=metric.metric_code, role="metric")
    ]
    return QueryResponse(
        metric=MetricBrief(
            code=metric.metric_code,
            name=metric.name,
            unit=metric.unit,
            additivity=metric.additivity,
        ),
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        explain=Explain(
            formula_sql=metric.formula_sql,
            source_view=metric.source_view,
            sql=explain_sql,
            params=_json_params(params),
        ),
        total=total,
    )
