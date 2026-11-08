"""Two-level scenario categories of the review report (CAT-01)."""
from scenario_db.reporting.arch_opinions import OTHER_GROUP, RECORDING, _blocks, classify, group_of
from scenario_db.reporting.review_sections import category_section


def test_group_rules_policy_globs_and_name_fallback():
    assert group_of("uc-cam-recording-apv-e2600") == RECORDING
    assert [group_of(s) for s in ("uc-cam-preview-e2600", "uc-cam-capture-e2600", "uc-vid-youtube-e2600",
                                  "uc-game-play-e2600", "uc-call-voice-e2600", "uc-call-video-e2600", "uc-aud-mp3-playback-e2600")] == [
        "Camera Preview", "Camera Capture", "Video Playback", "Game", "Voice Call", "Video Call", "Audio"]
    assert group_of("uc-xr-passthrough", None, "XR Passthrough") == "XR Passthrough"
    assert group_of("uc-xr-passthrough") == OTHER_GROUP
    assert group_of("uc-cam-recording-e2600", {"uc-cam-rec*": "Video Recording"}) == "Video Recording"


def test_classify_reviews_recording_by_class_and_other_groups_as_one_block():
    rec = classify("cam-rec-r1-uhd60", "uc-cam-recording-e2600", 60, False, {"resolution": "UHD"})
    assert rec["group"] == RECORDING and rec["category"] == "fps60"
    pre = classify("cam-pre-uhd30", "uc-cam-preview-e2600", 30, False, {})
    assert pre["group"] == "Camera Preview" and pre["category"] == "other"
    # a project renaming the recording scenarios through the policy keeps the recording classes off
    renamed = classify("cam-rec-r1-uhd60", "uc-cam-recording-e2600", 60, False, {}, groups={"uc-cam-rec*": "Video Rec"})
    assert renamed["group"] == "Video Rec" and renamed["category"] == "other"
    rows = [{"variant_id": "cam-rec-a", "cls": rec}, {"variant_id": "cam-pre-a", "cls": pre},
            {"variant_id": "cam-pre-b", "cls": pre}, {"variant_id": "cam-rec-legacy", "cls": {"category": "fps30"}}]
    got = [(g, c, t, len(rs)) for g, c, t, _, rs in _blocks(rows)]
    assert got == [(RECORDING, "fps30", "30 fps recording", 1), (RECORDING, "fps60", "60 fps recording", 1),
                   ("Camera Preview", "other", "Camera Preview", 2)]


def test_category_section_lists_unexplored_categories_as_review_gaps():
    block = {"group": RECORDING, "category": "fps30", "title": "30 fps recording", "scope": "s", "variants": ["cam-rec-a"],
             "spec_ok": 1, "count": 1, "power_range_mw": [300, 400], "share_pct": {}, "opinions": ["ok"], "basis": ["산출"]}
    snap = {"opinions": [block], "review_context": {"policy": {}},
            "coverage": {"rows": [
                {"scenario_id": "uc-cam-recording-e2600", "name": "Camera Recording", "variants": 3, "explored": 1, "registered": 1},
                {"scenario_id": "uc-cam-recording-apv-e2600", "name": "Camera Recording APV", "variants": 2, "explored": 0, "registered": 0},
                {"scenario_id": "uc-game-play-e2600", "name": "Game <Play>", "variants": 8, "explored": 0, "registered": 0}]}}
    html = category_section(snap)
    assert "Category별 검토 범위" in html and "검토 · 1개 분류" in html and "미탐색 — 검토 공백" in html
    assert "Camera Recording APV, Camera Recording" in html or "Camera Recording, Camera Recording APV" in html
    assert "Game &lt;Play&gt;" in html and html.index("Camera Recording") < html.index("Game")
    assert "<div class='grp'><b>Camera Recording</b>" in html and "300–400 mW" in html
    assert category_section({"opinions": []}).startswith("<p class='meta'>분류 정보 없음")


def test_coverage_shows_without_opinions_and_derived_only_review_is_still_a_product_gap():
    cov = {"rows": [{"scenario_id": "uc-xr-passthrough", "name": "XR Passthrough", "variants": 2, "explored": 0, "registered": 0}]}
    html = category_section({"opinions": [], "coverage": cov})
    assert "Category별 검토 범위" in html and "XR Passthrough" in html and "평가 완료 variant가 없어" in html
    assert "이전 형식" not in html
    block = {"group": "XR Passthrough", "category": "other", "title": "XR Passthrough", "scope": "s", "variants": ["xr-a-sub"],
             "spec_ok": 1, "count": 1, "share_pct": {}, "opinions": ["ok"], "basis": ["산출"]}
    html = category_section({"opinions": [block], "coverage": cov})
    assert "파생 variant만 검토 (1개 분류) — 제품 variant 공백" in html and "<span class=ok>검토" not in html


def test_rows_use_the_scenario_name_fallback_like_the_coverage():
    c = classify("xr-a", "uc-xr-passthrough", 30, False, {}, name="XR Passthrough")
    assert c["group"] == "XR Passthrough" == group_of("uc-xr-passthrough", None, "XR Passthrough")


def test_variant_id_prefix_does_not_override_the_scenario_category():
    c = classify("cam-rec-uhd30", "uc-custom-camera", 30, False, {}, name="Custom Camera")
    assert c["group"] == "Custom Camera" == group_of("uc-custom-camera", None, "Custom Camera") and c["category"] == "other"


def test_empty_scenario_name_falls_back_to_the_id_in_rows_and_coverage():
    from scenario_db.reporting.arch_report import build_snapshot
    from scenario_db.reporting.review_snapshot import ProjectEvidence, ReviewEvidence

    v = {"variant_id": "xr-a", "scenario_id": "uc-xr", "fps": 30, "eis_on": False, "spec_ok": True, "spec_reasons": [],
         "distribution": {}, "recommended": {"total_mw": 100.0, "cpu_mw": 10, "hw_mw": 50, "bw_mw": 40}}
    ev = ReviewEvidence(scope={"kind": "project"}, context={"policy": {}, "rows": [], "battery": {}},
                        references={"references": {}, "tolerance_pct": None},
                        project=ProjectEvidence(project_ref="p", scenarios=[("uc-xr", {"name": ""})], variants=[("uc-xr", "xr-a", None)],
                                                model={"coverage": {}, "offsetting": 0, "flat_cpu": None, "confidence": {}, "bias": {}}))
    snap = build_snapshot({"id": "EXP", "title": "t", "scenario_type": "x", "project_ref": "p", "spec": {}, "variants": [v],
                           "summary": {}}, {}, {}, review=ev)
    assert snap["scenarios"][0]["cls"]["group"] == "uc-xr"
    html = category_section(snap)
    assert "미탐색 — 검토 공백" not in html and "검토 · 1개 분류" in html
