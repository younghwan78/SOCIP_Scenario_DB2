from __future__ import annotations

import pytest

pytest.importorskip("networkx")
pytest.importorskip("simpy")

from scenario_db.sim.models import (
    IPSimParams,
    IPWorkload,
    PortTransferSpec,
    PortType,
    SimulationInputs,
    SimulationRunConfig,
)
from scenario_db.sim.power_calc import calc_active_power_mw
from scenario_db.sim.power_model import (
    POWER_MODELS,
    V1VfpsModel,
    resolve_power_model,
)
from scenario_db.sim.runner import build_simulation_evidence, run_simulation


def _workload(node_id: str, *, vdd: str, fps: float = 30.0) -> IPWorkload:
    return IPWorkload(
        node_id=node_id,
        ip_ref=f"ip-{node_id}",
        hw_name=node_id.upper(),
        width=1920,
        height=1080,
        fps=fps,
        sim_params=IPSimParams(
            hw_name=node_id.upper(), ppc=4, unit_power_mw_mp=10, vdd=vdd
        ),
    )


def _port(node_id: str) -> PortTransferSpec:
    return PortTransferSpec(
        node_id=node_id,
        ip_ref=f"ip-{node_id}",
        hw_name=node_id.upper(),
        port="WDMA0",
        port_type=PortType.DMA_WRITE,
        width=1920,
        height=1080,
        format="YUV420",
        bitwidth=8,
    )


def _inputs(config: SimulationRunConfig | None = None) -> SimulationInputs:
    return SimulationInputs(
        scenario_id="uc-x",
        variant_id="v1",
        config=config or SimulationRunConfig(fps=30.0, include_timeline=False),
        workloads=[_workload("isp0", vdd="VDD_CAM"), _workload("dpu0", vdd="VDD_DPU")],
        port_transfers=[_port("isp0"), _port("dpu0")],
    )


def test_registry_resolves_default_and_rejects_unknown():
    model = resolve_power_model(None)
    assert model.model_id == "v1-vfps"
    assert "v1-vfps" in POWER_MODELS
    with pytest.raises(ValueError, match="Unknown power model"):
        resolve_power_model("no-such-model")


def test_v1_model_matches_legacy_formulas():
    model = V1VfpsModel()
    assert model.ip_active_power_mw(
        unit_power_mw_mp=10.0, resolution_mp=2.0736, voltage_mv=710.0, fps=30.0
    ) == pytest.approx(
        calc_active_power_mw(
            unit_power_mw_mp=10.0, resolution_mp=2.0736, voltage_mv=710.0, fps=30.0
        )
    )
    # Memory: BW · coeff / 1000 · llc_weight
    assert model.memory_transfer_power_mw(
        bw_mbs=1000.0, bw_power_coeff=80.0, llc_weight=0.5
    ) == pytest.approx(40.0)
    assert model.memory_transfer_power_mw(
        bw_mbs=0.0, bw_power_coeff=80.0, llc_weight=1.0
    ) == 0.0


def test_runner_emits_three_bucket_power_breakdown_with_model_stamp():
    result = run_simulation(_inputs(), dvfs_tables={})

    bd = result.power_breakdown
    assert bd["model"] == {"id": "v1-vfps", "version": "1.0"}
    assert set(bd) == {"model", "ip", "memory", "cpu", "total_mw"}
    assert bd["ip"]["total_mw"] == pytest.approx(result.core_power_mw, abs=1e-6)
    assert bd["memory"]["total_mw"] == pytest.approx(result.bw_power_mw, abs=1e-6)
    assert bd["cpu"] == {"total_mw": 0.0, "by_cluster": {}}
    assert bd["total_mw"] == pytest.approx(result.total_power_mw, abs=1e-6)
    assert set(bd["ip"]["by_rail"]) == {"VDD_CAM", "VDD_DPU"}
    assert set(bd["ip"]["by_node"]) == {"isp0", "dpu0"}


def test_bw_power_is_attributed_to_the_memory_rail_not_ip_rails():
    """Measured captures see DRAM/interconnect power on the MIF buck; the
    simulation must attribute it the same way or per-rail calibration
    factors compare structurally different quantities."""
    config = SimulationRunConfig(fps=30.0, include_timeline=False, memory_rail="MIF")
    result = run_simulation(_inputs(config), dvfs_tables={})

    assert result.vdd_power["VDD_CAM"]["bw_mw"] == 0.0
    assert result.vdd_power["VDD_DPU"]["bw_mw"] == 0.0
    assert result.vdd_power["MIF"]["core_mw"] == 0.0
    assert result.vdd_power["MIF"]["bw_mw"] == pytest.approx(result.bw_power_mw)
    assert result.vdd_power["MIF"]["total_mw"] == pytest.approx(result.bw_power_mw)
    # scenario total is attribution-invariant
    rail_sum = sum(rail["total_mw"] for rail in result.vdd_power.values())
    assert rail_sum == pytest.approx(result.total_power_mw, abs=1e-6)
    assert result.power_breakdown["memory"]["rail"] == "MIF"


def test_memory_rail_is_configurable_per_run():
    config = SimulationRunConfig(fps=30.0, include_timeline=False, memory_rail="VDD_MIF_L")
    result = run_simulation(_inputs(config), dvfs_tables={})
    assert "VDD_MIF_L" in result.vdd_power
    assert result.power_breakdown["memory"]["rail"] == "VDD_MIF_L"


def test_unknown_power_model_in_config_fails_loudly():
    config = SimulationRunConfig(fps=30.0, include_timeline=False, power_model="v9-nope")
    with pytest.raises(ValueError, match="Unknown power model"):
        run_simulation(_inputs(config), dvfs_tables={})


def test_evidence_carries_power_breakdown():
    from scenario_db.models.evidence.common import ExecutionContext

    result = run_simulation(_inputs(), dvfs_tables={})
    evidence = build_simulation_evidence(
        result,
        execution_context=ExecutionContext(
            silicon_rev="EVT1", sw_baseline_ref="sw-x", thermal="room"
        ),
    )
    assert evidence.power_breakdown is not None
    assert evidence.power_breakdown["model"]["id"] == "v1-vfps"
    assert evidence.power_breakdown["total_mw"] == pytest.approx(result.total_power_mw)
