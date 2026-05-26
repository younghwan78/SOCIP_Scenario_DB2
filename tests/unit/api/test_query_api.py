from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from scenario_db.api.app import create_app
from scenario_db.api.deps import get_db
from tests.unit.query_engine.test_architecture_query_service import _Session


def _empty_session() -> MagicMock:
    session = MagicMock()
    query = MagicMock()
    query.all.return_value = []
    session.query.return_value = query
    return session


def test_query_facets_and_empty_variant_query_return_200() -> None:
    app = create_app()
    mock_session = _empty_session()

    @asynccontextmanager
    async def _lifespan(a):
        a.state.engine = None
        a.state.session_factory = lambda: mock_session
        a.state.rule_cache = None
        yield

    app.router.lifespan_context = _lifespan

    def _override_db():
        yield mock_session

    app.dependency_overrides[get_db] = _override_db

    with TestClient(app, raise_server_exceptions=False) as client:
        facets = client.get("/api/v1/query/facets")
        assert facets.status_code == 200
        assert any(item["field"] == "topology.uses_ip" for item in facets.json()["fields"])

        response = client.post(
            "/api/v1/query/variants",
            json={"where": [{"field": "axis.resolution", "op": "eq", "value": "UHD"}]},
        )
        assert response.status_code == 200
        assert response.json()["items"] == []


def test_query_api_returns_validation_error_for_invalid_request_shape() -> None:
    app = create_app()
    mock_session = _empty_session()

    @asynccontextmanager
    async def _lifespan(a):
        a.state.engine = None
        a.state.session_factory = lambda: mock_session
        a.state.rule_cache = None
        yield

    app.router.lifespan_context = _lifespan

    def _override_db():
        yield mock_session

    app.dependency_overrides[get_db] = _override_db

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/query/variants",
            json={"limit": 0, "where": [{"field": "axis.resolution", "op": "eq", "value": "UHD"}]},
        )

    assert response.status_code == 422


def test_query_variants_endpoint_returns_filtered_architecture_facts() -> None:
    app = create_app()
    mock_session = _Session()

    @asynccontextmanager
    async def _lifespan(a):
        a.state.engine = None
        a.state.session_factory = lambda: mock_session
        a.state.rule_cache = None
        yield

    app.router.lifespan_context = _lifespan

    def _override_db():
        yield mock_session

    app.dependency_overrides[get_db] = _override_db

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/query/variants",
            json={
                "scope": {"soc_ref": "soc-demo", "project_ref": "proj-demo"},
                "where": [
                    {"field": "buffer.compression", "op": "contains", "value": "SBWC"},
                    {"field": "topology.uses_buffer", "op": "exists", "value": True},
                ],
                "sort": [{"field": "variant.id", "dir": "asc"}],
            },
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["total"] == 2
    assert [item["variant_id"] for item in payload["items"]] == ["FHD30", "UHD60"]
    assert payload["items"][0]["viewer_query"] == {
        "soc_id": "soc-demo",
        "project_id": "proj-demo",
        "scenario_id": "uc-camera",
        "variant_id": "FHD30",
    }


def test_query_variants_endpoint_returns_groups_and_aggregation() -> None:
    app = create_app()
    mock_session = _Session()

    @asynccontextmanager
    async def _lifespan(a):
        a.state.engine = None
        a.state.session_factory = lambda: mock_session
        a.state.rule_cache = None
        yield

    app.router.lifespan_context = _lifespan

    def _override_db():
        yield mock_session

    app.dependency_overrides[get_db] = _override_db

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/query/variants",
            json={
                "where": [{"field": "scenario.category", "op": "eq", "value": "camera"}],
                "groups": [
                    {
                        "join": "or",
                        "where": [
                            {"field": "axis.resolution", "op": "eq", "value": "UHD"},
                            {"field": "axis.fps", "op": "eq", "value": 30},
                        ],
                    }
                ],
                "aggregate": {
                    "group_by": ["scenario.category"],
                    "metrics": [
                        {
                            "field": "evidence.latest.kpi.total_power_mw",
                            "ops": ["count", "avg", "p95", "max"],
                        }
                    ],
                },
            },
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["total"] == 2
    assert payload["aggregations"][0]["key"] == {"scenario.category": "camera"}
    assert payload["aggregations"][0]["metrics"]["evidence.latest.kpi.total_power_mw"]["avg"] == 1500.0


def test_query_variants_endpoint_returns_field_errors_as_standard_4xx_envelope() -> None:
    app = create_app()
    mock_session = _Session()

    @asynccontextmanager
    async def _lifespan(a):
        a.state.engine = None
        a.state.session_factory = lambda: mock_session
        a.state.rule_cache = None
        yield

    app.router.lifespan_context = _lifespan

    def _override_db():
        yield mock_session

    app.dependency_overrides[get_db] = _override_db

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/query/variants",
            json={"where": [{"field": "raw.sql", "op": "eq", "value": "select 1"}]},
        )

    payload = response.json()
    assert response.status_code == 400
    assert payload["error"] == "bad_request"
    assert "Unsupported query field: raw.sql" in payload["detail"]


def test_query_variants_endpoint_rejects_non_numeric_metric_fields() -> None:
    app = create_app()
    mock_session = _Session()

    @asynccontextmanager
    async def _lifespan(a):
        a.state.engine = None
        a.state.session_factory = lambda: mock_session
        a.state.rule_cache = None
        yield

    app.router.lifespan_context = _lifespan

    def _override_db():
        yield mock_session

    app.dependency_overrides[get_db] = _override_db

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/query/variants",
            json={
                "aggregate": {
                    "group_by": ["scenario.category"],
                    "metrics": [{"field": "scenario.category", "ops": ["avg"]}],
                }
            },
        )

    payload = response.json()
    assert response.status_code == 400
    assert payload["error"] == "bad_request"
    assert "aggregation_field_type_mismatch" in " ".join(payload["detail"])
