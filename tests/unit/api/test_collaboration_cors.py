from fastapi.testclient import TestClient

from scenario_db.api.app import create_app
from scenario_db.config import get_settings


def test_cross_origin_note_save_and_existing_report_review_are_allowed():
    client = TestClient(create_app())
    origin = get_settings().cors_origins[0]
    for method, path in (
        ("PUT", "/api/v1/arch/predictions/example/notes"),
        ("PATCH", "/api/v1/arch/reports/example"),
    ):
        response = client.options(path, headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "Content-Type,X-ScenarioDB-Key-Id,X-ScenarioDB-API-Key",
        })
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        assert method in response.headers["access-control-allow-methods"].split(", ")
