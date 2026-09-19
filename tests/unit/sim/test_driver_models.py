from pathlib import Path
import pytest
import yaml
from pydantic import ValidationError
from scenario_db.sim.driver_models import evaluate

ROOT = Path(__file__).parents[3] / "db_fixtures_Exynos2600_S26Plus/00_hw"


def caps(name):
    return yaml.safe_load((ROOT / f"ip-{name}-s5e9965.yaml").read_text(encoding="utf-8"))[
        "capabilities"
    ]


def test_storage_direction_and_decimal_units():
    a = evaluate({"model": "ufs", "bitrate_mbps": 8}, caps("ufs"))
    assert a["write_bytes_s"] == 1_000_000
    assert a["source_kB_s"] == 1000
    assert a["read_bytes_s"] == 0
    assert a["power_mw"] is None
    b = evaluate({"model": "ufs", "bitrate_mbps": 8, "operation": "write"}, caps("ufs"))
    assert b["read_bytes_s"] == 1_000_000 and b["write_bytes_s"] == 0


def test_pcm_and_offload_unknown_refill():
    raw = {
        "model": "abox",
        "sample_rate_khz": 48,
        "bit_depth": 24,
        "channels": 2,
        "playback_streams": 1,
        "capture_streams": 1,
        "offload": False,
    }
    a = evaluate(raw, caps("abox"))
    assert a["read_bytes_s"] == a["write_bytes_s"] == 288000
    assert a["source_KiB_s"] == 562.5
    b = evaluate({**raw, "offload": True}, caps("abox"))
    assert b["read_bytes_s"] is None and b["status"] == "partial"
    assert b["pcm_read_bytes_s"] == a["read_bytes_s"]
    with pytest.raises(ValueError):
        evaluate({**raw, "aud_freq_khz": 123}, caps("abox"))


def scaler(**kwargs):
    return {
        "model": "mscl",
        "src": [1920, 1080],
        "dst": [1440, 3120],
        "fps": 30,
        "src_bpp": 12,
        "dst_bpp": 32,
        "ppc_row": "YUV420",
        **kwargs,
    }


def test_scaler_sizing_qos_and_infeasibility():
    a = evaluate(scaler(), caps("m2m-scaler"))
    assert a["read_bytes_s"] == 93312000
    assert a["write_bytes_s"] == 539136000
    assert a["required_clock_khz"] == pytest.approx(1440 * 3120 * 30 / 4.89 / 1000)
    assert a["selected_qos"]["freq_mscl_khz"] == 88000
    b = evaluate(scaler(fps=10000), caps("m2m-scaler"))
    assert b["status"] == "infeasible" and b["selected_qos"] is None
    c = evaluate(scaler(votf=True, compression_ratio=0.5), caps("m2m-scaler"))
    assert c["write_bytes_s"] == 0 and c["read_bytes_s"] == a["read_bytes_s"] / 2
    with pytest.raises(ValueError):
        evaluate(scaler(ppc_row="guessed"), caps("m2m-scaler"))


def test_dpu_vote_floor_is_separate_from_traffic():
    raw = {
        "model": "dpu",
        "panel_width": 1440,
        "panel_height": 3120,
        "refresh_hz": 30,
        "dsc_slice_count": 2,
        "layers": [{"src": [1440, 3120], "dst": [1440, 3120], "bpp": 32}],
    }
    a = evaluate(raw, caps("dpu"))
    b = evaluate({**raw, "refresh_hz": 60}, caps("dpu"))
    assert a["bts_read_vote_kB_s"] == b["bts_read_vote_kB_s"]
    assert 2 * a["read_bytes_s"] == b["read_bytes_s"]
    assert a["selected_disp_clock_khz"] == 200000
    assert a["power_mw"] is None


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_invalid_units_rejected(value):
    with pytest.raises(ValidationError):
        evaluate({"model": "ufs", "bitrate_mbps": value}, caps("ufs"))
