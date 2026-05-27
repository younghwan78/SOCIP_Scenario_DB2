from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from scenario_db.api.routers import view as view_router
from scenario_db.api.schemas.view import ViewResponse, ViewSummary


def _view_response() -> ViewResponse:
    return ViewResponse(
        level=0,
        scenario_id="uc-camera-recording",
        variant_id="FHD30-SDR-H265",
        mode="topology",
        nodes=[],
        edges=[],
        summary=ViewSummary(
            scenario_id="uc-camera-recording",
            variant_id="FHD30-SDR-H265",
            name="Camera",
            subtitle="FHD30",
            period_ms=33.3,
            budget_ms=30.0,
            resolution="1920x1080",
            fps=30,
            variant_label="FHD30",
        ),
    )


def test_specific_simulation_overlay_rejects_evidence_for_another_variant(monkeypatch):
    evidence = SimpleNamespace(
        id="sim-other",
        kind="evidence.simulation",
        scenario_ref="uc-other",
        variant_ref="OTHER",
    )
    monkeypatch.setattr(view_router, "get_evidence", lambda db, evidence_id: evidence)

    with pytest.raises(HTTPException) as exc_info:
        view_router._apply_optional_sim_overlay(
            _view_response(),
            db=object(),
            scenario_id="uc-camera-recording",
            variant_id="FHD30-SDR-H265",
            sim="none",
            sim_evidence_id="sim-other",
        )

    assert exc_info.value.status_code == 409
    assert "does not match" in str(exc_info.value.detail)


def test_level0_view_rejects_unknown_mode(monkeypatch):
    monkeypatch.setattr(view_router, "project_level0", lambda *args, **kwargs: _view_response())

    with pytest.raises(HTTPException) as exc_info:
        view_router._build_view(
            "uc-camera-recording",
            "FHD30-SDR-H265",
            level=0,
            mode="typo",
            expand=None,
            sim="none",
            sim_evidence_id=None,
            db=object(),
        )

    assert exc_info.value.status_code == 422
    assert "mode" in str(exc_info.value.detail)
