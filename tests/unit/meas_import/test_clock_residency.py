"""Clock-domain residency: table import (CPU active / DSU / GPU, PMU-pass groups), perfetto shaping,
CPU power with running-time residency, read view notes, report block."""
from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest
import yaml

from scenario_db.api.services.clock_residency import (clock_residency_view, opp_max_from_ip_catalog,
                                                      opp_max_from_params)
from scenario_db.meas_import import clock_residency as cr
from scenario_db.meas_import.meta import PerfettoSpec, PmuSpec
from scenario_db.meas_import.observations import build_metric_observations
from scenario_db.meas_import.perfetto_digest import (SQL_CPU_ACTIVE_RESIDENCY, PerfettoDigest, extract_digest)
from scenario_db.meas_import.pmu_digest import PmuDigest, PmuDigestError, PmuSample, build_pmu_digest, import_pmu_digest
from scenario_db.meas_import.table_adapter import TableSource
from scenario_db.models.capability.power_model import PowerModelParams
from scenario_db.reporting.clock_section import clock_block, clock_sheet, opp_color, report_rows
from scenario_db.sim.cpu_power import CpuPowerModel, profile_cpu_power
from scenario_db.sim.models import CpuClusterProfile, CpuProfile, CpuTaskProfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "examples" / "measurement-import" / "clock-residency-e2600"
PMP = ROOT / "db_Exynos2600_SM-S947B" / "00_hw" / "pmp-exynos2600-v2.yaml"
GPU_IP = ROOT / "db_Exynos2600_SM-S947B" / "00_hw" / "ip-gpu-s5e9965.yaml"


def _digest(variant: str):
    meta = yaml.safe_load((EXAMPLE / variant / "meta.yaml").read_text(encoding="utf-8"))
    return import_pmu_digest(EXAMPLE / variant, PmuSpec.model_validate(meta["pmu"]))


def _by(obs: list[dict], metric: str) -> dict[str, float]:
    return {o["scope"]["ref"]: o["value"] for o in obs if o["metric_id"] == metric}


def test_example_imports_every_domain_and_basis():
    d = _digest("cam-rec-r1-uhd30-vdis")
    wall, active = _by(d.observations, "cpu.freq_residency"), _by(d.observations, "cpu.freq_residency_active")
    assert wall["MID_LF0@1000"] == pytest.approx(0.70, abs=1e-3)
    assert active["MID_LF0@1000"] > wall["MID_LF0@1000"]          # idle parks at 400 MHz
    assert {"DSU@400", "DSU@900"} <= set(wall) and {"DSU@400", "DSU@900"} <= set(active)
    gpu = _by(d.observations, "gpu.freq_residency")
    assert sum(gpu.values()) == pytest.approx(1.0, abs=1e-5) and "GPU@226" in gpu
    assert _by(d.observations, "gpu.active_ratio")["GPU"] == pytest.approx(0.22, abs=1e-3)
    assert "BIG" not in {k.rpartition("@")[0] for k in active}      # never ran -> no running residency
    jsd = _by(d.observations, cr.PASS_JSD_METRIC)
    assert jsd["cpu/MID_LF0"] < cr.PASS_JSD_WARN and "gpu/GPU" in jsd
    assert not any("JSD" in w for w in d.warnings)


def test_pass_divergence_is_reported():
    d = _digest("cam-rec-r1-8k30-psm")
    assert _by(d.observations, cr.PASS_JSD_METRIC)["cpu/MID_LF0"] > cr.PASS_JSD_WARN
    assert any("cpu/MID_LF0" in w and "JSD" in w for w in d.warnings)


def test_jsd_bounds():
    assert cr.jsd({1: 1.0}, {1: 2.0}) == 0.0
    assert cr.jsd({1: 1.0}, {2: 1.0}) == pytest.approx(1.0)
    assert 0 < cr.jsd({1: 0.5, 2: 0.5}, {1: 0.6, 2: 0.4}) < 0.05


def test_source_validation():
    with pytest.raises(ValueError, match="cluster"):
        TableSource(file="g.csv", kind="freq_residency", domain_class="gpu", cpu={"column": "cpu"},
                    freq_column="f", value_column="t")
    with pytest.raises(ValueError, match="residency sources only"):
        TableSource(file="c.csv", kind="counters", basis="active", cpu={"column": "cpu"},
                    counters={"cycles": ["cpu-cycles"]}, counter_column="e", value_column="v")
    # a PMU pass on a counter source is allowed (merged by meas_import/pmu_passes.py)
    TableSource(file="c.csv", kind="counters", group="pass1", cpu={"column": "cpu"},
                counters={"cycles": ["cpu-cycles"]}, counter_column="e", value_column="v")
    with pytest.raises(ValueError, match="unknown clock domain class"):
        TableSource(file="n.csv", kind="freq_residency", domain_class="npu", cluster={"value": "NPU"},
                    freq_column="f", value_column="t")


def test_neutral_samples_with_groups_and_duplicates():
    samples = [PmuSample("gpu_freq_time", "gpu", "GPU", 3.0, freq_mhz=300, group="p1", line=1),
               PmuSample("gpu_freq_time", "gpu", "GPU", 1.0, freq_mhz=600, group="p1", line=2),
               PmuSample("gpu_freq_time", "gpu", "GPU", 3.0, freq_mhz=300, group="p2", line=3),
               PmuSample("gpu_freq_time", "gpu", "GPU", 1.0, freq_mhz=600, group="p2", line=4)]
    d = build_pmu_digest(samples)
    assert _by(d.observations, "gpu.freq_residency") == {"GPU@300": 0.75, "GPU@600": 0.25}
    assert _by(d.observations, cr.PASS_JSD_METRIC) == {"gpu/GPU": 0.0}
    with pytest.raises(PmuDigestError, match="duplicate"):
        build_pmu_digest(samples + [PmuSample("gpu_freq_time", "gpu", "GPU", 1.0, freq_mhz=600, group="p2", line=5)])
    with pytest.raises(PmuDigestError, match="domain scope"):
        build_pmu_digest([PmuSample("gpu_freq_time", "cpu", "0", 1.0, freq_mhz=300, line=1)])


class FakeTrace:
    """Answers the clock SQL by content (no trace_processor needed)."""

    def query(self, sql: str) -> list[dict]:
        if sql == SQL_CPU_ACTIVE_RESIDENCY:
            return [{"cpu": 0, "freq_khz": 1_000_000, "dur_ns": 3e9}, {"cpu": 1, "freq_khz": 400_000, "dur_ns": 1e9},
                    {"cpu": 9, "freq_khz": 2_000_000, "dur_ns": 0}]
        if "SPAN_JOIN(_sdb_cd_freq" in sql:
            assert "'gpu_util'" in sql and "100.0" in sql
            return [{"value": 300_000, "busy_ns": 2e9, "dur_ns": 8e9}, {"value": 600_000, "busy_ns": 2e9, "dur_ns": 2e9}]
        if "counter_track t" in sql and "'gpufreq'" in sql:
            return [{"track": "gpufreq", "value": 300_000, "dur_ns": 8e9}, {"track": "gpufreq", "value": 600_000, "dur_ns": 2e9}]
        if "'dsu_clk'" in sql or "freq_spans" in sql:   # DSU track absent; wall cpufreq not under test
            return []
        raise AssertionError(sql)


def test_perfetto_clock_domains():
    spec = PerfettoSpec(trace="t.pftrace", cpu_to_cluster={0: "MID_LF0", 1: "MID_LF0", 9: "BIG"}, cpu_active_residency=True,
                        clock_domains=[{"name": "GPU", "tracks": ["gpufreq"], "utilization_track": "gpu_util"},
                                       {"name": "DSU", "domain_class": "cpu", "tracks": ["dsu_clk"]}])
    digest = extract_digest(FakeTrace(), spec)
    obs = cr.perfetto_observations(digest)
    assert _by(obs, "cpu.freq_residency_active") == {"MID_LF0@400": 0.25, "MID_LF0@1000": 0.75}
    assert _by(obs, "gpu.freq_residency") == {"GPU@300": 0.8, "GPU@600": 0.2}
    assert _by(obs, "gpu.freq_residency_active") == {"GPU@300": 0.5, "GPU@600": 0.5}
    assert _by(obs, "gpu.active_ratio") == {"GPU": 0.4}
    assert any("DSU" in w for w in digest.warnings)


def test_pmu_owned_domain_wins_over_trace():
    meta = SimpleNamespace(metric_observations=[], sw_task_timing=[], profiling=None)
    pmu = PmuDigest(observations=[{"metric_id": "gpu.freq_residency", "scope": {"kind": "gpu_freq", "ref": "GPU@226"},
                                   "unit": "ratio", "value": 1.0}])
    perfetto = PerfettoDigest()
    perfetto.clock_residency = [{"domain_class": "gpu", "domain": "GPU", "basis": "wall", "bins": {300.0: 1.0, 600.0: 1.0}},
                                {"domain_class": "gpu", "domain": "GPU", "basis": "active", "bins": {300.0: 1.0}}]
    obs = build_metric_observations(meta, None, perfetto, kpi={}, pmu=pmu)
    assert _by(obs, "gpu.freq_residency") == {"GPU@226": 1.0}       # no mixed bins
    assert _by(obs, "gpu.freq_residency_active") == {"GPU@300": 1.0}


def _model() -> CpuPowerModel:
    return CpuPowerModel.from_params(PowerModelParams.model_validate(yaml.safe_load(PMP.read_text(encoding="utf-8"))))


def test_cpu_power_uses_running_residency_cycle_weighted():
    task = CpuTaskProfile(task="eis", cluster="MID_LF0", cycles=10e6)
    wall_only = CpuProfile(tasks=[task], clusters={"MID_LF0": CpuClusterProfile(freq_residency={400.0: 0.3, 1000.0: 0.7})})
    with_run = CpuProfile(tasks=[task], clusters={"MID_LF0": CpuClusterProfile(
        freq_residency={400.0: 0.3, 1000.0: 0.7}, freq_residency_active={400.0: 0.5, 1000.0: 0.5})})
    model = _model()
    a = profile_cpu_power(wall_only, model=model, period_ms=33.3)
    b = profile_cpu_power(with_run, model=model, period_ms=33.3)
    cl = next(c for c in model.clusters if c.name == "MID_LF0")
    e = {f: cl.energy_nj_per_cycle(f, model.fallback_mv) for f in (400.0, 1000.0)}
    expected = (0.5 * 400 * e[400.0] + 0.5 * 1000 * e[1000.0]) / (0.5 * 400 + 0.5 * 1000)
    assert b["tasks"][0]["power_mw"] == pytest.approx(10e6 * expected / 33.3 / 1000.0, rel=1e-4)
    assert b["clusters"]["MID_LF0"]["residency_basis"] == "active"
    assert b["clusters"]["MID_LF0"]["static_mw"] == pytest.approx(a["clusters"]["MID_LF0"]["static_mw"])  # leakage: wall
    assert "residency_basis" not in a["clusters"]["MID_LF0"]


def _view(variant: str):
    ev = yaml.safe_load((ROOT / "db_Exynos2600_SM-S947B" / "03_evidence"
                         / f"meas-synthetic-clock-residency-{variant}-e2600-evt1.yaml").read_text(encoding="utf-8"))
    params = yaml.safe_load(PMP.read_text(encoding="utf-8"))
    opp = opp_max_from_ip_catalog([yaml.safe_load(GPU_IP.read_text(encoding="utf-8"))], "soc-exynos2600") \
        | opp_max_from_params([{"cpu": params["cpu"]}], {"MID_LF0", "DSU"})
    return ev, clock_residency_view(ev["metric_observations"], ev.get("cpu_breakdown"), opp_max=opp)


def test_view_notes_and_summary():
    _, view = _view("r1-8k30-psm")
    assert view is not None
    d = {x["domain"]: x for x in view["domains"]}
    assert [x["domain"] for x in view["domains"]][-2:] == ["DSU", "GPU"]     # CPU clusters, DSU, then GPU
    assert d["GPU"]["opp_max_mhz"] == 980.0 and d["MID_LF0"]["opp_max_mhz"] == 2000.0
    codes = {k: [n["code"] for n in v["notes"]] for k, v in d.items()}
    assert {"pass_divergence", "high_opp"} <= set(codes["MID_LF0"])
    assert codes["BIG"] == ["idle_domain"]
    assert "idle_gap" in codes["MID_LF1"]
    assert view["summary"][0].startswith("CPU: 가장 바쁜 cluster MID_LF0")
    assert any(s.startswith("확인 필요") for s in view["summary"])
    _, calm = _view("r1-uhd30-vdis")
    assert not any(s.startswith("확인 필요") for s in calm["summary"])


def test_view_without_topology_does_not_claim_high_opp():
    obs = [{"metric_id": "gpu.freq_residency", "scope": {"kind": "gpu_freq", "ref": f"GPU@{f}"}, "unit": "ratio", "value": v}
           for f, v in ((300, 0.2), (600, 0.8))]
    view = clock_residency_view(obs)
    assert view["domains"][0]["wall"]["high_share"] is None
    assert not view["domains"][0]["notes"]
    assert clock_residency_view([]) is None


def test_report_block_and_sheet():
    ev, view = _view("r1-8k30-psm")
    m = SimpleNamespace(id=ev["id"], measured_at=None, provenance=ev["provenance"])
    row = report_rows(ev["variant_ref"], ev["scenario_ref"], m, view)
    html = clock_block([row])
    assert "Clock 분포 실측" in html and "r1-8k30-psm" in html and "합성" in html and "JSD" in html
    assert html.count("<svg") == len(row["domains"])
    name, header, rows = clock_sheet({"clock_residency": [row]})
    assert name == "Clock 분포" and len(rows) == len(row["domains"]) and len(header) == len(rows[0])
    assert clock_block([]) == ""
    assert opp_color(0, 4) == "#D7ECE7" and opp_color(3, 4) == "#174D47"


def _obs(metric: str, kind: str, ref: str, value: float) -> dict:
    return {"metric_id": metric, "scope": {"kind": kind, "ref": ref}, "unit": "ratio", "value": value}


def test_wall_only_cpu_is_one_summary_line_and_burst_rule():
    obs = [_obs("cpu.freq_residency", "cluster_freq", "MID_HF@2400", 0.9), _obs("cpu.freq_residency", "cluster_freq", "MID_HF@600", 0.1),
           _obs("cpu.active_ratio", "cluster", "MID_HF", 0.1)]
    view = clock_residency_view(obs, opp_max={"MID_HF": 2600.0})
    d = view["domains"][0]
    assert [n["code"] for n in d["notes"]] == ["high_opp", "burst"]
    assert any("running(idle 제외) 분포 없음" in s for s in view["summary"])
