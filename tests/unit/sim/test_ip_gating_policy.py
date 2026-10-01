"""v2-vf gating-aware IP power and the same-voltage DVFS promotion policy."""
from __future__ import annotations

import pytest

from scenario_db.sim.dvfs_resolver import DvfsResolver
from scenario_db.sim.models import DVFSLevel, DVFSTable, IPSimParams, IPWorkload
from scenario_db.sim.power_model import busy_share, clock_factor, resolve_power_model

V2 = resolve_power_model("v2-vf")


def _table(levels) -> dict[str, DVFSTable]:
    return {"CAM": DVFSTable(domain="CAM", levels=[DVFSLevel(level=i, speed_mhz=f, voltages={4: v})
                                                    for i, (f, v) in enumerate(levels)])}


def _wl(node="isp", **sim) -> IPWorkload:
    # 3840x2160x30 / 0.85 / 2 ppc ~= 146 MHz need
    return IPWorkload(node_id=node, ip_ref=f"ip-{node}", hw_name=node.upper(), width=3840, height=2160, fps=30.0,
                      sim_params=IPSimParams(hw_name=node.upper(), ppc=2, unit_power_mw_mp=10, dvfs_group="CAM", **sim))


def test_gating_terms_reduce_to_previous_v2_and_v1():
    assert clock_factor(0.3, 400, 200) == pytest.approx(0.7 + 0.3 * 2)           # cg = 0: previous v2
    assert clock_factor(0.3, 400, 200, 1.0) == pytest.approx(1.0)                 # perfect clock gating
    assert clock_factor(0.3, 400, 200, 0.5) == pytest.approx(0.7 + 0.3 * 2 * (0.5 + 0.5 * 0.5))
    assert busy_share(400, 100) == 0.25 and busy_share(None, 100) == 1.0
    base = DvfsResolver(_table([(400, 700)])).resolve([_wl()])["isp"]
    v2 = DvfsResolver(_table([(400, 700)]), power_model=V2).resolve([_wl()])["isp"]
    assert v2.total_power_mw == pytest.approx(base.total_power_mw)
    assert v2.leakage_power_mw == 0.0 and v2.clock_overhead_mw == 0.0


def test_leakage_with_power_gating_and_decomposition():
    cfg = DvfsResolver(_table([(400, 710)]), power_model=V2).resolve(
        [_wl(leakage_mw=20.0, power_gating_eff=0.8, clock_power_fraction=0.3, clock_gating_eff=0.5)])["isp"]
    busy = cfg.clock_ref_mhz / cfg.set_clock_mhz
    assert cfg.leakage_power_mw == pytest.approx(20.0 * (1 - 0.8 * (1 - busy)))
    work = DvfsResolver(_table([(400, 710)])).resolve([_wl()])["isp"].total_power_mw
    assert cfg.total_power_mw == pytest.approx(work + cfg.leakage_power_mw + cfg.clock_overhead_mw)
    assert cfg.clock_overhead_mw == pytest.approx(work * (clock_factor(0.3, cfg.set_clock_mhz, cfg.clock_ref_mhz, 0.5) - 1))


def test_same_voltage_promotion_under_v1_is_free_margin():
    table = _table([(200, 650), (300, 650), (400, 700)])
    base = DvfsResolver(table).resolve([_wl()])["isp"]
    assert base.set_clock_mhz == 200
    promo = DvfsResolver(table, dvfs_policy="same_voltage_up").resolve([_wl()])["isp"]
    assert promo.set_clock_mhz == 300 and promo.set_voltage_mv == 650          # never the 700 mV level
    assert promo.total_power_mw == pytest.approx(base.total_power_mw)
    assert promo.dvfs_promotion == {"from_mhz": 200, "to_mhz": 300, "delta_mw": 0.0, "voltage_mv": 650}
    assert any(c.kind == "dvfs_policy" for c in promo.clock_ledger.constraints)


def test_same_voltage_promotion_respects_power_under_v2():
    table = _table([(200, 650), (300, 650)])
    ungated = DvfsResolver(table, power_model=V2, dvfs_policy="same_voltage_up").resolve(
        [_wl(clock_power_fraction=0.3)])["isp"]
    assert ungated.set_clock_mhz == 200 and ungated.dvfs_promotion is None     # clock power would rise
    gated = DvfsResolver(table, power_model=V2, dvfs_policy="same_voltage_up").resolve(
        [_wl(clock_power_fraction=0.3, clock_gating_eff=1.0)])["isp"]
    assert gated.set_clock_mhz == 300                                           # idle clock fully gated
    tolerant = DvfsResolver(table, power_model=V2, dvfs_policy="same_voltage_up", promote_tolerance_pct=50).resolve(
        [_wl(clock_power_fraction=0.3)])["isp"]
    assert tolerant.set_clock_mhz == 300 and tolerant.dvfs_promotion["delta_mw"] > 0


def test_promotion_is_skipped_for_overridden_groups():
    table = _table([(200, 650), (300, 650)])
    cfg = DvfsResolver(table, dvfs_policy="same_voltage_up").resolve([_wl()], dvfs_overrides={"CAM": 0})["isp"]
    assert cfg.set_clock_mhz == 200 and cfg.dvfs_promotion is None


def test_promotion_respects_every_group_members_maximum_clock():
    table = _table([(200, 650), (300, 650), (400, 650)])
    resolved = DvfsResolver(table, dvfs_policy="same_voltage_up").resolve(
        [_wl(), _wl("tnr", max_clock_mhz=350)])
    assert all(c.set_clock_mhz == 300 and c.feasible for c in resolved.values())
    capped = DvfsResolver(table, dvfs_policy="same_voltage_up").resolve([_wl(max_clock_mhz=250)])["isp"]
    assert capped.set_clock_mhz == 200 and capped.feasible and capped.dvfs_promotion is None
