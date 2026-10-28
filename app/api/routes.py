"""Роуты API поверх mart.*: /api/metrics, /api/query, /api/status, /api/export.csv.

Эндпоинты синхронные, соединение `connect_ro()` открывается на каждый запрос.
Обработчики ошибок вешаются на приложение (`register_handlers`), не на router.
"""

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.api.catalog import Catalog, load_catalog
from app.api.db import connect_ro
from app.api.export import build_export_request, to_csv
from app.api.query_builder import run_query
from app.api.schemas import (
    EXPORT_DEFAULT_LIMIT,
    DimensionInfo,
    MetricInfo,
    MetricsResponse,
    QueryRequest,
    QueryResponse,
    StatusResponse,
)
from app.api.status import build_status

router = APIRouter(prefix="/api")


def _metrics_response(catalog: Catalog) -> MetricsResponse:
    return MetricsResponse(
        metrics=[
            MetricInfo(
                code=m.metric_code,
                name=m.name,
                description=m.description,
                unit=m.unit,
                additivity=m.additivity,
                is_additive=m.is_additive,
                source_view=m.source_view,
                grain=m.grain,
                allowed_dims=m.allowed_dims,
                note=m.note,
                formula_sql=m.formula_sql,
            )
            for m in catalog.metrics.values()
        ],
        dimensions=[
            DimensionInfo(
                code=d.dim_code, name=d.name, dim_type=d.dim_type, source_views=d.source_views
            )
            for d in catalog.dimensions.values()
        ],
    )


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics() -> MetricsResponse:
    with connect_ro() as conn:
        return _metrics_response(load_catalog(conn))


@router.post("/query", response_model=QueryResponse)
def post_query(req: QueryRequest) -> QueryResponse:
    with connect_ro() as conn:
        return run_query(conn, load_catalog(conn), req)


@router.get("/status", response_model=StatusResponse)
def get_status() -> StatusResponse:
    with connect_ro() as conn:
        return build_status(conn)


@router.get("/export.csv")
def get_export_csv(
    metric: str,
    group_by: list[str] = Query(default_factory=list),
    filters: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    grain: str | None = None,
    sort: str | None = None,
    limit: int = EXPORT_DEFAULT_LIMIT,
) -> Response:
    req = build_export_request(
        metric=metric,
        group_by=group_by,
        filters=filters,
        date_from=date_from,
        date_to=date_to,
        grain=grain,
        sort=sort,
        limit=limit,
    )
    with connect_ro() as conn:
        result = run_query(conn, load_catalog(conn), req)
    return Response(
        content=to_csv(result),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{result.metric.code}.csv"',
            "X-Truncated": "true" if result.truncated else "false",
        },
    )
