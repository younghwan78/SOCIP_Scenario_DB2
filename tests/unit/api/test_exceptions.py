from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from scenario_db.api.app import create_app


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
