"""Step 0 of the scenario expansion (E2600 data only).

- G-0: a game variant is judged at its target frame rate (design_conditions.fps = target_fps).
- A-0: a CPU audio decoder runs on its own codec-frame period, not at the 30 Hz default scenario rate.
- C-1: camera preview / capture ISP nodes compute (sizes follow the sensor mode); a full_remosaic session is judged
  at the sensor's 10 fps.
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
def test_camera_isp_computes_and_full_remosaic_runs_at_the_sensor_rate(scenario):
    for v in _variants(scenario):
        g = _exynos2600_generated_graph(scenario, v["id"])
        report = analyze_timing_budget(g, TimingBudgetOptions(throughput_model="pipelined"))
        zero = sorted(i["node"] for i in report["ips"] if i["node"] in ISP and not i.get("power_mw"))
        assert zero == [], (v["id"], zero)
        assert report["verdict"]["status"] != "fail", (v["id"], report["verdict"]["reasons"])
        sensor_mode = ((v.get("node_configs") or {}).get("sensor_rear") or {}).get("selected_mode")
        if sensor_mode == "full_remosaic":
            assert report["fps"] == pytest.approx(10.0), v["id"]
