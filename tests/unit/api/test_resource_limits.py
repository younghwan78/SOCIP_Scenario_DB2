from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from scenario_db.api.resource_limits import (
    admission_slot,
    enforce_request_size,
    enforce_timeline_frame_limit,
)
from scenario_db.sim.exploration import ExplorationSweep, compile_exploration_sweep
from scenario_db.sim.resource_limits import enforce_sweep_case_limit
from scenario_db.sim import service as simulation_service
from scenario_db.exceptions import UnprocessableError


class _Request(BaseModel):
    source_yaml: str


def test_admission_slot_rejects_when_operation_is_at_capacity():
    with admission_slot("unit-test-capacity", 1):
        with pytest.raises(HTTPException) as exc_info:
            with admission_slot("unit-test-capacity", 1):
                pass

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers == {"Retry-After": "1"}


def test_request_size_is_measured_as_utf8_bytes():
    with pytest.raises(HTTPException) as exc_info:
        enforce_request_size(_Request(source_yaml="한글"), max_bytes=10)

    assert exc_info.value.status_code == 413


def test_timeline_frame_limit_rejects_oversized_run():
    with pytest.raises(HTTPException) as exc_info:
        enforce_timeline_frame_limit(121, max_frames=120)

    assert exc_info.value.status_code == 422


def test_sweep_case_limit_rejects_cartesian_product_before_expansion():
    axes = [
        {"name": "a", "values": [1, 2, 3]},
        {"name": "b", "values": [1, 2, 3]},
    ]

    with pytest.raises(ValueError, match="maximum 8"):
        enforce_sweep_case_limit(axes, max_cases=8)


def test_exploration_compiler_applies_configured_case_limit():
    sweep = ExplorationSweep.model_validate(
        {
            "id": "bounded",
            "base_recipe": {
                "id": "bounded",
                "project_ref": "project",
                "source": {"width": 1920, "height": 1080},
                "pipeline": [{"id": "isp0", "template": "isp"}],
            },
            "axes": [
                {"name": "fps", "path": "source.fps", "values": [24, 30, 60]},
                {"name": "format", "path": "source.format", "values": ["RAW", "YUV"]},
            ],
        }
    )

    with pytest.raises(ValueError, match="maximum 5"):
        compile_exploration_sweep(sweep, max_cases=5)


def test_simulation_input_component_limit_is_enforced(monkeypatch):
    settings = SimpleNamespace(
        simulation_max_workloads=1,
        simulation_max_port_transfers=5,
        simulation_max_timeline_tasks=5,
        simulation_max_timeline_edges=5,
    )
    monkeypatch.setattr(simulation_service, "get_settings", lambda: settings)
    inputs = SimpleNamespace(
        workloads=[object(), object()],
        port_transfers=[],
        timeline_tasks=[],
        timeline_edges=[],
    )

    with pytest.raises(UnprocessableError, match="2 workloads"):
        simulation_service._enforce_input_limits(inputs)
