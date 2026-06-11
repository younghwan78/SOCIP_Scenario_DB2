"""Domain-level exceptions for service layers.

Service modules (write, sim, ...) raise these instead of fastapi.HTTPException
so the same logic is reusable from CLI scripts and ETL without an HTTP
dependency. api/exceptions.py maps each type to its HTTP status code.
"""
from __future__ import annotations


class ScenarioDbError(Exception):
    """Base class for domain errors. `detail` is the human-readable message."""

    status_code = 500

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class BadRequestError(ScenarioDbError):
    """Malformed payload or unsupported operation (HTTP 400)."""

    status_code = 400


class NotFoundError(ScenarioDbError):
    """Referenced entity does not exist (HTTP 404)."""

    status_code = 404


class ConflictError(ScenarioDbError):
    """State machine or uniqueness conflict (HTTP 409)."""

    status_code = 409


class UnprocessableError(ScenarioDbError):
    """Semantically invalid request content (HTTP 422)."""

    status_code = 422
