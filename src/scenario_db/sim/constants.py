"""Shared constants for ScenarioDB simulation calculations."""
from __future__ import annotations

BPP_MAP: dict[str, float] = {
    "NV12": 1.5,
    "NV21": 1.5,
    "YUV420": 1.5,
    "YUV420_10BIT": 1.5,
    "YUV420_SBWC": 1.5,
    "YUV420_SBWCL": 1.5,
    "YUV422": 2.0,
    "NV16": 2.0,
    "YUYV": 2.0,
    "UYVY": 2.0,
    "YUV444": 3.0,
    "Y": 1.0,
    "Y8": 1.0,
    "GREY": 1.0,
    "UV8": 2.0,
    "RGB": 3.0,
    "RGB888": 3.0,
    "BGR": 3.0,
    "ARGB": 4.0,
    "RGBA": 4.0,
    "BGRA": 4.0,
    "ABGR": 4.0,
    "RAW": 1.0,
    "RAW8": 1.0,
    "RAW10": 1.25,
    "RAW12": 1.5,
    "RAW14": 1.75,
    "RAW16": 2.0,
    "BAYER": 1.0,
    "BAYER_PACKED": 1.0,
    "BAYER_UNPACKED": 2.0,
    "P010": 2.0,
    "P210": 3.2,
    "STAT": 1.0,
}

BPP_DEFAULT = 1.0
BW_POWER_COEFF_DEFAULT = 80.0
SW_MARGIN_DEFAULT = 0.15
REFERENCE_VOLTAGE_MV = 710.0
REFERENCE_FPS = 30.0
VBAT_DEFAULT = 4.0
PMIC_EFFICIENCY_DEFAULT = 0.85
H_BLANK_MARGIN_DEFAULT = 0.05
