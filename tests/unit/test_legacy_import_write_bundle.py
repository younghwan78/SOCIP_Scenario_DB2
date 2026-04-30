from __future__ import annotations

import json

from scenario_db.legacy_import.write_bundle import build_import_bundle_request


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
