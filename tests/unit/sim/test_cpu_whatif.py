"""CPU placement / frequency what-if (stall-split time model) and CPU BW."""
from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest
import yaml

from scenario_db.api.schemas.cpu import CpuWhatIfRequest
from scenario_db.api.services.cpu import run_cpu_whatif
from scenario_db.exceptions import UnprocessableError
from scenario_db.models.capability.power_model import PowerModelParams
from scenario_db.sim.cpu_power import CpuPowerModel
from scenario_db.sim.cpu_whatif import WhatIfSpec, cpu_whatif
from scenario_db.sim.models import CpuClusterProfile, CpuProfile, CpuTaskProfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
TOPO = ROOT / "examples" / "cpu-topology"


def _params(**cpu) -> PowerModelParams:
    return PowerModelParams.model_validate({
        "id": "pmp-t", "schema_version": "2.2", "kind": "power_model_params", "soc_ref": "soc-x", "cpu": cpu})


def _two_cluster(**extra) -> CpuPowerModel:
    return CpuPowerModel.from_params(_params(clusters=[
        {"name": "LITTLE", "core_type": "L", "cores": 2, "ipc_rel": 0.5, "opps": [
            {"mhz": 500, "mv": 600, "mw_per_core": 20}, {"mhz": 1000, "mv": 700, "mw_per_core": 50}],
         "leakage": {"mw_per_core_at_ref": 2, "ref_mv": 700}},
        {"name": "BIG", "core_type": "B", "cores": 2, "ipc_rel": 1.0, "opps": [
            {"mhz": 1000, "mv": 700, "mw_per_core": 150}, {"mhz": 2000, "mv": 850, "mw_per_core": 450}],
         "leakage": {"mw_per_core_at_ref": 10, "ref_mv": 700}}], default_cluster=0, **extra))


def _profile(stall=2e6) -> CpuProfile:
    # 5e6 cycles per frame on BIG at 1000 MHz = 5 ms, of which stall 2 ms
    return CpuProfile(
        tasks=[CpuTaskProfile(task="eis", cluster="BIG", cycles=5e6, stall_cycles=stall, bus_bytes=1e6)],
        clusters={"BIG": CpuClusterProfile(cycles=5e6, freq_residency={1000.0: 1.0})},
    )


def test_stall_split_time_model_and_opp_choice():
    model = _two_cluster()
    # 33.3 ms period: BIG@1000 easily fits -> lowest-power OPP is 1000 MHz, time = 3 ms core + 2 ms stall
    r = cpu_whatif(_profile(), target=model, fps=30, spec=WhatIfSpec())
    big = r["base"]["clusters"]["BIG"]
    assert big["mhz"] == 1000 and big["tasks_ms"]["eis"] == pytest.approx(5.0)
    # a tight budget forces 2000 MHz: only the core part halves -> 1.5 + 2.0 ms
    r = cpu_whatif(_profile(), target=model, fps=30, spec=WhatIfSpec(budgets_ms={"eis": 4.0}))
    big = r["base"]["clusters"]["BIG"]
    assert big["mhz"] == 2000 and big["tasks_ms"]["eis"] == pytest.approx(3.5)
    assert r["base"]["min_slack_ms"] == pytest.approx(0.5)


def test_moving_to_a_lower_ipc_cluster_and_growth():
    model = _two_cluster()
    r = cpu_whatif(_profile(), target=model, fps=30,
                   spec=WhatIfSpec(candidates={"eis": ["LITTLE", "BIG"]}, growth={"eis": 1.2}))
    little = next(c for c in r["cases"] if c["placement"]["eis"] == "LITTLE")
    # core cycles 3e6 * 1.2 growth * (1.0 / 0.5 IPC) = 7.2e6 at the chosen OPP, + stall 2 ms * 1.2
    cl = little["clusters"]["LITTLE"]
    assert cl["mhz"] == 500  # fits the frame at the lowest-power OPP
    assert cl["tasks_ms"]["eis"] == pytest.approx(7.2e6 / (500 * 1000) + 2.4)
    assert r["case_count"] == 2 and r["cases"][0]["total_mw"] <= r["cases"][1]["total_mw"]
    assert r["base"]["cpu_bw_mbs"] == pytest.approx(1e6 * 1.2 * 30 / 1e6)
    assert "eis" in r["tasks"] and r["measured_mw"] is not None


def test_infeasible_reports_fastest_level_and_limits():
    model = _two_cluster()
    r = cpu_whatif(_profile(), target=model, fps=30, spec=WhatIfSpec(budgets_ms={"eis": 1.0}))
    assert not r["base"]["feasible"] and r["base"]["clusters"]["BIG"]["mhz"] == 2000
    with pytest.raises(ValueError, match="unknown target clusters"):
        cpu_whatif(_profile(), target=model, fps=30, spec=WhatIfSpec(candidates={"eis": ["PRIME"]}))
    with pytest.raises(ValueError, match="max_cases"):
        cpu_whatif(_profile(), target=model, fps=30, spec=WhatIfSpec(candidates={"eis": ["LITTLE", "BIG"]}, max_cases=1))
    r = cpu_whatif(_profile(stall=None), target=model, fps=30)
    assert any("no stall_cycles" in w for w in r["warnings"])


def test_cross_soc_mapping_by_core_type():
    load = lambda soc: CpuPowerModel.from_params(PowerModelParams.model_validate(  # noqa: E731
        yaml.safe_load((TOPO / f"pmp-{soc}-cpu-example.yaml").read_text())))
    prof = CpuProfile(tasks=[CpuTaskProfile(task="t", cluster="MID_HF", cycles=1e6, stall_cycles=1e5)],
                      clusters={"MID_HF": CpuClusterProfile(cycles=1e6)})
    r = cpu_whatif(prof, target=load("exynos2800"), base=load("exynos2700"), fps=30)
    assert r["base"]["placement"]["t"] == "MID_HF0"      # same core type on the 2800 topology
    assert r["measured_mw"] is None                        # measured reference only on the same SoC


class _Db:
    def __init__(self, params_row, evidence_row=None):
        self.params_row, self.evidence_row = params_row, evidence_row

    def get(self, _model, _id):
        return self.params_row

    def query(self, *_):
        return self

    def filter_by(self, **_):
        return self

    def one_or_none(self):
        return self.evidence_row


def test_api_service_runs_with_inline_profile():
    params = _params(clusters=[{"name": "BIG", "opps": [{"mhz": 1000, "mv": 700, "mw_per_core": 150}]}])
    row = SimpleNamespace(id="pmp-t", schema_version="2.2", soc_ref="soc-x", version=1, status="draft",
                          description=None, notes=None,
                          params=params.model_dump(mode="json", exclude_none=True,
                                                   include={"ip_model", "cpu", "bw", "calibration"}))
    req = CpuWhatIfRequest(cpu_profile=_profile(), power_params_ref="pmp-t")
    resp = run_cpu_whatif(_Db(row), req)
    assert resp.result["base"]["clusters"]["BIG"]["mhz"] == 1000
    with pytest.raises(UnprocessableError, match="give cpu_profile_ref"):
        run_cpu_whatif(_Db(row), CpuWhatIfRequest(power_params_ref="pmp-t"))


def test_list_cpu_inputs_reports_dominant_cluster_per_task():
    from scenario_db.api.services.cpu import list_cpu_inputs

    topo = SimpleNamespace(id="pmp-x", version="1", soc_ref="soc-x",
                           params={"cpu": {"clusters": [{"name": "MID"}, {"name": "BIG"}]}})
    obs = [
        {"metric_id": "cpu.cycles_pf", "value": 5e6, "scope": {"kind": "task_cluster", "ref": "eis@MID"}},
        {"metric_id": "cpu.cycles_pf", "value": 9e6, "scope": {"kind": "task_cluster", "ref": "eis@BIG"}},
        {"metric_id": "cpu.cycles_pf", "value": 1e6, "scope": {"kind": "task_cluster", "ref": "enc@MID"}},
    ]
    meas = SimpleNamespace(id="ev-1", scenario_ref="s", variant_ref="v", project_ref="p", metric_observations=obs)
    plain = SimpleNamespace(id="ev-2", scenario_ref="s", variant_ref="v", project_ref="p",
                            metric_observations=[{"metric_id": "fps"}])

    class _Q:
        def __init__(self, rows):
            self.rows = rows

        def order_by(self, *_):
            return self

        def filter(self, *_):
            return self

        def all(self):
            return self.rows

    class _Db:
        def query(self, model):
            return _Q([meas, plain] if model.__name__ == "Evidence" else [topo])

    out = list_cpu_inputs(_Db())  # type: ignore[arg-type]
    assert out["topologies"] == [{"id": "pmp-x", "version": "1", "soc_ref": "soc-x", "clusters": ["MID", "BIG"]}]
    assert [p["id"] for p in out["profiles"]] == ["ev-1"]
    assert out["profiles"][0]["tasks"] == [{"task": "eis", "cluster": "BIG"}, {"task": "enc", "cluster": "MID"}]
