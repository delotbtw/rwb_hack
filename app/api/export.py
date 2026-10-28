"""CSV-экспорт для GET /api/export.csv (K1-api.md §2, §3).

Параметры запроса собираются в `ExportRequest`, ответ строится из `QueryResponse`.
Строковые ячейки, начинающиеся с формульных символов, получают префикс `'` (CSV-injection).
"""

import csv
import io
import json
from typing import Any

from pydantic import ValidationError

from app.api.errors import ApiError, invalid_request_from
from app.api.schemas import ExportRequest, QueryResponse

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def build_export_request(
    *,
    metric: str,
    group_by: list[str],
    filters: str | None,
    date_from: str | None,
    date_to: str | None,
    grain: str | None,
    sort: str | None,
    limit: int | None,
) -> ExportRequest:
    """Собирает ExportRequest из query-параметров; ошибки формы -> 422 `invalid_request`."""
    parsed_filters: Any = {}
    if filters:
        try:
            parsed_filters = json.loads(filters)
        except ValueError:
            raise ApiError.invalid_request("filters: invalid JSON") from None
    optional = {
        "date_from": date_from,
        "date_to": date_to,
        "grain": grain,
        "sort": sort,
        "limit": limit,
    }
    try:
        return ExportRequest(
            metric=metric,
            group_by=group_by,
            filters=parsed_filters,
            **{key: value for key, value in optional.items() if value is not None},
        )
    except ValidationError as exc:
        raise invalid_request_from(exc) from None


def _safe_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def to_csv(result: QueryResponse) -> str:
    """Заголовок = `columns`, затем строки в порядке `rows`; None -> пустая ячейка."""
    names = [column.name for column in result.columns]
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(names)
    for row in result.rows:
        writer.writerow([_safe_cell(row.get(name)) for name in names])
    return buffer.getvalue()
