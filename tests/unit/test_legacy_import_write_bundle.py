from __future__ import annotations

import json

from scenario_db.legacy_import.write_bundle import (
    build_import_bundle_request,
    build_soc_dvfs_table_bundle_request,
    main,
)


def test_build_import_bundle_request_includes_sw_profile(tmp_path):
    generated = tmp_path / "generated"
    sw_dir = generated / "01_sw"
    sw_dir.mkdir(parents=True)
    (generated / "import_report.json").write_text(
        json.dumps({"ok": True, "generated": {"validated_yaml": 1}, "messages": []}),
        encoding="utf-8",
    )
    (sw_dir / "sw-vendor-v1.2.3.yaml").write_text(
        """
id: sw-vendor-v1.2.3
schema_version: "2.2"
kind: sw_profile
metadata:
  baseline_family: vendor
  version: "1.2.3"
  compatible_soc:
    - soc-exynos2600
components:
  hal:
    - domain: camera
      ref: hal-cam-v4.5
  kernel:
    ref: kernel-6.12-android16
    config_deltas: []
  firmware: []
feature_flags:
  LLC_dynamic_allocation: enabled
compatibility:
  min_compatible_version: "v1.2.0"
""".strip(),
        encoding="utf-8",
    )

    payload, issues = build_import_bundle_request(
        generated,
        actor="Joo Younghwan",
        note="unit test",
    )

    assert issues == []
    assert payload["kind"] == "scenario.import_bundle"
    assert payload["actor"] == "Joo Younghwan"
    assert payload["payload"]["documents"][0]["kind"] == "sw_profile"
    assert payload["payload"]["documents"][0]["id"] == "sw-vendor-v1.2.3"


def test_build_import_bundle_request_includes_soc_dvfs_table(tmp_path):
    generated = tmp_path / "generated"
    hw_dir = generated / "00_hw"
    hw_dir.mkdir(parents=True)
    (generated / "import_report.json").write_text(
        json.dumps({"ok": True, "generated": {"validated_yaml": 2}, "messages": []}),
        encoding="utf-8",
    )
    (hw_dir / "soc-A.yaml").write_text(
        """
id: soc-A
schema_version: "2.2"
kind: soc
process_node: 3nm
ips: []
""".strip(),
        encoding="utf-8",
    )
    (hw_dir / "dvfs-soc-A-v4.yaml").write_text(
        """
id: dvfs-soc-A-v4
schema_version: "2.3"
kind: soc.dvfs_table
soc_ref: soc-A
dvfs_version: 4
evt_hint: EVT1
source:
  guide_name: camera_dvfs_guide
  source_revision: EVT1
domains:
  CAM:
    domain: CAM
    levels:
      - {level: 0, speed_mhz: 800.0, voltages: {"4": 800.0}}
      - {level: 4, speed_mhz: 332.0, voltages: {"4": 606.25}}
""".strip(),
        encoding="utf-8",
    )

    payload, issues = build_import_bundle_request(generated)

    assert issues == []
    assert [doc["kind"] for doc in payload["payload"]["documents"]] == ["soc", "soc.dvfs_table"]
    assert payload["payload"]["documents"][1]["dvfs_version"] == 4


def test_build_soc_dvfs_table_bundle_request_core_builder():
    payload = build_soc_dvfs_table_bundle_request(
        soc_ref="soc-exynos2700",
        dvfs_version=5,
        domains={"CAM": {"domain": "CAM", "levels": []}},
        actor="cli",
        note="dvfs update",
        evt_hint="EVT1",
        guide_name="camera_dvfs_guide",
    )

    doc = payload["payload"]["documents"][0]
    assert payload["kind"] == "scenario.import_bundle"
    assert doc["kind"] == "soc.dvfs_table"
    assert doc["id"] == "dvfs-soc-exynos2700-v5"
    assert doc["dvfs_version"] == 5
    assert doc["evt_hint"] == "EVT1"


def test_write_bundle_cli_builds_soc_dvfs_table_bundle(tmp_path):
    domains_path = tmp_path / "domains.json"
    out_path = tmp_path / "import_bundle.json"
    domains_path.write_text(
        json.dumps({"CAM": {"domain": "CAM", "levels": [{"level": 0, "speed_mhz": 800.0, "voltages": {"4": 800.0}}]}}),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--soc-ref",
            "soc-exynos2700",
            "--dvfs-version",
            "6",
            "--evt-hint",
            "EVT1",
            "--guide-name",
            "camera_dvfs_guide",
            "--domains-json",
            str(domains_path),
            "--out",
            str(out_path),
            "--actor",
            "cli",
            "--note",
            "dvfs update",
        ]
    )

    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert written["payload"]["documents"][0]["id"] == "dvfs-soc-exynos2700-v6"
    assert written["payload"]["documents"][0]["source"]["guide_name"] == "camera_dvfs_guide"
