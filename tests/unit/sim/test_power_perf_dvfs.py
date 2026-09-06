from __future__ import annotations

import pytest

from scenario_db.sim.dvfs_resolver import DvfsResolver
from scenario_db.sim.models import DVFSLevel, DVFSTable, IPSimParams, IPWorkload, SimulationRunConfig
from scenario_db.sim.perf_calc import calc_processing_time_ms
from scenario_db.sim.power_calc import calc_active_power_mw


def test_power_formula_uses_voltage_squared_and_fps_scale():
    assert calc_active_power_mw(
        unit_power_mw_mp=10.0,
        resolution_mp=2.0,
        voltage_mv=710.0,
        fps=60.0,
    ) == pytest.approx(40.0)


def test_processing_time_uses_h_blank_margin():
    result = calc_processing_time_ms(
        pixels=1920 * 1080,
        set_clock_mhz=400,
        ppc=4,
        h_blank_margin=0.05,
    )

    assert result == pytest.approx(1.3608, rel=1e-3)


def test_simulation_default_sw_margin_is_15_percent():
    assert SimulationRunConfig().sw_margin == pytest.approx(0.15)
    assert IPWorkload(
        node_id="isp0",
        ip_ref="ip-isp-v12",
        hw_name="ISP",
        width=1920,
        height=1080,
        fps=30,
        sim_params=IPSimParams(hw_name="ISP"),
    ).sw_margin == pytest.approx(0.15)


def test_dvfs_resolver_aligns_shared_vdd_voltage():
    resolver = DvfsResolver(
        {
            "CAM": DVFSTable(
                domain="CAM",
                levels=[
                    DVFSLevel(level=0, speed_mhz=600, voltages={4: 780}),
                    DVFSLevel(level=1, speed_mhz=400, voltages={4: 700}),
                ],
            ),
            "INT": DVFSTable(
                domain="INT",
                levels=[
                    DVFSLevel(level=0, speed_mhz=533, voltages={4: 760}),
                    DVFSLevel(level=1, speed_mhz=266, voltages={4: 680}),
                ],
            ),
        },
        asv_group=4,
    )
    workloads = [
        IPWorkload(
            node_id="isp0",
            ip_ref="ip-isp-v12",
            hw_name="ISP",
            width=3840,
            height=2160,
            fps=200,
            sim_params=IPSimParams(
                hw_name="ISP",
                ppc=4,
                unit_power_mw_mp=10,
                vdd="VDD_CAM",
                dvfs_group="CAM",
            ),
        ),
        IPWorkload(
            node_id="mfc",
            ip_ref="ip-mfc-v14",
            hw_name="MFC",
            width=1920,
            height=1080,
            fps=60,
            sim_params=IPSimParams(
                hw_name="MFC",
                ppc=4,
                unit_power_mw_mp=5,
                vdd="VDD_CAM",
                dvfs_group="INT",
            ),
        ),
    ]

    resolved = resolver.resolve(workloads)

    assert resolved["isp0"].set_clock_mhz == 600
    assert resolved["mfc"].set_clock_mhz == 266
    assert resolved["isp0"].set_voltage_mv == 780
    assert resolved["mfc"].set_voltage_mv == 780
    assert resolved["mfc"].vdd_leader == "isp0"


def test_manual_clock_shared_set_clock_raises_group_required_voltage():
    resolver = DvfsResolver(
        {
            "CAM": DVFSTable(
                domain="CAM",
                levels=[
                    DVFSLevel(level=0, speed_mhz=600, voltages={4: 780}),
                    DVFSLevel(level=1, speed_mhz=400, voltages={4: 700}),
                    DVFSLevel(level=2, speed_mhz=133, voltages={4: 562.5}),
                ],
            ),
        },
        asv_group=4,
    )
    workloads = [
        IPWorkload(
            node_id="isp0",
            ip_ref="ip-isp-v12",
            hw_name="ISP",
            width=1920,
            height=1080,
            fps=30,
            manual_clock_mhz=600,
            sim_params=IPSimParams(
                hw_name="ISP",
                ppc=4,
                unit_power_mw_mp=10,
                vdd="VDD_CAM",
                dvfs_group="CAM",
            ),
        ),
        IPWorkload(
            node_id="byrp",
            ip_ref="ip-isp-v12",
            hw_name="BYRP",
            width=1920,
            height=1080,
            fps=30,
            sim_params=IPSimParams(
                hw_name="BYRP",
                ppc=4,
                unit_power_mw_mp=10,
                vdd="VDD_CAM",
                dvfs_group="CAM",
            ),
        ),
    ]

    resolved = resolver.resolve(workloads)

    assert resolved["isp0"].required_clock_mhz == pytest.approx(600)
    assert resolved["isp0"].required_voltage_mv == pytest.approx(780)
    assert resolved["byrp"].required_clock_mhz < 133
    # byrp is pulled up to the group's aligned level; its required voltage
    # must follow that level (was 562.5 pre-fix — an under-volted phantom).
    assert resolved["byrp"].required_voltage_mv == pytest.approx(780)
    assert resolved["byrp"].set_clock_mhz == pytest.approx(600)
    assert resolved["byrp"].set_voltage_mv == pytest.approx(780)


def test_group_aligned_node_alone_on_its_rail_gets_aligned_voltage():
    """A node pulled up by dvfs_group alignment but alone on its VDD rail must
    carry the raised level's voltage — rail alignment cannot mask it."""
    resolver = DvfsResolver(
        {
            "CAM": DVFSTable(
                domain="CAM",
                levels=[
                    DVFSLevel(level=0, speed_mhz=600, voltages={4: 780}),
                    DVFSLevel(level=1, speed_mhz=400, voltages={4: 700}),
                    DVFSLevel(level=2, speed_mhz=133, voltages={4: 562.5}),
                ],
            ),
        },
        asv_group=4,
    )
    workloads = [
        IPWorkload(
            node_id="isp0",
            ip_ref="ip-isp-v12",
            hw_name="ISP",
            width=1920,
            height=1080,
            fps=30,
            manual_clock_mhz=600,
            sim_params=IPSimParams(
                hw_name="ISP",
                ppc=4,
                unit_power_mw_mp=10,
                vdd="VDD_CAM",
                dvfs_group="CAM",
            ),
        ),
        IPWorkload(
            node_id="byrp",
            ip_ref="ip-isp-v12",
            hw_name="BYRP",
            width=1920,
            height=1080,
            fps=30,
            sim_params=IPSimParams(
                hw_name="BYRP",
                ppc=4,
                unit_power_mw_mp=10,
                vdd="VDD_BYRP",  # own rail: no other node can mask the voltage
                dvfs_group="CAM",
            ),
        ),
    ]

    resolved = resolver.resolve(workloads)

    assert resolved["byrp"].set_clock_mhz == pytest.approx(600)
    assert resolved["byrp"].dvfs_level == 0
    # Pre-fix this stayed at 562.5 (level 2's voltage) while reporting level 0.
    assert resolved["byrp"].set_voltage_mv == pytest.approx(780)


def test_required_clock_above_ip_max_clock_is_infeasible_without_dvfs_table():
    resolver = DvfsResolver({}, asv_group=4)
    workloads = [
        IPWorkload(
            node_id="isp0",
            ip_ref="ip-isp-v12",
            hw_name="ISP",
            width=7680,
            height=4320,
            fps=60,
            sim_params=IPSimParams(
                hw_name="ISP",
                ppc=1,
                unit_power_mw_mp=10,
                max_clock_mhz=800,
            ),
        ),
    ]

    resolved = resolver.resolve(workloads)

    assert resolved["isp0"].feasible is False
    assert "max_clock" in (resolved["isp0"].infeasible_reason or "")
