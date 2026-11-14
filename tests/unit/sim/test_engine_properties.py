"""S-10: properties the engine must keep across revisions (monotone directions, not exact numbers).

- DVFS level up (faster OPP) -> power does not go down
- buffer compression on (any ratio <= 1) -> BW does not go up
- SW growth up (DVFS fixed) -> SW slack (exploration SW margin rule) does not go up
- fps up -> required IP clock does not go down

A golden case pins numbers; these pin directions, so a model change that keeps them can still move
numbers (and is recorded in docs/contracts/simulation/engine-revisions.md).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from verify_is_v15_camera import FIXTURE, graph_from_fixture, read  # noqa: E402

from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.sim.adapter import build_port_transfers  # noqa: E402
from scenario_db.sim.bw_calc import calc_port_bw  # noqa: E402
from scenario_db.sim.models import DVFSTable, SimulationRunConfig  # noqa: E402
from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget, dvfs_level_whatif  # noqa: E402

REC = "uc-cam-recording-e2600"
EPS = 1e-6


@pytest.fixture(scope="module")
def env():
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    doc = read(FIXTURE / "00_hw" / "dvfs-exynos2600-sample-v0.yaml")
    tables = {k: DVFSTable.model_validate(v) for k, v in doc["domains"].items()}
    return catalog, tables, read(FIXTURE / "02_definition" / f"{REC}.yaml")


@pytest.mark.parametrize("variant", ["cam-rec-r1-fhd30-sdr", "cam-rec-r1-fhd60-sdr"])
def test_a_faster_dvfs_level_never_lowers_power(env, variant):
    catalog, tables, raw = env
    graph = graph_from_fixture(raw, variant, catalog)
    w = dvfs_level_whatif(graph, TimingBudgetOptions(), dvfs_tables=tables, shifts=(1, 2))
    base = w["base"]["total_mw"]
    checked = 0
    for domain in {r["domain"] for r in w["rows"]}:
        rows = sorted((r for r in w["rows"] if r["domain"] == domain and r.get("level") is not None), key=lambda r: r["shift"])
        chain = [base] + [r["total_mw"] for r in rows]
        assert all(b >= a - EPS for a, b in zip(chain, chain[1:])), (domain, chain)
        checked += len(rows)
    assert checked > 0


def test_compression_never_raises_bw(env):
    catalog, _, raw = env
    fps, _, transfers = build_port_transfers(graph_from_fixture(raw, "cam-rec-r1-fhd30-sdr", catalog))
    assert transfers
    for spec in transfers:
        off = calc_port_bw(spec.model_copy(update={"compression": "disable"}), fps=fps).bw_mbs
        for ratio in (1.0, 0.75, 0.5, 0.3):
            on = calc_port_bw(spec.model_copy(update={"compression": "SBWC", "comp_ratio": ratio}), fps=fps).bw_mbs
            assert on <= off + EPS, (spec.node_id, spec.port, ratio, on, off)


@pytest.mark.parametrize("variant", ["cam-rec-r1-fhd30-sdr", "cam-rec-r1-fhd60-sdr"])
@pytest.mark.parametrize("model", ["stage", "pipelined"])
def test_more_sw_growth_never_raises_the_sw_slack(env, variant, model):
    # the SW margin rule of the exploration (sw_margin): stage = P - (SW + HW), pipelined = P - longest SW task.
    # (``stages[].margin`` is the HW clock lift, not a slack: it rises with the SW load in the stage model.)
    # DVFS fixed at the base run's levels (the "DVFS 고정" tolerance): with re-selection, a growth that lifts a
    # domain one OPP makes HW faster and the slack can rise again — that is the other tolerance, not this property.
    catalog, tables, raw = env
    graph = graph_from_fixture(raw, variant, catalog)
    base = analyze_timing_budget(graph, TimingBudgetOptions(throughput_model=model), dvfs_tables=tables)
    pinned = SimulationRunConfig(dvfs_overrides={ip["dvfs_group"]: ip["dvfs_level"] for ip in base["ips"]
                                                 if ip.get("dvfs_group") in tables and ip.get("dvfs_level") is not None})
    assert pinned.dvfs_overrides
    slacks = []
    for scale in (1.0, 1.25, 1.5, 2.0):
        report = analyze_timing_budget(graph, TimingBudgetOptions(runtime_scale=scale, throughput_model=model),
                                       config=pinned, dvfs_tables=tables)
        P = report["period_ms"]
        slacks.append({s["id"]: P - (s["longest_sw_ms"] if model == "pipelined" else s["sw_ms"] + s["hw_ms"])
                       for s in report["stages"] if s["id"] in ("nrt", "post") and s["sw_ms"] > 0})
    assert slacks[0]
    for stage in slacks[0]:
        chain = [m[stage] for m in slacks]
        assert all(b <= a + EPS for a, b in zip(chain, chain[1:])), (stage, chain)


def test_a_higher_fps_never_lowers_a_required_clock(env):
    # fhd30 / fhd60 SDR differ only in the frame rate
    catalog, tables, raw = env
    lo, hi = (analyze_timing_budget(graph_from_fixture(raw, v, catalog), TimingBudgetOptions(), dvfs_tables=tables)
              for v in ("cam-rec-r1-fhd30-sdr", "cam-rec-r1-fhd60-sdr"))
    assert (lo["fps"], hi["fps"]) == (30.0, 60.0)
    need_lo = {ip["node"]: ip["own_required_mhz"] for ip in lo["ips"] if ip.get("own_required_mhz") is not None}
    need_hi = {ip["node"]: ip["own_required_mhz"] for ip in hi["ips"] if ip.get("own_required_mhz") is not None}
    common = need_lo.keys() & need_hi.keys()
    assert common
    for node in common:
        assert need_hi[node] >= need_lo[node] - EPS, (node, need_lo[node], need_hi[node])
