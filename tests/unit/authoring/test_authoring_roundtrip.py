from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scenario_db.authoring import yamlio
from scenario_db.authoring.cli import check_against, write_worksheet
from scenario_db.authoring.patch import deep_merge, make_patch
from scenario_db.authoring.scenario import AuthoringError, expand_variants
from scenario_db.authoring.tree import compile_project
from scenario_db.authoring.validate import validate_documents

REPO = Path(__file__).resolve().parents[3]
AUTHORING = REPO / "authoring"
FIXTURE = REPO / "db_fixtures_Exynos2600_S26Plus"
EXAMPLE_2800 = AUTHORING / "examples" / "exynos2800-pipeline-change"


def _docs(report: dict) -> dict[str, dict]:
    return {d.data["id"]: d.data for d in report["documents"] if isinstance(d.data, dict) and "id" in d.data}


def _variant(doc: dict, vid: str) -> dict:
    return next(v for v in doc["variants"] if v["id"] == vid)


@pytest.fixture()
def scratch_root(tmp_path: Path) -> Path:
    root = tmp_path / "authoring"
    shutil.copytree(AUTHORING, root, ignore=shutil.ignore_patterns("examples"))
    return root


# --- patch semantics --------------------------------------------------------

def test_make_patch_roundtrips_with_unset_and_type_changes():
    base = {"a": 1, "b": {"c": [1, 2], "d": "x"}, "gone": True, "f": 30}
    target = {"a": 1, "b": {"c": [1, 2, 3]}, "new": {"k": 1}, "f": 30.0}
    patch = make_patch(base, target)
    assert patch["$unset"] == ["gone"]
    assert deep_merge(base, patch) == target
    assert type(deep_merge(base, patch)["f"]) is float


def test_expand_variants_rejects_cycles_and_unknown_parents():
    with pytest.raises(AuthoringError, match="cycle"):
        expand_variants([{"id": "a", "extends": "b"}, {"id": "b", "extends": "a"}])
    with pytest.raises(AuthoringError, match="unknown variant"):
        expand_variants([{"id": "a", "extends": "zz"}])


# --- Exynos2600: authoring is lossless vs. the canonical fixture ------------

def test_exynos2600_authoring_compiles_to_the_canonical_fixture():
    assert check_against(AUTHORING, "sm-s947b", FIXTURE) == []


def test_exynos2600_compiled_documents_validate():
    report = compile_project(AUTHORING, "sm-s947b")
    result = validate_documents(report["documents"])
    assert result["errors"] == []
    assert report["impact"] == {}


# --- Exynos2700: inherit + rename + measurement slots -----------------------

def test_e2700_inherits_all_scenarios_with_renamed_ids():
    report = compile_project(AUTHORING, "e2700-ref")
    docs = _docs(report)
    assert validate_documents(report["documents"])["errors"] == []
    assert "soc-exynos2700" in docs and "proj-e2700-ref" in docs
    assert not [i for i in docs if i.startswith("ip-") and "s5e9965" in i]
    assert docs["proj-e2700-ref"]["metadata"]["soc_ref"] == "soc-exynos2700"
    assert docs["simcfg-proj-e2700-ref-v1"]["status"] == "draft"
    rec = docs["uc-camera-recording-e2700"]
    assert rec["project_ref"] == "proj-e2700-ref"
    assert rec["metadata"]["canonical_usecase"] == "uc-camera-recording"
    assert len(rec["variants"]) == 75
    assert all(n["ip_ref"].endswith("exynos2700") for n in rec["pipeline"]["nodes"])
    # shared sensor DT catalogs keep their ids (rename_exclude)
    assert "sensor-gng-m2s" in docs
    # pending measurement slots are reported, baseline kept
    assert report["measurements"]["uc-camera-recording-e2700"]["pending"] > 0


def test_sw_timing_measurement_overrides_only_the_selected_scope(scratch_root: Path):
    target = scratch_root / "projects/e2700-ref/scenarios/uc-camera-recording/sw_timing.measured.yaml"
    yamlio.dump(target, {"entries": [{
        "task": "post_crta", "group": "post_crta-a", "when": {"resolution": "UHD"},
        "timing": {"mean_ms": 0.42, "value_source": "measured", "source_note": "perfetto test"},
    }]})
    rec = _docs(compile_project(scratch_root, "e2700-ref"))["uc-camera-recording-e2700"]
    uhd = _variant(rec, "cam-rec-r1-uhd30-sdr")["node_configs"]["post_crta"]["sw_timing"]
    fhd = _variant(rec, "cam-rec-r1-fhd30-sdr")["node_configs"]["post_crta"]["sw_timing"]
    assert uhd["mean_ms"] == 0.42 and uhd["value_source"] == "measured" and uhd["max_ms"] == 0.5
    assert fhd["mean_ms"] == 0.3 and fhd["value_source"] == "assumed"


def test_worksheet_does_not_overwrite_existing_slots(scratch_root: Path):
    assert write_worksheet(scratch_root, "e2700-ref") == []


def test_derived_anchor_drives_bound_node_sizes(scratch_root: Path):
    """EIS-margin style rule: eis_in = record_out * 1.25 (16-aligned) feeding MSNR."""
    overlay = scratch_root / "projects/e2700-ref/scenarios/uc-camera-recording/overlay.yaml"
    yamlio.dump(overlay, {"sizes": {
        "derived": {"eis_in": {"from": "record_out", "scale": 1.25, "align": 16}},
        "bindings": {"msnr": "eis_in"},
    }})
    rec = _docs(compile_project(scratch_root, "e2700-ref"))["uc-camera-recording-e2700"]
    v = _variant(rec, "cam-rec-r1-fhd30-sdr")
    assert v["size_overrides"]["eis_in"] == "2400x1360"
    assert (v["node_configs"]["msnr"]["sim"]["width"], v["node_configs"]["msnr"]["sim"]["height"]) == (2400, 1360)
    u = _variant(rec, "cam-rec-r1-uhd30-sdr")
    assert u["size_overrides"]["eis_in"] == "4800x2704"


# --- Exynos2800-style pipeline change ---------------------------------------

def test_pipeline_change_example(scratch_root: Path):
    for sub in ("platforms", "projects"):
        shutil.copytree(EXAMPLE_2800 / sub, scratch_root / sub, dirs_exist_ok=True)
    report = compile_project(scratch_root, "e2800-concept")
    assert validate_documents(report["documents"])["errors"] == []
    rec = _docs(report)["uc-camera-recording-e2800c"]
    nodes = {n["id"]: n for n in rec["pipeline"]["nodes"]}
    assert "msnr" not in nodes
    assert nodes["mtnr"]["ip_ref"] == "ip-nr-v2-exynos2800c"
    assert any(e["from"] == "mtnr" and e["to"] == "yuvp" for e in rec["pipeline"]["edges"])
    impact = report["impact"]["uc-camera-recording-e2800c"]
    assert impact and all("msnr" in line for line in impact)
    assert all("msnr" not in (v.get("node_configs") or {}) for v in rec["variants"])


def test_pipeline_change_without_prune_fails_with_impact_list(scratch_root: Path):
    for sub in ("platforms", "projects"):
        shutil.copytree(EXAMPLE_2800 / sub, scratch_root / sub, dirs_exist_ok=True)
    overlay_path = scratch_root / "projects/e2800-concept/scenarios/uc-camera-recording-e2700/overlay.yaml"
    overlay = yamlio.load(overlay_path)
    overlay["prune_missing_nodes"] = False
    yamlio.dump(overlay_path, overlay)
    with pytest.raises(AuthoringError, match="node_configs.msnr"):
        compile_project(scratch_root, "e2800-concept")
