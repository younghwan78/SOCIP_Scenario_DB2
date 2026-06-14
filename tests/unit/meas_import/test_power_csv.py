from __future__ import annotations

from pathlib import Path

import pytest

from scenario_db.meas_import.meta import PowerSpec
from scenario_db.meas_import.power_csv import (
    PowerCsvError,
    aggregate_power,
    aggregate_power_rail_long,
)


def _write_csv(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "power.csv"
    p.write_text(text, encoding="utf-8")
    return p


def test_aggregate_vdd_and_cluster_and_total(tmp_path: Path):
    csv = _write_csv(
        tmp_path,
        "timestamp_ms,VDD_CAM,VDD_BIG,VDD_LIT\n"
        "0,100,40,10\n"
        "1,200,60,30\n",
    )
    spec = PowerSpec(
        csv="power.csv",
        total_power_rails=["VDD_CAM", "VDD_BIG", "VDD_LIT"],
        rails={
            "VDD_CAM": {"role": "vdd"},
            "VDD_BIG": {"role": "cpu_cluster", "cluster": "BIG"},
            "VDD_LIT": {"role": "cpu_cluster", "cluster": "LIT"},
        },
    )
    digest = aggregate_power(csv, spec)

    assert digest.sample_count == 2
    # vdd
    assert digest.vdd_power["VDD_CAM"]["mean_mw"] == 150.0
    # per-cluster (single rail each)
    assert digest.cpu_cluster_power["BIG"]["mean"] == 50.0
    assert digest.cpu_cluster_power["LIT"]["mean"] == 20.0
    # total = per-sample sum: (100+40+10)=150, (200+60+30)=290 -> mean 220
    assert digest.total_power_mw["mean"] == 220.0
    assert digest.total_power_mw["n"] == 2


def test_cluster_sums_multiple_rails_per_sample(tmp_path: Path):
    csv = _write_csv(
        tmp_path,
        "timestamp_ms,VDD_BIG0,VDD_BIG1\n"
        "0,30,20\n"
        "1,50,40\n",
    )
    spec = PowerSpec(
        csv="power.csv",
        rails={
            "VDD_BIG0": {"role": "cpu_cluster", "cluster": "BIG"},
            "VDD_BIG1": {"role": "cpu_cluster", "cluster": "BIG"},
        },
    )
    digest = aggregate_power(csv, spec)
    # per-sample sum: 50, 90 -> mean 70
    assert digest.cpu_cluster_power["BIG"]["mean"] == 70.0


def test_total_power_column_takes_precedence(tmp_path: Path):
    csv = _write_csv(
        tmp_path,
        "timestamp_ms,VDD_CAM,TOTAL\n"
        "0,100,500\n"
        "1,200,700\n",
    )
    spec = PowerSpec(csv="power.csv", total_power_column="TOTAL", total_power_rails=["VDD_CAM"])
    digest = aggregate_power(csv, spec)
    assert digest.total_power_mw["mean"] == 600.0


def test_missing_time_column_raises(tmp_path: Path):
    csv = _write_csv(tmp_path, "t,VDD_CAM\n0,100\n")
    with pytest.raises(PowerCsvError, match="time column"):
        aggregate_power(csv, PowerSpec(csv="power.csv"))


def test_unknown_rail_in_spec_raises(tmp_path: Path):
    csv = _write_csv(tmp_path, "timestamp_ms,VDD_CAM\n0,100\n")
    spec = PowerSpec(csv="power.csv", rails={"VDD_GPU": {"role": "vdd"}})
    with pytest.raises(PowerCsvError, match="not a CSV column"):
        aggregate_power(csv, spec)


def test_non_numeric_value_raises(tmp_path: Path):
    csv = _write_csv(tmp_path, "timestamp_ms,VDD_CAM\n0,oops\n")
    with pytest.raises(PowerCsvError, match="non-numeric"):
        aggregate_power(csv, PowerSpec(csv="power.csv"))


def test_short_row_raises_power_csv_error(tmp_path: Path):
    csv = _write_csv(tmp_path, "timestamp_ms,VDD_CAM,VDD_BIG\n0,100\n")
    with pytest.raises(PowerCsvError, match="malformed row"):
        aggregate_power(csv, PowerSpec(csv="power.csv"))


def test_skips_blank_and_empty_cells(tmp_path: Path):
    csv = _write_csv(
        tmp_path,
        "timestamp_ms,VDD_CAM\n0,100\n\n2,\n3,200\n",
    )
    digest = aggregate_power(csv, PowerSpec(csv="power.csv"))
    # two numeric samples: 100, 200
    assert digest.rail_kpi["VDD_CAM"]["mean"] == 150.0


# --- rail_long (real bench: run x rail, V/mA/mW, aggregated across runs) ---

def test_rail_long_aggregates_triplet_across_runs(tmp_path: Path):
    csv = _write_csv(
        tmp_path,
        "run,rail,voltage_v,current_ma,power_mw\n"
        "1,VDD_CAM,0.60,100,60\n"
        "1,VDD_BIG,0.55,40,22\n"
        "2,VDD_CAM,0.60,110,66\n"
        "2,VDD_BIG,0.55,50,28\n",
    )
    spec = PowerSpec(
        csv="power.csv",
        format="rail_long",
        rails={"VDD_BIG": {"role": "cpu_cluster", "cluster": "BIG"}},
    )
    digest = aggregate_power_rail_long(csv, spec)

    assert digest.sample_count == 2                       # two runs
    cam = digest.vdd_power["VDD_CAM"]
    assert cam["power_mw"] == 63.0                        # mean(60,66)
    assert cam["voltage_v"] == 0.6                        # regulated, constant
    assert cam["current_ma"] == 105.0                     # mean(100,110)
    assert "std_mw" in cam
    # cluster: per-run member sum (here single rail) across runs -> mean(22,28)=25
    assert digest.cpu_cluster_power["BIG"]["mean"] == 25.0
    assert digest.cpu_cluster_power["BIG"]["n"] == 2
    # total = per-run sum of all rails: run1=82, run2=94 -> mean 88, n=2
    assert digest.total_power_mw["mean"] == 88.0
    assert digest.total_power_mw["n"] == 2


def test_rail_long_total_subset_and_single_run(tmp_path: Path):
    csv = _write_csv(
        tmp_path,
        "run,rail,voltage_v,current_ma,power_mw\n"
        "1,VDD_CAM,0.60,100,60\n"
        "1,VDD_MEM,1.10,20,22\n",
    )
    spec = PowerSpec(csv="power.csv", format="rail_long", total_power_rails=["VDD_CAM"])
    digest = aggregate_power_rail_long(csv, spec)
    assert digest.sample_count == 1
    assert digest.total_power_mw["mean"] == 60.0          # subset = VDD_CAM only
    assert digest.total_power_mw["n"] == 1                # single run -> no ci_95
    assert "ci_95" not in digest.total_power_mw
    assert "std_mw" not in digest.vdd_power["VDD_CAM"]     # n=1 -> no std


def test_rail_long_missing_power_column_raises(tmp_path: Path):
    csv = _write_csv(tmp_path, "run,rail,voltage_v,current_ma\n1,VDD_CAM,0.6,100\n")
    with pytest.raises(PowerCsvError, match="power_mw"):
        aggregate_power_rail_long(csv, PowerSpec(csv="power.csv", format="rail_long"))


def test_rail_long_non_numeric_raises(tmp_path: Path):
    csv = _write_csv(tmp_path, "run,rail,voltage_v,current_ma,power_mw\n1,VDD_CAM,0.6,100,oops\n")
    with pytest.raises(PowerCsvError, match="non-numeric"):
        aggregate_power_rail_long(csv, PowerSpec(csv="power.csv", format="rail_long"))
