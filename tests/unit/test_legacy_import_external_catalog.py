from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import yaml

from scenario_db.legacy_import.cli import main
from scenario_db.legacy_import.normalize_display import convert_display_catalog
from scenario_db.legacy_import.normalize_sensor import convert_sensor_catalog
from scenario_db.legacy_import.report import ImportReport
from scenario_db.models.capability.hw import IpCatalog


def _legacy_sensors() -> dict:
    return {
        "HP2": {
            "mode1": {
                "sensor_name": "A-08 SENSOR_HP2_4000x2252_60FPS_12BIT",
                "sensor_size": [4000, 2252],
                "sensor_fps": 60.0,
                "sensor_pclk": 1_760_000_000,
                "sensor_line_length_pck": 6440,
                "sensor_format": "BAYER",
                "sensor_bitwidth": 12,
                "sensor_mipi_speed": 3.712,
                "sensor_sbwc": "enable",
                "sensor_phy_type": "CPHY",
            },
            "mode2": {
                "sensor_name": "A-08 SENSOR_HP2_1920x1080_120FPS_10BIT",
                "sensor_size": [1920, 1080],
                "sensor_fps": 120.0,
                "sensor_pclk": 1_200_000_000,
                "sensor_line_length_pck": 3000,
                "sensor_format": "BAYER",
                "sensor_bitwidth": 10,
                "sensor_mipi_speed": 2.4,
                "sensor_sbwc": "disable",
                "sensor_phy_type": "CPHY",
            },
        },
        "GNG": {
            "default": {
                "sensor_size": [3264, 2448],
                "sensor_fps": 30.0,
                "sensor_format": "BAYER",
                "sensor_bitwidth": 10,
            },
        },
    }


def _legacy_displays() -> dict:
    return {
        "FHD_PANEL": {
            "display_size": [2400, 1080],
            "ppi": 420,
            "refresh_rates": [60, 120],
            "bitdepth": [8, 10],
            "hdr_formats": ["SDR", "HDR10"],
        }
    }


def test_convert_sensor_catalog_preserves_modes_and_calculates_v_valid():
    report = ImportReport()
    docs = convert_sensor_catalog(
        _legacy_sensors(),
        project_ref="proj-projectA",
        schema_version="2.2",
        report=report,
    )

    assert report.ok
    assert report.generated["sensor_catalog"] == 2
    hp2 = docs[0]
    assert hp2["id"] == "ip-sensor-hp2-projecta"
    assert hp2["category"] == "sensor"
    assert {mode["id"] for mode in hp2["capabilities"]["operating_modes"]} == {"mode1", "mode2"}
    assert hp2["capabilities"]["supported_features"]["bitdepth"] == [10, 12]
    assert hp2["capabilities"]["supported_features"]["compression"] == ["SBWC_v4"]
    assert hp2["capabilities"]["properties"]["modes"]["mode1"]["v_valid_ms"] == 8.240273

    for doc in docs:
        IpCatalog.model_validate(doc)


def test_convert_display_catalog_preserves_panel_properties():
    report = ImportReport()
    docs = convert_display_catalog(
        _legacy_displays(),
        project_ref="proj-projectA",
        schema_version="2.2",
        report=report,
    )

    assert report.ok
    assert report.generated["display_catalog"] == 1
    display = docs[0]
    assert display["id"] == "ip-display-fhd-panel-projecta"
    assert display["category"] == "display"
    assert [mode["id"] for mode in display["capabilities"]["operating_modes"]] == ["60hz", "120hz"]
    assert display["capabilities"]["supported_features"]["bitdepth"] == [8, 10]
    assert display["capabilities"]["supported_features"]["hdr_formats"] == ["SDR", "HDR10"]
    assert display["capabilities"]["properties"]["display_size"] == [2400, 1080]
    assert display["capabilities"]["properties"]["ppi"] == 420

    IpCatalog.model_validate(display)


def test_legacy_import_cli_emits_sensor_and_display_catalog_yaml():
    tmp_path = Path(__file__).parents[2] / f"_tmp_legacy_external_import_{uuid.uuid4().hex}"
    try:
        tmp_path.mkdir()
        sensor_path = tmp_path / "sensor_config.yaml"
        display_path = tmp_path / "display_config.yaml"
        out_dir = tmp_path / "generated"
        sensor_path.write_text(yaml.safe_dump({"sensors": _legacy_sensors()}, sort_keys=False), encoding="utf-8")
        display_path.write_text(yaml.safe_dump({"displays": _legacy_displays()}, sort_keys=False), encoding="utf-8")

        exit_code = main([
            "--sensor",
            str(sensor_path),
            "--display",
            str(display_path),
            "--out",
            str(out_dir),
            "--project",
            "proj-projectA",
            "--strict",
        ])

        assert exit_code == 0
        generated = sorted((out_dir / "00_hw").glob("*.yaml"))
        assert [path.name for path in generated] == [
            "ip-display-fhd-panel-projecta.yaml",
            "ip-sensor-gng-projecta.yaml",
            "ip-sensor-hp2-projecta.yaml",
        ]
        for path in generated:
            IpCatalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

        report = json.loads((out_dir / "import_report.json").read_text(encoding="utf-8"))
        assert report["ok"] is True
        assert report["generated"]["sensor_catalog"] == 2
        assert report["generated"]["display_catalog"] == 1
    finally:
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
