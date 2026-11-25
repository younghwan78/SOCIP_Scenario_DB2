"""Step 0 of the scenario expansion (E2600 data only).

- G-0: a game variant is judged at its target frame rate (design_conditions.fps = target_fps).
- A-0: a CPU audio decoder runs on its own codec-frame period, not at the 30 Hz default scenario rate.
- C-1: camera preview / capture ISP nodes compute (sizes follow the sensor mode).
- C-2: the preview session is 12M (binning_4x4; a 30 fps session pins it at 30 fps); 50M / 200M are read only at capture (seamless mode change, event job).
"""

import pytest
import yaml

from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph

ROOT = "db_Exynos2600_SM-S947B/02_definition"
ISP = {"csispdp", "byrp", "rgbp", "yuvsc", "mtnr", "msnr", "yuvp", "mcsc", "gdc_m", "dpu"}


def _variants(scenario):
    with open(f"{ROOT}/{scenario}.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["variants"]


def test_game_variants_are_judged_at_their_target_fps():
    for v in _variants("uc-game-play-e2600"):
        dc = v["design_conditions"]
        # R-1: the rate comes from judgement.rate (target_fps); design fps stays equal (views / replay read it)
        assert dc["fps"] == dc["target_fps"], v["id"]
        report = analyze_timing_budget(_exynos2600_generated_graph("uc-game-play-e2600", v["id"]),
                                       TimingBudgetOptions(throughput_model="pipelined"))
        assert report["period_ms"] == pytest.approx(1000.0 / dc["target_fps"], abs=1e-3), v["id"]


# decode-call period = samples per codec frame / sample rate
DECODER_PERIOD_MS = {
    ("uc-aud-mp3-playback-e2600", "audio-mp3-screen-on"): 1152 / 48.0,        # MP3, 48 kHz
    ("uc-aud-mp3-playback-e2600", "audio-flac-hires-screen-off"): 4096 / 192.0,  # FLAC block, 192 kHz
    ("uc-aud-mp3-playback-e2600", "audio-aac-bt-screen-on"): 1024 / 48.0,     # AAC-LC, 48 kHz
    ("uc-aud-streaming-e2600", "audio-stream-aac-screen-on"): 1024 / 48.0,
    ("uc-aud-streaming-e2600", "audio-stream-aac-screen-off"): 1024 / 48.0,
    ("uc-aud-streaming-e2600", "audio-stream-bt-screen-off"): 1024 / 48.0,
}


@pytest.mark.parametrize(("scenario", "variant"), sorted(DECODER_PERIOD_MS))
def test_cpu_audio_decoder_runs_on_its_codec_frame_period(scenario, variant):
    report = analyze_timing_budget(_exynos2600_generated_graph(scenario, variant))
    rows = {r["node"]: r for r in report.get("own_cadence") or []}
    assert rows["sw_decoder"]["period_ms"] == pytest.approx(DECODER_PERIOD_MS[(scenario, variant)], abs=1e-3)
    assert rows["sw_decoder"]["ok"] is True


def test_offloaded_decode_has_no_cpu_decoder_cadence():
    report = analyze_timing_budget(_exynos2600_generated_graph("uc-aud-mp3-playback-e2600",
                                                               "audio-mp3-screen-off-offload"))
    assert "sw_decoder" not in {r["node"] for r in report.get("own_cadence") or []}


@pytest.mark.parametrize("scenario", ["uc-cam-preview-e2600", "uc-cam-capture-e2600"])
def test_camera_isp_computes_and_the_session_is_a_12m_preview(scenario):
    for v in _variants(scenario):
        g = _exynos2600_generated_graph(scenario, v["id"])
        report = analyze_timing_budget(g, TimingBudgetOptions(throughput_model="pipelined"))
        zero = sorted(i["node"] for i in report["ips"] if i["node"] in ISP and not i.get("power_mw"))
        assert zero == [], (v["id"], zero)
        assert report["verdict"]["status"] != "fail", (v["id"], report["verdict"]["reasons"])
        if "sensor_rear" in ((v.get("routing_switch") or {}).get("disabled_nodes") or []):
            continue
        sensor_mode = ((v.get("node_configs") or {}).get("sensor_rear") or {}).get("selected_mode")
        if v["id"] in ("cam-prev-r1-pro", "cam-cap-r1-sf-pro"):   # pro mode: 16:9 wide video crop
            assert sensor_mode == "wide_video_16_9_30", v["id"]
            from scenario_db.sim.external_devices import active_sensor_nodes, selected_sensor_mode
            resolved = selected_sensor_mode(g, next(n for n in active_sensor_nodes(g) if n["id"] == "sensor_rear"))
            assert resolved["sensor_size"] == [4080, 2296] and resolved["sensor_bitwidth"] == 12, v["id"]
        else:
            assert sensor_mode == "binning_4x4", v["id"]      # 12M (30 fps sessions: resolved_sensor_mode at 30)
            assert (v.get("size_overrides") or {}).get("sensor_out", "4000x3000") == "4000x3000", v["id"]
        assert report["fps"] >= 30.0, v["id"]


@pytest.mark.parametrize("scenario", ["uc-cam-preview-e2600", "uc-cam-capture-e2600"])
def test_active_sensors_run_at_the_session_fps_and_one_size(scenario):
    from scenario_db.sim.external_devices import active_sensor_nodes, selected_sensor_mode

    bad = []
    for v in _variants(scenario):
        fps = float((v.get("design_conditions") or {}).get("fps") or 30)
        graph = _exynos2600_generated_graph(scenario, v["id"])
        nodes = active_sensor_nodes(graph)
        modes = {n["id"]: selected_sensor_mode(graph, n) or {} for n in nodes}
        for node, mode in modes.items():
            if float(mode.get("sensor_fps") or 0) != fps:
                bad.append(f"{v['id']}.{node}: sensor {mode.get('sensor_fps')} fps, session {fps} fps")
        # instances of one sensor (rear, rear2, rear3 share csispdp) read one size; PIP mixes different sensors
        for ip in {n["ip_ref"] for n in nodes}:
            sizes = {n["id"]: modes[n["id"]].get("sensor_size") for n in nodes if n["ip_ref"] == ip}
            if len({tuple(z or ()) for z in sizes.values()}) > 1:
                bad.append(f"{v['id']}: {ip} sizes differ {sizes}")
    assert not bad, bad
