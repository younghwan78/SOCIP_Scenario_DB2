from scenario_db.reporting.arch_opinions import build_opinions, classify


def test_classify_categories():
    assert classify("cam-rec-r1-uhd30-vdis", "uc-camera-recording", 30, True, {"resolution": "UHD"})["category"] == "fps30"
    assert classify("cam-rec-r1-fhd60-sdr", "uc-camera-recording", 60, False, {})["category"] == "fps60"
    assert classify("cam-rec-r1-fhd240", "uc-camera-recording", 240, False, {})["category"] == "highspeed"
    c = classify("cam-rec-r1-uhd30-portrait", "uc-camera-recording", 30, False, {"portrait": 1}, "heavy")
    assert c["category"] == "heavy" and c["heavy_kind"] == "Portrait" and c["severity"] == "heavy"
    assert classify("cam-rec-pip-fhd30", "uc-camera-recording", 30, False, {"camera_mode": "dual_async"})["heavy_kind"] == "Dual"
    assert classify("cam-rec-apv-pro-uhd30-444", "uc-camera-recording-apv", 30, False, {})["heavy_kind"] == "Pro"
    apv = classify("cam-rec-apv-uhd30-422-sdr", "uc-camera-recording-apv", 30, False, {})
    assert apv["codec"] == "APV" and apv["resolution"] == "UHD" and apv["category"] == "fps30"
    # high-speed wins over heavy; 8K parsed from the id
    assert classify("cam-rec-r1-8k30-sdr", "uc-camera-recording", 30, False, {})["resolution"] == "8K"


def _row(vid, sid, fps, eis, total, dc=None, ok=True):
    return {"variant_id": vid, "scenario_id": sid, "spec_ok": ok, "reasons": [] if ok else ["x"], "bw_mbs": 5000.0,
            "power": {"total_mw": total, "cpu_mw": total * 0.3, "hw_mw": total * 0.3, "bw_ip_mw": total * 0.4, "bw_cpu_mw": 0.0},
            "cls": classify(vid, sid, fps, eis, dc or {}), "sw_margin_pct": 12.0, "sw_stage": "nrt", "sw_bottleneck": "eis"}


def test_opinions_pair_eis_and_codec():
    rows = [_row("cam-rec-r1-uhd30-sdr", "uc-camera-recording", 30, False, 500.0),
            _row("cam-rec-r1-uhd30-vdis", "uc-camera-recording", 30, True, 560.0),
            _row("cam-rec-apv-uhd30-422-sdr", "uc-camera-recording-apv", 30, False, 540.0),
            _row("cam-rec-r1-fhd120", "uc-camera-recording", 120, False, 900.0, ok=False)]
    blocks = {b["category"]: b for b in build_opinions(rows, [])}
    text = " ".join(blocks["fps30"]["opinions"])
    assert "EIS on 영향" in text and "UHD HEVC +60 mW" in text
    assert "APV vs HEVC" in text and "UHD EIS off +40 mW" in text
    assert "BW 비중이 가장 커서" in text
    assert blocks["highspeed"]["spec_ok"] == 0 and any("미달 원인" in o for o in blocks["highspeed"]["opinions"])
