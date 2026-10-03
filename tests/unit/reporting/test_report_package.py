from __future__ import annotations

import hashlib
import io
import json
from zipfile import ZipFile

from scenario_db.reporting.report_package import build_manifest, package_zip

HTML = "<html><body>frozen</body></html>"
META = {"id": "RPT-1", "title": "E2600 camera", "status": "published", "project_ref": "proj-a", "target_soc_ref": "s5e9965",
        "scenario_type": "camera", "engine_rev": "arch-exploration/7", "dvfs_table_ref": "dvfs-x", "generated_by": "joo",
        "generated_at": "2026-10-04T10:00:00+00:00", "run_ids": ["EXP-1"], "html_sha256": hashlib.sha256(HTML.encode()).hexdigest()}
SNAP = {"spec_summary": {"requested": 3, "evaluated": 2, "calc_failed": 1, "spec_ok": 2, "spec_fail": 0, "power_partial": 2, "errors": [{}]},
        "scenarios": [{"scenario_id": "s", "variant_id": "a", "prediction_id": "P-1", "spec_ok": True},
                      {"scenario_id": "s", "variant_id": "b", "prediction_id": None, "spec_ok": True}],
        "calibration": [{"variant_id": "a", "measurement_id": "meas-1", "origin": "physical_capture"}], "sw_margin_top5": []}
REVIEWS = [{"status": "published", "reviewer": "kim", "note": "ok", "by": "joo", "at": "2026-10-04T11:00:00+00:00"}]


def test_manifest_identifies_the_reviewed_copy():
    m = build_manifest(META, SNAP, HTML, {"EXP-1": {"input_hash": "abc"}}, REVIEWS)
    assert m["body"]["integrity_ok"] and m["report"]["status"] == "published"
    assert m["review_history"][0]["reviewer"] == "kim"
    assert m["runs"][0]["input_hash"] == "abc"
    assert m["measurements"][0]["measurement_id"] == "meas-1"
    assert m["coverage"]["calc_failed"] == 1 and m["coverage"]["not_registered"] == 1


def test_tampered_body_is_flagged():
    m = build_manifest(META, SNAP, HTML + " ", {}, [])
    assert not m["body"]["integrity_ok"]


def test_package_keeps_body_byte_identical():
    data, name = package_zip(META, SNAP, HTML, {}, REVIEWS)
    z = ZipFile(io.BytesIO(data))
    assert set(z.namelist()) == {"report.html", "cover.html", "manifest.json"}
    assert z.read("report.html").decode() == HTML
    assert "kim" in z.read("cover.html").decode()
    assert json.loads(z.read("manifest.json"))["report"]["id"] == "RPT-1"
    assert name.startswith("RPT-1_published_") and name.endswith(".zip")
