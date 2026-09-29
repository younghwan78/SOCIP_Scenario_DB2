from __future__ import annotations

import pytest

pytest.importorskip("networkx")
pytest.importorskip("simpy")

from scenario_db.sim.bw_calc import calc_port_bw
from scenario_db.sim.bw_power import (
    BW_POWER_MODELS,
    BwPowerContext,
    BwPowerSettings,
    LegacyCoeffBwModel,
    LinearPerGbpsBwModel,
    resolve_bw_power_model,
)
from scenario_db.sim.models import (
    IPSimParams,
    IPWorkload,
    PortTransferSpec,
    PortType,
    SimulationInputs,
    SimulationRunConfig,
)
from scenario_db.sim.runner import run_simulation


def _port(node_id: str, *, llc: bool = False, llc_weight: float = 1.0, w: int = 3840, h: int = 2160) -> PortTransferSpec:
    return PortTransferSpec(
        node_id=node_id,
        ip_ref=f"ip-{node_id}",
        hw_name=node_id.upper(),
        port="WDMA0",
        port_type=PortType.DMA_WRITE,
        width=w,
        height=h,
        format="YUV420",
        bitwidth=10,
        llc_enabled=llc,
        llc_weight=llc_weight,
    )


def _inputs(config: SimulationRunConfig) -> SimulationInputs:
    return SimulationInputs(
        scenario_id="uc-x",
        variant_id="v1",
        config=config,
        workloads=[
            IPWorkload(
                node_id="isp0", ip_ref="ip-isp0", hw_name="ISP0", width=1920, height=1080, fps=30.0,
                sim_params=IPSimParams(hw_name="ISP0", ppc=4, unit_power_mw_mp=10, vdd="VDD_CAM"),
            )
        ],
        port_transfers=[_port("isp0"), _port("mlsc0", llc=True, llc_weight=0.6, w=1920, h=1080)],
    )


def test_registry_lists_models_and_rejects_unknown():
    assert {"legacy-coeff", "linear-per-gbps"} <= set(BW_POWER_MODELS)
    with pytest.raises(ValueError, match="Unknown BW power model"):
        resolve_bw_power_model("nope", BwPowerSettings(bw_power_coeff=80.0))


def test_linear_per_gbps_50_mw_per_gb_s():
    model = LinearPerGbpsBwModel(mw_per_gbps=50.0)
    # 2 GB/s = 2000 MB/s -> 100 mW; unit is GB/s = 1000 MB/s.
    kwargs = dict(direction="write", llc_enabled=False, llc_weight=1.0)
    assert model.port_power_mw(bw_mbs=2000.0, **kwargs) == pytest.approx(100.0)
    assert model.port_power_mw(bw_mbs=0.0, **kwargs) == 0.0
    assert model.port_power_mw(bw_mbs=1000.0, direction="read", llc_enabled=True, llc_weight=0.5) == pytest.approx(25.0)


def test_linear_llc_hit_scale_scales_the_credited_saving():
    model = LinearPerGbpsBwModel(mw_per_gbps=50.0, llc_hit_scale=0.5)
    # llc_weight 0.6 -> saving 0.4, credited 0.2 -> factor 0.8
    got = model.port_power_mw(bw_mbs=1000.0, direction="write", llc_enabled=True, llc_weight=0.6)
    assert got == pytest.approx(40.0)


def test_default_settings_use_rule_of_thumb_50():
    model = resolve_bw_power_model("linear-per-gbps", BwPowerSettings(bw_power_coeff=80.0))
    assert isinstance(model, LinearPerGbpsBwModel)
    assert model.mw_per_gbps == 50.0


def test_legacy_coeff_is_bit_exact_with_builtin_path():
    spec = _port("isp0", llc=True, llc_weight=0.7)
    base = calc_port_bw(spec, fps=30.0, bw_power_coeff=80.0)
    via_model = calc_port_bw(spec, fps=30.0, bw_power_coeff=80.0, bw_model=LegacyCoeffBwModel(80.0))
    assert via_model.bw_power_mw == base.bw_power_mw  # exact, not approx
    assert via_model.bw_power_ma == base.bw_power_ma


def test_linear_with_matching_coefficient_is_numerically_equal():
    spec = _port("isp0", llc=True, llc_weight=0.7)
    base = calc_port_bw(spec, fps=30.0, bw_power_coeff=80.0)
    lin = calc_port_bw(spec, fps=30.0, bw_model=LinearPerGbpsBwModel(mw_per_gbps=80.0))
    assert lin.bw_power_mw == pytest.approx(base.bw_power_mw, rel=1e-12)


def test_default_run_has_no_bw_model_stamp_and_matches_legacy_alias_exactly():
    default = run_simulation(_inputs(SimulationRunConfig(fps=30.0, include_timeline=False)))
    legacy = run_simulation(
        _inputs(SimulationRunConfig(fps=30.0, include_timeline=False, bw_power_model="legacy-coeff"))
    )
    assert "bw_model" not in default.power_breakdown["model"]
    assert legacy.power_breakdown["model"]["bw_model"]["id"] == "legacy-coeff"
    assert legacy.bw_power_mw == default.bw_power_mw
    assert legacy.total_power_mw == default.total_power_mw
    assert legacy.vdd_power == default.vdd_power


def test_linear_run_uses_configured_mw_per_gbps_and_stamps_model():
    config = SimulationRunConfig(
        fps=30.0, include_timeline=False, bw_power_model="linear-per-gbps", bw_power_mw_per_gbps=50.0
    )
    result = run_simulation(_inputs(config))
    expected = sum(
        item.bw_mbs / 1000.0 * 50.0 * (item.llc_weight or 1.0) for item in result.dma_breakdown
    )
    assert result.bw_power_mw == pytest.approx(expected)
    assert result.power_breakdown["memory"]["total_mw"] == pytest.approx(expected, abs=1e-5)
    assert result.vdd_power["MIF"]["bw_mw"] == pytest.approx(expected)
    assert result.power_breakdown["model"]["bw_model"] == {
        "id": "linear-per-gbps", "version": "1.0", "mw_per_gbps": 50.0, "llc_hit_scale": 1.0,
    }


def test_aggregate_hook_can_replace_the_port_sum(monkeypatch):
    class FlatMifModel(LinearPerGbpsBwModel):
        def aggregate_power_mw(self, port_power_mw, *, context: BwPowerContext | None = None) -> float:
            assert context is not None and context.total_bw_mbs and context.memory_rail == "MIF"
            return 123.0

    monkeypatch.setitem(BW_POWER_MODELS, "flat-mif", lambda s: FlatMifModel(model_id="flat-mif"))
    result = run_simulation(
        _inputs(SimulationRunConfig(fps=30.0, include_timeline=False, bw_power_model="flat-mif"))
    )
    assert result.bw_power_mw == 123.0
    assert result.vdd_power["MIF"]["bw_mw"] == 123.0
    assert result.power_breakdown["memory"]["total_mw"] == 123.0
    assert result.total_power_mw == pytest.approx(result.core_power_mw + 123.0)


def test_unknown_bw_model_in_config_fails_loudly():
    with pytest.raises(ValueError, match="Unknown BW power model"):
        run_simulation(_inputs(SimulationRunConfig(fps=30.0, include_timeline=False, bw_power_model="x")))


def test_debug_trace_reports_the_model_formula():
    config = SimulationRunConfig(
        fps=30.0, include_timeline=False, debug_trace=True, bw_power_model="linear-per-gbps"
    )
    trace = run_simulation(_inputs(config)).calculation_trace
    assert trace is not None
    dma = trace["dma"][0]
    assert dma["bw_power_formula"] == "(bw_mbs / 1000) * mw_per_gbps * llc_factor"
    assert dma["inputs"]["bw_power_model"]["mw_per_gbps"] == 50.0
