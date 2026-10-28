"""Pydantic-модели API: запросы, ответы /api/metrics, /api/query, /api/status, /api/export.csv.

Контракт: docs/realtime/K0-contracts.md §5, docs/realtime/K1-api.md §2.
Ошибки валидации формы превращаются в 422 `invalid_request` (см. errors.py).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, StrictInt, StrictStr, model_validator

DEFAULT_LIMIT = 500
MAX_LIMIT = 1000
EXPORT_DEFAULT_LIMIT = 10000
EXPORT_MAX_LIMIT = 50000

MAX_GROUP_BY = 2
MAX_FILTERS = 6
MAX_FILTER_VALUES = 10
MAX_FILTER_VALUE_LEN = 100
MAX_CODE_LEN = 64

GRAINS = ("day", "week", "month")

Grain = Literal["day", "week", "month"]
Sort = Literal["asc", "desc"]
FilterValue = StrictStr | StrictInt


class _QueryCore(BaseModel):
    """Общая часть /api/query и /api/export.csv; `limit` задают наследники."""

    metric: str = Field(min_length=1, max_length=MAX_CODE_LEN)
    group_by: list[str] = Field(default_factory=list, max_length=MAX_GROUP_BY)
    filters: dict[str, list[FilterValue]] = Field(default_factory=dict)
    date_from: date | None = None
    date_to: date | None = None
    grain: Grain = "month"
    sort: Sort | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> _QueryCore:
        if len(set(self.group_by)) != len(self.group_by):
            raise ValueError("group_by contains duplicates")
        if any(not 0 < len(code) <= MAX_CODE_LEN for code in self.group_by):
            raise ValueError("group_by code has invalid length")
        if len(self.filters) > MAX_FILTERS:
            raise ValueError(f"at most {MAX_FILTERS} filters are allowed")
        for key, values in self.filters.items():
            if not 0 < len(key) <= MAX_CODE_LEN:
                raise ValueError("filter key has invalid length")
            if len(values) > MAX_FILTER_VALUES:
                raise ValueError(f"at most {MAX_FILTER_VALUES} values per filter are allowed")
            if any(isinstance(v, str) and len(v) > MAX_FILTER_VALUE_LEN for v in values):
                raise ValueError(f"filter value is longer than {MAX_FILTER_VALUE_LEN} characters")
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from is later than date_to")
        return self


class QueryRequest(_QueryCore):
    """POST /api/query."""

    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    with_total: bool = False


class ExportRequest(_QueryCore):
    """GET /api/export.csv: те же правила, другой диапазон `limit`, без `with_total`."""

    limit: int = Field(default=EXPORT_DEFAULT_LIMIT, ge=1, le=EXPORT_MAX_LIMIT)


class MetricBrief(BaseModel):
    code: str
    name: str
    unit: str | None = None
    additivity: str


class Column(BaseModel):
    name: str
    role: Literal["dim", "metric"]


class Explain(BaseModel):
    formula_sql: str
    source_view: str
    sql: str  # текст с плейсхолдерами %s
    params: list[Any]  # bind-значения в порядке плейсхолдеров


class QueryResponse(BaseModel):
    metric: MetricBrief
    columns: list[Column]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    explain: Explain
    total: float | None = None


class MetricInfo(BaseModel):
    code: str
    name: str
    description: str | None = None
    unit: str | None = None
    additivity: str
    is_additive: bool
    source_view: str
    grain: str | None = None
    allowed_dims: list[str]
    note: str | None = None
    formula_sql: str


class DimensionInfo(BaseModel):
    code: str
    name: str
    dim_type: str | None = None
    source_views: list[str]


class Limits(BaseModel):
    default: int = DEFAULT_LIMIT
    max: int = MAX_LIMIT


class MetricsResponse(BaseModel):
    metrics: list[MetricInfo]
    dimensions: list[DimensionInfo]
    grains: list[str] = list(GRAINS)
    limits: Limits = Field(default_factory=Limits)


class StreamStatus(BaseModel):
    """mart.stream_status; пустой поток даёт нули."""

    last_event_ts: datetime | None = None
    events_total: int = 0
    events_per_sec: float = 0
    lag_events: int = 0
    lag_sec: float = 0
    dlq_count: int = 0
    updated_at: datetime | None = None


class EtlRun(BaseModel):
    """Строка mart.etl_runs."""

    run_id: int
    ds: date
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    dq_passed: int | None = None
    dq_total: int | None = None
    reconcile_diff: float | None = None
    cutoff: date | None = None
    note: str | None = None


class DqFailure(BaseModel):
    check_id: str
    description: str
    expected: str
    actual: str | None = None


class DqStatus(BaseModel):
    passed: int
    total: int
    failed: list[DqFailure] = Field(default_factory=list)


class ReconcileItem(BaseModel):
    day: date | None = None
    check_code: str
    batch_value: float | None = None
    stream_value: float | None = None
    diff: float | None = None
    is_ok: bool


class ReconcileStatus(BaseModel):
    run_id: int
    ok: bool
    items: list[ReconcileItem] = Field(default_factory=list, max_length=50)


class ReplayRun(BaseModel):
    """Последняя строка mart.replay_runs по received_at."""

    replay_id: str
    cutoff: date | None = None
    events_total: int | None = None
    orders_total: int | None = None
    expected: dict[str, Any]
    received_at: datetime
    caught_up_at: datetime | None = None


class StatusResponse(BaseModel):
    server_time: datetime
    stream: StreamStatus
    last_batch: EtlRun | None = None
    last_published: EtlRun | None = None
    dq: DqStatus | None = None
    reconcile: ReconcileStatus | None = None
    last_replay: ReplayRun | None = None


class ErrorResponse(BaseModel):
    """Тело всех ошибок API."""

    error: str
    allowed: list[str] = Field(default_factory=list)
    detail: str | None = None
