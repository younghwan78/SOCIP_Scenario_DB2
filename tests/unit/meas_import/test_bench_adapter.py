from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scenario_db.legacy_import.report import ImportReport
from scenario_db.meas_import.bench_adapter import (
    BenchParseError,
    assign_run_numbers,
    bench_files_to_rail_long,
    main,
    parse_bench_wide,
)
from scenario_db.meas_import.meta import MeasurementImportMeta
from scenario_db.meas_import.power_csv import aggregate_power_rail_long

REPO = Path(__file__).resolve().parents[3]
BENCH_EXPORT = REPO / "examples" / "measurement-import" / "bench-export"
PATH_A_CSV = REPO / "examples" / "measurement-import" / "path-a-capture" / "rail_power_by_run.csv"

WIDE_SAMPLE = """\
rail                          Voltage  Current(mA)  Power(mW)
B5S4_VDDMIF_AP_L              0.5687   70.3296      42.6975
B2S2_VDD_CPUCL1_MID_LF0_L     0.5954   183.8097     113.1666
"""


def test_parse_wide_whitespace_table_with_default_units():
    table = parse_bench_wide(WIDE_SAMPLE, source="run1.txt")
    assert not table.has_run_column
    assert table.rows[0] == {
        "rail": "B5S4_VDDMIF_AP_L",
        "voltage_v": pytest.approx(0.5687),
        "current_ma": pytest.approx(70.3296),
        "power_mw": pytest.approx(42.6975),
    }
    assert len(table.rows) == 2


def test_parse_converts_mv_and_w_units_to_canonical():
    text = (
        "rail  Voltage(mV)  Current(A)  Power[W]\n"
        "VDD_X  568.7  0.0703296  0.0426975\n"
    )
    table = parse_bench_wide(text, source="units.txt")
    row = table.rows[0]
    assert row["voltage_v"] == pytest.approx(0.5687)
    assert row["current_ma"] == pytest.approx(70.3296)
    assert row["power_mw"] == pytest.approx(42.6975)


def test_parse_comma_delimited_with_title_lines_and_comments():
    text = (
        "Bench power export v2\n"
        "# comment line\n"
        "name,voltage_v,current_ma,power_mw\n"
        "VDD_CAM,0.7,10.0,7.0\n"
        "\n"
        "VDD_MIF,0.5,20.0,10.0\n"
    )
    table = parse_bench_wide(text, source="export.csv")
    assert [row["rail"] for row in table.rows] == ["VDD_CAM", "VDD_MIF"]


def test_parse_single_file_with_run_column():
    text = (
        "run,rail,Voltage,Current(mA),Power(mW)\n"
        "1,VDD_CAM,0.7,10.0,7.0\n"
        "2,VDD_CAM,0.71,10.5,7.4\n"
    )
    table = parse_bench_wide(text, source="all_runs.csv")
    assert table.has_run_column
    assert [row["run"] for row in table.rows] == [1, 2]


def test_parse_rejects_unknown_voltage_unit():
    with pytest.raises(BenchParseError, match="unsupported voltage unit"):
        parse_bench_wide("rail Voltage(kV) Current(mA) Power(mW)\nX 1 2 3\n", source="s")


def test_parse_rejects_missing_header():
    with pytest.raises(BenchParseError, match="no header line"):
        parse_bench_wide("just some text\nwithout a table\n", source="s")


def test_parse_rejects_non_numeric_value():
    with pytest.raises(BenchParseError, match="not numeric"):
        parse_bench_wide(
            "rail Voltage Current(mA) Power(mW)\nVDD_X abc 2 3\n", source="s"
        )


def test_run_numbers_from_filename_digits_win_over_order(tmp_path: Path):
    paths = [tmp_path / "power_run3.txt", tmp_path / "power_run1.txt", tmp_path / "power_run2.txt"]
    assert assign_run_numbers(paths) == {paths[0]: 3, paths[1]: 1, paths[2]: 2}


def test_run_numbers_fall_back_to_sorted_order_on_collision(tmp_path: Path):
    paths = [tmp_path / "b.txt", tmp_path / "a.txt"]
    assert assign_run_numbers(paths) == {tmp_path / "a.txt": 1, tmp_path / "b.txt": 2}


def test_convert_writes_long_csv(tmp_path: Path):
    for run in (1, 2):
        (tmp_path / f"run{run}.txt").write_text(
            "rail Voltage Current(mA) Power(mW)\n"
            f"VDD_CAM 0.7 10.{run} 7.{run}\n"
            f"VDD_MIF 0.5 20.{run} 10.{run}\n",
            encoding="utf-8",
        )
    out = tmp_path / "long.csv"
    report = ImportReport()
    ok = bench_files_to_rail_long(
        [tmp_path / "run1.txt", tmp_path / "run2.txt"], out, report=report
    )
    assert ok and report.ok
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert len(rows) == 4
    assert {(r["run"], r["rail"]) for r in rows} == {
        ("1", "VDD_CAM"), ("1", "VDD_MIF"), ("2", "VDD_CAM"), ("2", "VDD_MIF"),
    }


def test_convert_warns_on_inconsistent_rail_sets(tmp_path: Path):
    (tmp_path / "run1.txt").write_text(
        "rail Voltage Current(mA) Power(mW)\nVDD_CAM 0.7 10 7\n", encoding="utf-8"
    )
    (tmp_path / "run2.txt").write_text(
        "rail Voltage Current(mA) Power(mW)\nVDD_MIF 0.5 20 10\n", encoding="utf-8"
    )
    report = ImportReport()
    ok = bench_files_to_rail_long(
        [tmp_path / "run1.txt", tmp_path / "run2.txt"], tmp_path / "o.csv", report=report
    )
    assert ok
    assert any(m.code == "bench_inconsistent_rail_sets" for m in report.messages)


def test_convert_rejects_run_column_mixed_with_multiple_files(tmp_path: Path):
    (tmp_path / "all.csv").write_text(
        "run,rail,Voltage,Current(mA),Power(mW)\n1,VDD_CAM,0.7,10,7\n", encoding="utf-8"
    )
    (tmp_path / "extra.txt").write_text(
        "rail Voltage Current(mA) Power(mW)\nVDD_CAM 0.7 10 7\n", encoding="utf-8"
    )
    report = ImportReport()
    ok = bench_files_to_rail_long(
        [tmp_path / "all.csv", tmp_path / "extra.txt"], tmp_path / "o.csv", report=report
    )
    assert not ok
    assert any(m.code == "bench_mixed_run_semantics" for m in report.messages)


def test_committed_bench_example_reproduces_path_a_digest(tmp_path: Path):
    """Acceptance: the committed wide bench export, run through the adapter,
    must yield the exact digest of the committed rail_long CSV."""
    out = tmp_path / "rail_long.csv"
    report = ImportReport()
    files = sorted(BENCH_EXPORT.glob("*.txt"))
    assert len(files) == 3
    assert bench_files_to_rail_long(files, out, report=report)

    meta = MeasurementImportMeta.model_validate(
        {
            "project_ref": "proj-sm-s947b",
            "scenario_ref": "uc-camera-recording",
            "variant_ref": "cam-rec-r1-uhd30-vdis",
            "measured_at": "2026-06-14T11:00:00+09:00",
            "execution_context": {
                "silicon_rev": "EVT1",
                "sw_baseline_ref": "sw-vendor-v1.2.3",
                "thermal": "room",
            },
            "power": {"csv": "x.csv", "format": "rail_long", "rails": {}},
        }
    )
    from_bench = aggregate_power_rail_long(out, meta.power)
    from_committed = aggregate_power_rail_long(PATH_A_CSV, meta.power)

    assert from_bench.total_power_mw == from_committed.total_power_mw
    assert from_bench.vdd_power == from_committed.vdd_power
    assert from_bench.sample_count == from_committed.sample_count == 3


def test_cli_main_converts_directory(tmp_path: Path, capsys):
    out = tmp_path / "long.csv"
    rc = main(["--in", str(BENCH_EXPORT), "--out", str(out)])
    assert rc == 0
    assert out.exists()
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert len(rows) == 48  # 3 runs x 16 rails


def test_cli_main_reports_missing_input(tmp_path: Path, capsys):
    rc = main(["--in", str(tmp_path / "nope"), "--out", str(tmp_path / "o.csv")])
    assert rc == 1


def test_meas_import_cli_bench_in_is_turnkey(tmp_path: Path, capsys):
    """Raw bench export dir + meta.yaml -> canonical evidence in one command."""
    import shutil

    import yaml

    from scenario_db.meas_import.cli import main as cli_main

    meta_dst = tmp_path / "meta.yaml"
    shutil.copy(
        REPO / "examples" / "measurement-import" / "path-a-capture" / "meta.yaml",
        meta_dst,
    )
    out = tmp_path / "generated"
    rc = cli_main(
        [
            "--meta", str(meta_dst),
            "--out", str(out),
            "--bench-in", str(BENCH_EXPORT),
            "--skip-perfetto",
        ]
    )
    assert rc == 0
    # the adapter materialized the CSV next to the meta, not the repo copy
    assert (tmp_path / "rail_power_by_run.csv").exists()
    doc = yaml.safe_load(
        next((out / "03_evidence").glob("*.yaml")).read_text(encoding="utf-8")
    )
    committed = yaml.safe_load(
        (
            REPO / "examples" / "measurement-import" / "path-b-canonical"
            / "meas-example-canonical.yaml"
        ).read_text(encoding="utf-8")
    )
    assert doc["kpi"]["total_power_mw"] == committed["kpi"]["total_power_mw"]
    assert doc["vdd_power"] == committed["vdd_power"]


def test_meas_import_cli_bench_in_requires_rail_long(tmp_path: Path, capsys):
    import yaml

    from scenario_db.meas_import.cli import main as cli_main

    meta = {
        "project_ref": "proj-x",
        "scenario_ref": "uc-x",
        "variant_ref": "v1",
        "measured_at": "2026-06-14T11:00:00+09:00",
        "execution_context": {
            "silicon_rev": "EVT1",
            "sw_baseline_ref": "sw-x",
            "thermal": "room",
        },
        "power": {"csv": "wide.csv", "rails": {}},  # default wide format
    }
    meta_path = tmp_path / "meta.yaml"
    meta_path.write_text(yaml.safe_dump(meta), encoding="utf-8")
    rc = cli_main(
        [
            "--meta", str(meta_path),
            "--out", str(tmp_path / "gen"),
            "--bench-in", str(BENCH_EXPORT),
            "--strict",
        ]
    )
    assert rc == 1
    assert "bench_requires_rail_long" in capsys.readouterr().out
