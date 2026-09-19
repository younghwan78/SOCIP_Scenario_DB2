"""VVALID is readout time, never silently replaced with the frame period."""
from __future__ import annotations
from typing import Any
from scenario_db.models.sensor import SensorTiming


def calculate_sensor_timing(raw: dict[str, Any]) -> dict[str, Any]:
    t = SensorTiming.model_validate(raw)
    line_ms = t.line_length_pck * 1000 / t.pixel_clock_hz
    readout_lines = t.readout_lines or t.active_height
    valid_ms = line_ms * readout_lines
    period_ms = line_ms * t.frame_length_lines
    return {
        "status": "calculated", "value_source": "calculated",
        "valid_time_ms": valid_ms,
        "csis_frame_window_ms": valid_ms,
        "frame_period_ms": period_ms,
        "vertical_blank_ms": period_ms - valid_ms,
        "line_time_us": line_ms * 1000,
        "readout_lines": readout_lines,
        "effective_fps": 1000 / period_ms,
        "formula": "line_length_pck / pixel_clock_hz * readout_lines * 1000",
        "source": t.source,
        "note": "CSIS frame window prediction from sensor readout; not a measured FS/FE interval. Multi-exposure modes require explicit readout_lines for the selected sequence.",
    }


def catalog_mode_timing(mode: dict[str, Any]) -> dict[str, Any]:
    if mode.get("timing"):
        return calculate_sensor_timing(mode["timing"])
    fps = (mode.get("decoded") or {}).get("fps")
    return {
        "status": "missing_timing", "valid_time_ms": None,
        "csis_frame_window_ms": None,
        "nominal_frame_period_ms": 1000 / fps if fps and fps > 0 else None,
        "required_fields": ["pixel_clock_hz", "line_length_pck", "frame_length_lines", "active_height or readout_lines"],
        "note": "DT FPS and MIPI rate do not determine VVALID. Select an explicitly verified CIS timing mode; no resolution/FPS-only match is applied.",
    }
