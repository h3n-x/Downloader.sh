"""One error envelope for every failure. No stack traces or internals reach clients."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from downloader.api.schemas import ErrorBody, ErrorOut
from downloader.domain.errors import ERROR_SPECS, AppError, ErrorCode
from downloader.observability import request_id_var

log = logging.getLogger(__name__)

_HTTP_TO_CODE = {404: ErrorCode.NOT_FOUND, 405: ErrorCode.NOT_FOUND, 429: ErrorCode.RATE_LIMITED}


def error_response(
    code: ErrorCode, *, retry_after: int | None = None, fields: list[str] | None = None
) -> JSONResponse:
    spec = ERROR_SPECS[code]
    body = ErrorOut(
        error=ErrorBody(
            code=code,
            message=spec.default_message,
            retryable=spec.retryable,
            request_id=request_id_var.get(),
            retry_after=retry_after,
            fields=fields,
        )
    )
    headers = {"Cache-Control": "no-store"}
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(body.model_dump(mode="json", exclude_none=True), spec.status, headers)


def install(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError) -> JSONResponse:
        if exc.spec.status >= 500 and exc.code is ErrorCode.INTERNAL_ERROR:
            log.error("internal error", extra={"detail": exc.detail})
        return error_response(exc.code, retry_after=exc.retry_after)

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = sorted(
            {".".join(str(p) for p in e.get("loc", ())[1:]) or "body" for e in exc.errors()}
        )
        return error_response(ErrorCode.VALIDATION_ERROR, fields=fields[:10])

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(_HTTP_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR))

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled exception", exc_info=exc)
        return error_response(ErrorCode.INTERNAL_ERROR)
