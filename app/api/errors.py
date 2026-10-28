"""Единый формат ошибок API: `{error, allowed, detail?}` (K1-api.md §2).

SQL и текст исключений клиенту не отдаются, только в лог.
"""

import logging
from typing import Any

import psycopg2
import psycopg2.errors
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.schemas import ErrorResponse

log = logging.getLogger("app.api")

MAX_DETAIL_LEN = 300
_LOC_PREFIXES = ("body", "query")


class ApiError(Exception):
    """Ошибка API с HTTP-статусом и кодом из таблицы K1-api.md §2."""

    def __init__(
        self,
        status_code: int,
        error: str,
        allowed: list[str] | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(error)
        self.status_code = status_code
        self.error = error
        self.allowed = list(allowed or [])
        self.detail = detail

    @classmethod
    def unknown_metric(cls, allowed: list[str]) -> "ApiError":
        return cls(422, "unknown_metric", allowed)

    @classmethod
    def unknown_dim(cls, allowed: list[str]) -> "ApiError":
        return cls(422, "unknown_dim", allowed)

    @classmethod
    def dim_not_allowed(cls, allowed: list[str]) -> "ApiError":
        return cls(422, "dim_not_allowed", allowed)

    @classmethod
    def non_additive_rollup(cls) -> "ApiError":
        return cls(422, "non_additive_rollup", ["with_total=false"])

    @classmethod
    def invalid_request(cls, detail: str | None = None) -> "ApiError":
        return cls(422, "invalid_request", [], detail)

    @classmethod
    def query_timeout(cls) -> "ApiError":
        return cls(504, "query_timeout")

    @classmethod
    def db_unavailable(cls) -> "ApiError":
        return cls(503, "db_unavailable")

    @classmethod
    def internal(cls) -> "ApiError":
        return cls(500, "internal")


def _validation_detail(errors: list[Any]) -> str:
    """Короткое описание без введённых значений: поле и сообщение валидатора."""
    parts = []
    for err in errors:
        loc = [str(p) for p in err.get("loc", ())]
        if loc and loc[0] in _LOC_PREFIXES:
            loc = loc[1:]
        msg = str(err.get("msg", "invalid")).removeprefix("Value error, ")
        parts.append(f"{'.'.join(loc)}: {msg}" if loc else msg)
    return "; ".join(parts)[:MAX_DETAIL_LEN]


def invalid_request_from(exc: ValidationError | RequestValidationError) -> ApiError:
    """Ошибка формы запроса -> 422 `invalid_request`; пригодно и для ручной сборки модели в роуте."""
    return ApiError.invalid_request(_validation_detail(exc.errors()))


def _response(err: ApiError) -> JSONResponse:
    body = ErrorResponse(error=err.error, allowed=err.allowed, detail=err.detail)
    return JSONResponse(status_code=err.status_code, content=body.model_dump(exclude_none=True))


async def _api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return _response(exc)


async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return _response(invalid_request_from(exc))


async def _timeout_handler(request: Request, exc: psycopg2.errors.QueryCanceled) -> JSONResponse:
    log.warning("query timeout on %s: %s", request.url.path, exc)
    return _response(ApiError.query_timeout())


async def _db_unavailable_handler(request: Request, exc: psycopg2.OperationalError) -> JSONResponse:
    log.error("database unavailable on %s: %s", request.url.path, exc)
    return _response(ApiError.db_unavailable())


async def _internal_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled error on %s", request.url.path, exc_info=exc)
    return _response(ApiError.internal())


def register_handlers(app: FastAPI) -> None:
    """Подключает обработчики; вызывается один раз при сборке приложения/роутера."""
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(psycopg2.errors.QueryCanceled, _timeout_handler)
    app.add_exception_handler(psycopg2.OperationalError, _db_unavailable_handler)
    app.add_exception_handler(Exception, _internal_handler)
