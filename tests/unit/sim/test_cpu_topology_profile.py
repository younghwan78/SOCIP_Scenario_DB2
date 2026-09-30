"""CPU topology (variable clusters + DSU), configurable PMU table import and
profile-based CPU power (measured placement)."""
from __future__ import annotations

import math
import pathlib
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

pytest.importorskip("networkx")
pytest.importorskip("simpy")

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_is_v15_camera import graph_from_fixture, read  # noqa: E402

from scenario_db.api.schemas.simulation import SimulateRequest  # noqa: E402
from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.exceptions import NotFoundError, UnprocessableError  # noqa: E402
from scenario_db.meas_import.meta import PmuSpec  # noqa: E402
from scenario_db.meas_import.pmu_digest import PmuSample, build_pmu_digest, expand_cpu_map, import_pmu_digest  # noqa: E402
from scenario_db.meas_import.table_adapter import TableSpec  # noqa: E402
from scenario_db.models.capability.power_model import PowerModelParams  # noqa: E402
from scenario_db.sim.adapter import build_simulation_inputs  # noqa: E402
from scenario_db.sim.cpu_power import CpuPowerModel, profile_cpu_power  # noqa: E402
from scenario_db.sim.cpu_profile import cpu_profile_from_evidence, cpu_profile_from_observations  # noqa: E402
from scenario_db.sim.models import CpuClusterProfile, CpuProfile, CpuTaskProfile, SimulationRunConfig  # noqa: E402
from scenario_db.sim.runner import run_simulation  # noqa: E402
from scenario_db.sim.service import _apply_cpu_profile  # noqa: E402
from scenario_db.sim.timing_budget import CpuPowerConfig  # noqa: E402

TOPO = ROOT / "examples" / "cpu-topology"
SAMPLE = ROOT / "examples" / "measurement-import" / "cpu-profile-sample"
DB = ROOT / "db_Exynos2700_SM-S957B"


def _params(soc: str) -> PowerModelParams:
    return PowerModelParams.model_validate(yaml.safe_load((TOPO / f"pmp-{soc}-cpu-example.yaml").read_text()))


def _sample_spec() -> PmuSpec:
    return PmuSpec.model_validate(yaml.safe_load((SAMPLE / "meta.yaml").read_text())["pmu"])


@pytest.fixture(scope="module")
def profile() -> CpuProfile:
    digest = import_pmu_digest(SAMPLE, _sample_spec())
    prof = cpu_profile_from_observations(digest.observations, evidence_ref="meas-sample")
    assert prof is not None
    return prof


@pytest.fixture(scope="module")
def graph():
    catalog = {}
    for path in (DB / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="f")
    raw = read(DB / "02_definition" / "uc-cam-recording-e2700.yaml")
    return lambda variant: graph_from_fixture(raw, variant, catalog)


# --- topology -----------------------------------------------------------------------
@pytest.mark.parametrize("soc, names", [
    ("exynos2600", ["MID_LF0", "MID_LF1", "MID_HF", "BIG"]),
    ("exynos2700", ["MID_LF", "MID_HF", "BIG_LF", "BIG"]),
    ("exynos2800", ["MID_HF0", "MID_HF1", "BIG_LF", "BIG"]),
])
def test_example_topologies_load_with_their_own_cluster_composition(soc, names):
    model = CpuPowerModel.from_params(_params(soc))
    assert list(model.cluster_names) == names and model.dsu is not None
    assert model.rail_for(names[0]) == f"BUCK_{names[0]}" and model.rail_for("DSU") == "BUCK_DSU"
    # EM clusters expose an equivalent uW/MHz/V^2 at the default frequency (timing budget)
    cfg = CpuPowerConfig.from_params(_params(soc))
    assert cfg is not None and len(cfg.coeff_uw_per_mhz_v2) == 4 and all(c > 0 for c in cfg.coeff_uw_per_mhz_v2)


def test_topology_validation():
    base = {"id": "pmp-x", "schema_version": "2.2", "kind": "power_model_params", "soc_ref": "soc-x"}
    with pytest.raises(ValueError, match="cpus must not overlap"):
        PowerModelParams.model_validate({**base, "cpu": {"clusters": [
            {"name": "a", "coeff_uw_per_mhz_v2": 1, "cores": 1, "cpus": [0]},
            {"name": "b", "coeff_uw_per_mhz_v2": 1, "cores": 1, "cpus": [0]}]}})
    with pytest.raises(ValueError, match="sorted"):
        PowerModelParams.model_validate({**base, "cpu": {"clusters": [{"name": "a", "opps": [
            {"mhz": 2000, "mv": 800, "mw_per_core": 2}, {"mhz": 1000, "mv": 700, "mw_per_core": 1}]}]}})
    with pytest.raises(ValueError, match="default_cluster"):
        PowerModelParams.model_validate({**base, "cpu": {"default_cluster": 3, "clusters": [{"name": "a", "coeff_uw_per_mhz_v2": 1}]}})


# --- import -------------------------------------------------------------------------
def test_table_sources_become_a_per_frame_profile(profile):
    tasks = {(t.task, t.cluster): t for t in profile.tasks}
    assert {("eis", "MID_HF"), ("post_irta", "MID_HF"), ("post_crta", "MID_LF"), ("mpeg_writer", "MID_LF"),
            ("(other)", "MID_LF")} <= set(tasks)
    eis = tasks[("eis", "MID_HF")]
    assert eis.cycles == pytest.approx(6.5e6, rel=0.12)          # per frame (900 frames)
    assert eis.instructions / eis.cycles == pytest.approx(1.3, rel=1e-3)
    assert eis.bus_bytes == pytest.approx(eis.instructions / 1000 * 1500, rel=1e-3)  # bus_access x 64
    mid_lf = profile.clusters["MID_LF"]
    assert mid_lf.freq_residency == pytest.approx({400.0: 0.55, 1000.0: 0.35, 1600.0: 0.10})
    assert (mid_lf.clock_gated_ratio, mid_lf.power_gated_ratio) == pytest.approx((0.40, 0.30))
    assert profile.clusters["BIG"].power_gated_ratio == pytest.approx(0.98)


def test_wide_layout_filters_headerless_columns_and_task_policies(tmp_path):
    (tmp_path / "w.csv").write_text("t0,4,1000,2000,10\nt1,5,500,500,\nnoise,4,1,1,1\n")
    spec = TableSpec.model_validate({"sources": [{
        "file": "w.csv", "columns": ["thread", "cpu", "cyc", "inst", "acc"], "layout": "wide",
        "counters": {"cycles": ["cyc"], "instructions": ["inst"], "bus_access": ["acc"]},
        "cpu": {"column": "cpu"}, "task": {"column": "thread"},
        "task_rules": [{"match": "^t", "task": "worker"}], "unmapped_task": "drop",
        "filter": {"thread": "^(t|noise)"},
    }]})
    spec_pmu = PmuSpec(format="table", table=spec, cpu_map={"4-5": "MID_HF"}, window={"frames": 10})
    digest = import_pmu_digest(tmp_path, spec_pmu)
    obs = {(o["metric_id"], o["scope"]["ref"]): o["value"] for o in digest.observations}
    assert obs[("cpu.cycles_pf", "worker@MID_HF")] == 150.0     # (1000 + 500) / 10 frames
    assert ("cpu.bus_bytes_pf", "worker@MID_HF") not in obs    # bus_access needs bytes_per_access
    assert any("bytes_per_access" in w for w in digest.warnings)
    assert any("noise" in w for w in digest.warnings)           # dropped, reported


def test_neutral_format_cpu_scopes_ranges_and_missing_window():
    assert expand_cpu_map({"0-2": "A", "5": "B", "6,7": "C"}) == {0: "A", 1: "A", 2: "A", 5: "B", 6: "C", 7: "C"}
    samples = [
        PmuSample("cpu_cycles", "task_cpu", "eis@cpu4", 900.0, line=1),
        PmuSample("cpu_cycles", "task_cluster", "eis@MID_HF", 900.0, line=2),
        PmuSample("cpu_cycles", "cpu", "cpu9", 5.0, line=3),
        PmuSample("cpu_freq_time", "cluster", "MID_HF", 3.0, freq_mhz=1200.0, line=4),
        PmuSample("cpu_freq_time", "cluster", "MID_HF", 1.0, freq_mhz=600.0, line=5),
    ]
    digest = build_pmu_digest(samples, cpu_map={"4-7": "MID_HF"}, frames=9)
    obs = {(o["metric_id"], o["scope"]["ref"]): o["value"] for o in digest.observations}
    assert obs[("cpu.cycles_pf", "eis@MID_HF")] == 200.0          # both rows land on one scope
    assert obs[("cpu.freq_residency", "MID_HF@1200")] == 0.75
    assert any("cpu_map" in w and "cpu9" in w for w in digest.warnings)
    nowin = build_pmu_digest(samples[:1], cpu_map={"4": "MID_HF"})
    assert any("pmu.window" in w for w in nowin.warnings)


def test_cli_imports_the_example_bundle(tmp_path):
    out = subprocess.run(
        [sys.executable, "-m", "scenario_db.meas_import.cli", "--meta", str(SAMPLE / "meta.yaml"),
         "--out", str(tmp_path), "--strict"], capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stdout + out.stderr
    doc = yaml.safe_load(next(tmp_path.rglob("meas-*.yaml")).read_text())
    assert cpu_profile_from_evidence(doc) is not None
    assert sum(1 for a in doc["artifacts"] if a["type"] == "pmu_digest") == 3


# --- model --------------------------------------------------------------------------
def test_profile_energy_static_and_dsu_math():
    params = PowerModelParams.model_validate({
        "id": "pmp-t", "schema_version": "2.2", "kind": "power_model_params", "soc_ref": "soc-x",
        "cpu": {"clusters": [{"name": "C", "cores": 2, "opps": [
            {"mhz": 1000, "mv": 700, "mw_per_core": 100}, {"mhz": 2000, "mv": 800, "mw_per_core": 300}],
            "leakage": {"mw_per_core_at_ref": 10, "ref_mv": 800, "exponent": 2}}],
            "dsu": {"opps": [{"mhz": 1000, "mv": 700, "mw_per_core": 50}]}}})
    model = CpuPowerModel.from_params(params)
    prof = CpuProfile(
        tasks=[CpuTaskProfile(task="t", cluster="C", cycles=1e7)],
        clusters={"C": CpuClusterProfile(cycles=1.5e7, freq_residency={1000.0: 1, 2000.0: 1},
                                          clock_gated_ratio=0.2, power_gated_ratio=0.5)},
    )
    out = profile_cpu_power(prof, model=model, period_ms=10.0)
    e = 0.5 * 100 / 1000 + 0.5 * 300 / 2000                     # nJ / cycle
    rows = {r["task"]: r for r in out["tasks"]}
    assert rows["t"]["power_mw"] == pytest.approx(1e7 * e / 10 / 1000)
    assert rows["(other)"]["cycles_per_frame"] == pytest.approx(5e6)
    leak = 0.5 * 10 * (700 / 800) ** 2 + 0.5 * 10
    assert out["clusters"]["C"]["static_mw"] == pytest.approx(2 * leak * 0.5)
    assert out["dsu"]["active_ratio"] == pytest.approx(0.3)      # 1 - cg - pg of the busiest cluster
    assert out["dsu"]["dynamic_mw"] == pytest.approx(50 * 0.3)
    assert math.isclose(out["clusters"]["C"]["mean_mhz"], 1500.0)


def test_runner_uses_the_measured_profile_and_topology_rails(graph, profile):
    params = _params("exynos2700")
    result = run_simulation(build_simulation_inputs(graph("cam-rec-r1-uhd30-vdis"),
                                                    SimulationRunConfig(power_params=params, cpu_profile=profile)))
    cpu = result.power_breakdown["cpu"]
    assert cpu["source"] == "pmu_profile" and cpu["profile_ref"] == "meas-sample"
    assert set(cpu["by_cluster"]) == {"MID_LF", "MID_HF", "BIG_LF", "BIG", "DSU"}
    assert result.cpu_power_mw == pytest.approx(sum(cpu["by_cluster"].values()))
    assert result.total_power_mw == pytest.approx(result.core_power_mw + result.bw_power_mw + result.cpu_power_mw)
    assert {"BUCK_MID_HF", "BUCK_DSU"} <= set(result.vdd_power)
    assert cpu["by_task"]["eis"] > 0 and "(other)" in cpu["by_task"]
    # BIG cores are 98% power gated in the sample: leakage only
    assert cpu["clusters"]["BIG"]["dynamic_mw"] == 0.0 and cpu["clusters"]["BIG"]["static_mw"] > 0


def test_profile_from_another_variant_is_flagged(graph, profile):
    foreign = profile.model_copy(update={"scenario_ref": "uc-cam-recording-e2600", "variant_ref": "cam-rec-r1-uhd30-vdis"})
    result = run_simulation(build_simulation_inputs(graph("cam-rec-r1-uhd30-vdis"),
                                                    SimulationRunConfig(power_params=_params("exynos2700"), cpu_profile=foreign)))
    assert any("was measured on uc-cam-recording-e2600" in w for w in result.warnings)


class _Db:
    def __init__(self, row):
        self.row = row

    def query(self, *_):
        return self

    def filter_by(self, **_):
        return self

    def one_or_none(self):
        return self.row


def test_service_resolves_cpu_profile_ref(profile):
    obs = import_pmu_digest(SAMPLE, _sample_spec()).observations
    row = SimpleNamespace(kind="evidence.measurement", scenario_ref="s", variant_ref="v",
                          metric_observations=obs, cpu_breakdown=None)
    request = SimulateRequest.model_validate({
        "scenario_id": "s", "variant_id": "v",
        "execution_context": {"silicon_rev": "EVT0", "sw_baseline_ref": "sw-x", "thermal": "room"},
        "config": {"cpu_profile_ref": "meas-x"}})
    _apply_cpu_profile(_Db(row), request)
    assert request.config.cpu_profile.evidence_ref == "meas-x" and request.config.cpu_profile.variant_ref == "v"
    with pytest.raises(NotFoundError):
        _apply_cpu_profile(_Db(None), SimulateRequest.model_validate({**request.model_dump(), "config": {"cpu_profile_ref": "x"}}))
    empty = SimpleNamespace(kind="evidence.measurement", scenario_ref="s", variant_ref="v", metric_observations=[], cpu_breakdown=None)
    with pytest.raises(UnprocessableError, match="no per-frame CPU profile"):
        _apply_cpu_profile(_Db(empty), SimulateRequest.model_validate({**request.model_dump(), "config": {"cpu_profile_ref": "x"}}))


@pytest.mark.parametrize("residency", [{0: 1}, {-1: 1}, {1000: -1}, {1000: 0},
                                        {float("inf"): 1}, {1000: float("nan")}, {1000: float("inf")}])
def test_cpu_and_dsu_profiles_reject_invalid_residency(residency):
    from scenario_db.sim.models import CpuDsuProfile

    for model in (CpuClusterProfile, CpuDsuProfile):
        with pytest.raises(ValueError, match="residency"):
            model(freq_residency=residency)


def test_task_only_profile_keeps_task_energy_and_case_insensitive_cluster():
    model = CpuPowerModel()
    prof = CpuProfile(tasks=[CpuTaskProfile(task="t", cluster="MID", cycles=1e6)])
    out = profile_cpu_power(prof, model=model, period_ms=10)
    assert out["clusters"]["mid"]["dynamic_mw"] > 0
    assert out["tasks"][0]["cycles_per_frame"] == 1e6
    with pytest.raises(ValueError, match="unique"):
        CpuProfile(clusters={"mid": CpuClusterProfile(), "MID": CpuClusterProfile()})


def test_timing_budget_and_runner_agree_at_cluster_opp_voltage():
    params = PowerModelParams.model_validate({
        "id": "pmp-t", "schema_version": "2.2", "kind": "power_model_params", "soc_ref": "soc-x",
        "cpu": {"freq_mhz": 1000, "volt_v": 0.8, "clusters": [
            {"name": "C", "opps": [{"mhz": 1000, "mv": 600, "mw_per_core": 100}]}]},
    })
    model, config = CpuPowerModel.from_params(params), CpuPowerConfig.from_params(params)
    assert config.power_mw(5, 10) == pytest.approx(model.task_power_mw(5, 10))


def test_incomplete_or_duplicate_opp_tables_are_rejected():
    from scenario_db.models.capability.power_model import CpuClusterParams, CpuDsuParams

    incomplete = [{"mhz": 1000, "mv": 600, "mw_per_core": 100}, {"mhz": 2000, "mv": 800}]
    with pytest.raises(ValueError, match="mw_per_core"):
        CpuClusterParams(name="C", opps=incomplete)
    with pytest.raises(ValueError, match="mw_per_core"):
        CpuDsuParams(opps=incomplete)
    with pytest.raises(ValueError, match="unique"):
        CpuClusterParams(name="C", opps=[incomplete[0], incomplete[0]])
    with pytest.raises(ValueError, match="sorted"):
        CpuDsuParams(opps=[{"mhz": 2000, "mv": 800, "mw_per_core": 200}, incomplete[0]])


def test_cpu_profile_ref_uses_topology_dsu_name():
    params = _params("exynos2700").model_copy(deep=True)
    params.cpu.dsu.name = "SHARED"
    row = SimpleNamespace(kind="evidence.measurement", scenario_ref="s", variant_ref="v", cpu_breakdown=None,
                          metric_observations=[{"metric_id": "cpu.active_ratio", "scope": {"kind": "cluster", "ref": "SHARED"}, "value": 0.2}])
    request = SimulateRequest.model_validate({
        "scenario_id": "s", "variant_id": "v",
        "execution_context": {"silicon_rev": "EVT0", "sw_baseline_ref": "sw-x", "thermal": "room"},
        "config": {"cpu_profile_ref": "meas-x", "power_params": params}})
    _apply_cpu_profile(_Db(row), request)
    assert request.config.cpu_profile.dsu.active_ratio == 0.2
    assert "SHARED" not in request.config.cpu_profile.clusters


def test_table_nonfinite_counter_and_frequency_are_rejected(tmp_path):
    from scenario_db.meas_import.pmu_digest import PmuDigestError

    samples = [PmuSample("cpu_freq_time", "cluster", "C", 1, freq_mhz=float("inf"))]
    with pytest.raises(PmuDigestError, match="freq_mhz"):
        build_pmu_digest(samples)
    (tmp_path / "bad.csv").write_text("cycles\ninf\n")
    spec = PmuSpec(format="table", table={"sources": [{
        "file": "bad.csv", "layout": "wide", "counters": {"cycles": []}, "cluster": {"value": "C"}}]},
        window={"frames": 10})
    with pytest.raises(PmuDigestError, match="finite"):
        import_pmu_digest(tmp_path, spec)


def test_cpu_bw_from_the_profile_enters_dma_and_bw_power(graph, profile):
    params = _params("exynos2700")
    on = run_simulation(build_simulation_inputs(graph("cam-rec-r1-uhd30-vdis"),
                                                SimulationRunConfig(power_params=params, cpu_profile=profile)))
    off = run_simulation(build_simulation_inputs(graph("cam-rec-r1-uhd30-vdis"),
                                                 SimulationRunConfig(power_params=params, cpu_profile=profile,
                                                                     include_cpu_bw=False)))
    cpu_ports = [d for d in on.dma_breakdown if d.node_id.startswith("cpu.")]
    expected = sum(t.bus_bytes or 0 for t in profile.tasks) * 30 / 1e6
    assert sum(d.bw_mbs for d in cpu_ports) == pytest.approx(expected, rel=1e-6)
    assert on.bw_total_mbs == pytest.approx(off.bw_total_mbs + expected, rel=1e-6)
    assert on.bw_power_mw > off.bw_power_mw
    assert not any(d.node_id.startswith("cpu.") for d in off.dma_breakdown)
