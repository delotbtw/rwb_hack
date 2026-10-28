"""Загрузка каталогов метрик и срезов из mart.metric_catalog / mart.dimension_catalog.

Каталоги читаются на каждый запрос (K1 §2): кэша нет.
"""

from dataclasses import dataclass

from psycopg2.extras import RealDictCursor

_METRIC_COLUMNS = (
    "metric_code, name, description, formula_sql, source_view, grain, "
    "additivity, is_additive, unit, allowed_dims, note"
)
_DIMENSION_COLUMNS = "dim_code, name, column_name, dim_type, source_views"


@dataclass(frozen=True)
class Metric:
    metric_code: str
    name: str
    description: str
    formula_sql: str
    source_view: str
    grain: str
    additivity: str
    is_additive: bool
    unit: str
    allowed_dims: list[str]
    note: str | None


@dataclass(frozen=True)
class Dimension:
    dim_code: str
    name: str
    column_name: str
    dim_type: str
    source_views: list[str]


@dataclass(frozen=True)
class Catalog:
    metrics: dict[str, Metric]
    dimensions: dict[str, Dimension]


def load_catalog(conn) -> Catalog:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f"SELECT {_METRIC_COLUMNS} FROM mart.metric_catalog ORDER BY metric_code")
        metrics = {r["metric_code"]: Metric(**r) for r in cur.fetchall()}
        cur.execute(f"SELECT {_DIMENSION_COLUMNS} FROM mart.dimension_catalog ORDER BY dim_code")
        dimensions = {r["dim_code"]: Dimension(**r) for r in cur.fetchall()}
    return Catalog(metrics=metrics, dimensions=dimensions)
