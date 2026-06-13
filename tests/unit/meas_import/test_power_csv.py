from __future__ import annotations

from pathlib import Path

import pytest

from scenario_db.meas_import.meta import PowerSpec
from scenario_db.meas_import.power_csv import PowerCsvError, aggregate_power


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
