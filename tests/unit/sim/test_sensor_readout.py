import pytest
from pydantic import ValidationError
from scenario_db.sim.sensor_timing import calculate_sensor_timing, catalog_mode_timing
from scenario_db.sim.external_devices import _calc_v_valid_ms
from scenario_db.sim.clock_corrections import _calc_v_valid_ms as clock_valid


def timing(**changes):
    return {"active_width": 4080, "active_height": 3060, "pixel_clock_hz": 3532800000,
        "line_length_pck": 8880, "frame_length_lines": 3312,
        "source": {"basis": "CIS setfile"}, **changes}


def test_gng_readout_and_blanking():
    r = calculate_sensor_timing(timing())
    assert r["valid_time_ms"] == pytest.approx(7.6915760869565215)
    assert r["csis_frame_window_ms"] == r["valid_time_ms"]
    assert r["frame_period_ms"] > r["valid_time_ms"]
    assert r["frame_period_ms"] == pytest.approx(r["valid_time_ms"] + r["vertical_blank_ms"])


def test_frame_length_changes_period_not_readout():
    a = calculate_sensor_timing(timing())
    b = calculate_sensor_timing(timing(frame_length_lines=6624))
    assert a["valid_time_ms"] == b["valid_time_ms"]
    assert b["frame_period_ms"] == 2 * a["frame_period_ms"]


@pytest.mark.parametrize("change", [{"pixel_clock_hz": 0}, {"pixel_clock_hz": float("nan")},
    {"line_length_pck": -1}, {"readout_lines": 4000}, {"source": {}}])
def test_invalid_timing_rejected(change):
    with pytest.raises(ValidationError): calculate_sensor_timing(timing(**change))


def test_no_fps_fallback_for_valid_time():
    assert catalog_mode_timing({"decoded": {"fps": 30}})["valid_time_ms"] is None
    assert _calc_v_valid_ms({"sensor_fps": 30}) is None
    assert clock_valid({"sensor_fps": 30}) is None
