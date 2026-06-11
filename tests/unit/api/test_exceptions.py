from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from scenario_db.api.app import create_app
from scenario_db.exceptions import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    UnprocessableError,
)


@pytest.mark.parametrize(
    ("exc_type", "status", "error_code"),
    [
        (BadRequestError, 400, "bad_request"),
        (NotFoundError, 404, "not_found"),
        (ConflictError, 409, "conflict"),
        (UnprocessableError, 422, "validation_error"),
    ],
)
def test_domain_errors_map_to_http_status(exc_type, status, error_code):
    """Review 5.1: service layers raise domain exceptions; the API handler
    maps them to status codes so services stay HTTP-free."""
    app = create_app()

    @app.get("/domain-boom")
    def _boom():
        raise exc_type("domain failure detail")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/domain-boom")

    assert response.status_code == status
    assert response.json() == {"error": error_code, "detail": "domain failure detail"}


def test_integrity_error_response_masks_raw_database_message():
    app = create_app()

    @app.get("/boom")
    def _boom():
        raise IntegrityError("insert secret", {"id": "secret-id"}, Exception("duplicate key raw database text"))

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")

    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "conflict"
    assert "duplicate key raw database text" not in body["detail"]
    assert "secret-id" not in body["detail"]
