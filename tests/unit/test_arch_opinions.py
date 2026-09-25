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
    assert "EIS on/off 그룹 평균 차이" in text and "UHD HEVC (30 fps) +60 mW" in text
    assert "APV vs HEVC" in text and "UHD EIS off (30 fps) +40 mW" in text
    assert "BW 비중이 가장 커서" in text
    assert blocks["highspeed"]["spec_ok"] == 0 and any("미달 원인" in o for o in blocks["highspeed"]["opinions"])


def test_nonrecording_and_explicit_codecs_are_not_assumed_hevc():
    assert classify('playback', 'uc-video-playback', 30, False, {})['category'] == 'other'
    assert classify('cam-rec-test', 'uc-camera-recording', 30, False, {'codec_mfc': 'h264'})['codec'] == 'H264'


def test_fps_groups_do_not_imply_controlled_eis_effect():
    rows = [_row('cam-rec-a', 'uc-camera-recording', 24, False, 100, {'resolution': 'UHD'}),
            _row('cam-rec-b', 'uc-camera-recording', 30, True, 200, {'resolution': 'UHD'})]
    text = ' '.join(build_opinions(rows, [])[0]['opinions'])
    assert 'EIS on/off 그룹 평균 차이' not in text


def test_domain_headroom_keeps_scenario_identity_and_bw_is_not_double_counted():
    row = _row('cam-rec-shared', 'uc-camera-recording', 30, False, 100)
    row['power'] = {'total_mw': 100, 'cpu_mw': 30, 'hw_mw': 30, 'bw_mw': 40, 'bw_cpu_mw': 10}
    domains = [dict(scenario_id='other', variant_id='cam-rec-shared', headroom_pct=0,
                    domain='wrong', level=1, speed_mhz=100, required_mhz=100),
               dict(scenario_id='uc-camera-recording', variant_id='cam-rec-shared', headroom_pct=20,
                    domain='correct', level=2, speed_mhz=120, required_mhz=100)]
    block = build_opinions([row], domains)[0]
    assert block['share_pct']['BW'] == 40
    assert 'correct' in ' '.join(block['opinions'])
    assert 'wrong' not in ' '.join(block['opinions'])


def test_heavy_highspeed_and_missing_power_keep_explicit_limits():
    rows = [_row('cam-rec-dual', 'uc-camera-recording', 30, False, 100),
            _row('cam-rec-portrait', 'uc-camera-recording', 30, False, 200),
            _row('cam-rec-fast', 'uc-camera-recording', 120, False, 300),
            _row('cam-rec-fhd60', 'uc-camera-recording', 60, False, 200),
            _row('cam-rec-uhd60', 'uc-camera-recording', 60, False, 300)]
    rows[0]['sw_margin_pct'] = 2
    rows[1]['power'] = {}
    blocks = {b['category']: b for b in build_opinions(rows, [])}
    heavy = ' '.join(blocks['heavy']['opinions'])
    assert 'contention' in heavy and '과소 추정' in heavy and 'SW 증가 여유 부족' in heavy
    assert any('batch' in text for text in blocks['highspeed']['opinions'])
    assert any('UHD60 vs FHD60' in text for text in blocks['fps60']['opinions'])
