from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, NoResultFound


def _error_code_for_status(status_code: int) -> str:
    if status_code == 400:
        return "bad_request"
    if status_code == 404:
        return "not_found"
    if status_code == 409:
        return "conflict"
    if status_code == 422:
        return "validation_error"
    if status_code == 501:
        return "not_implemented"
    return "http_error"


async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": _error_code_for_status(exc.status_code),
            "detail": exc.detail,
        },
        headers=exc.headers,
    )


async def _not_found_handler(request: Request, exc: NoResultFound) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": "not_found", "detail": str(exc)},
    )


async def _conflict_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"error": "conflict", "detail": str(exc.orig)},
    )


async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "detail": exc.errors()},
    )


def register_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(NoResultFound, _not_found_handler)
    app.add_exception_handler(IntegrityError, _conflict_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
