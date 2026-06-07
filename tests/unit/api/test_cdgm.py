from __future__ import annotations

import time
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from scenario_db.api.app import create_app
from scenario_db.api.cache import RuleCache
from scenario_db.api.deps import get_db, get_rule_cache


def test_cdgm_resolve_endpoint_returns_resolved_arch_info(monkeypatch):
    from scenario_db.api.routers import cdgm as cdgm_router

    def fake_resolve(db, request):
        return {
            "scenario_id": request.scenario_id,
            "variant_id": request.variant_id,
            "soc_ref": "soc-A",
            "dvfs_table_ref": "dvfs-soc-A-v4",
            "cdgm_profile_ref": "cdgm-prof-soc-A-v1",
            "arch_info_rows": [
                {
                    "ip_ref": "ip-isp-v12",
                    "role_key": "ISP",
                    "arch_ip": "ISP",
                    "pos": "STEP1+STEP2+STEP3",
                    "ppc": 4.0,
                    "vdd": "VDD_CAM",
                    "dvfs_domain": "ISP",
                }
            ],
            "issues": [],
        }

    monkeypatch.setattr(cdgm_router, "resolve_cdgm_request", fake_resolve)
    app = create_app()
    mock_session = MagicMock()

    @asynccontextmanager
    async def _noop_lifespan(a):
        a.state.engine = None
        a.state.session_factory = lambda: mock_session
        a.state.rule_cache = RuleCache(loaded=True)
        a.state.start_time = time.time()
        yield

    app.router.lifespan_context = _noop_lifespan

    def _override_db():
        yield mock_session

    def _override_cache():
        return RuleCache(loaded=True)

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_rule_cache] = _override_cache

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/cdgm/resolve",
            json={
                "scenario_id": "uc-camera",
                "variant_id": "UHD60-HLG",
                "dvfs_version": 4,
                "cdgm_profile_version": 1,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["dvfs_table_ref"] == "dvfs-soc-A-v4"
    assert body["arch_info_rows"][0]["role_key"] == "ISP"
