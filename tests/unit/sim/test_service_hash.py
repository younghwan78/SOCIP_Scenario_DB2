from __future__ import annotations

from scenario_db.api.schemas.simulation import SimulateRequest
from scenario_db.sim.models import SimulationInputs, SimulationRunConfig
from scenario_db.sim.service import _request_hash


def test_request_hash_changes_with_execution_context() -> None:
    inputs = _inputs()
    baseline = _request_hash(inputs, _request(thermal="normal", ambient_temp_c=25.0))
    hot = _request_hash(inputs, _request(thermal="hot", ambient_temp_c=85.0))

    assert baseline != hot


def test_request_hash_ignores_persist_and_force_flags() -> None:
    inputs = _inputs()
    baseline = _request_hash(inputs, _request(persist=True, force=False))
    transient_forced = _request_hash(inputs, _request(persist=False, force=True))

    assert baseline == transient_forced


def test_request_hash_ignores_debug_trace_flags() -> None:
    inputs = _inputs()
    baseline = _request_hash(inputs, _request())
    debug = _request_hash(
        inputs,
        _request(config=SimulationRunConfig(asv_group=4, include_timeline=True, debug_trace=True, debug_trace_level="full")),
    )

    assert baseline == debug


def test_request_hash_changes_with_dvfs_table_ref() -> None:
    inputs = _inputs()
    baseline = _request_hash(inputs, _request(dvfs_table_ref="dvfs-soc-exynos2700-v4"))
    updated = _request_hash(inputs, _request(dvfs_table_ref="dvfs-soc-exynos2700-v5"))

    assert baseline != updated


def _inputs() -> SimulationInputs:
    return SimulationInputs(
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-f1-fhd30",
        project_ref="proj-sm-s947b",
        config=SimulationRunConfig(asv_group=4, include_timeline=True),
    )


def _request(
    *,
    thermal: str = "normal",
    ambient_temp_c: float = 25.0,
    persist: bool = True,
    force: bool = False,
    config: SimulationRunConfig | None = None,
    dvfs_table_ref: str | None = None,
) -> SimulateRequest:
    return SimulateRequest(
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-f1-fhd30",
        execution_context={
            "silicon_rev": "EVT0",
            "sw_baseline_ref": "sw-vendor-v1.2.3",
            "thermal": thermal,
            "ambient_temp_c": ambient_temp_c,
        },
        config=config or SimulationRunConfig(asv_group=4, include_timeline=True),
        dvfs_table_ref=dvfs_table_ref,
        persist=persist,
        force=force,
    )
