"""Shared constants for ScenarioDB simulation calculations."""
from __future__ import annotations

# Bytes-per-pixel FACTOR relative to the sample container size: total
# bytes/pixel = factor * (bitwidth / 8). Formats that pack samples into wider
# containers (P010/P210: 10-bit in 16-bit) must be used with the container
# bitwidth (16), not the sample depth — the factor already excludes bit depth.
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
    # 4:2:0 / 4:2:2 chroma layouts in 16-bit containers: plane factor only
    # (1.5 / 2.0); the old 2.0 / 3.2 values double-counted the container
    # width once bitwidth=16 was applied on top.
    "P010": 1.5,
    "P210": 2.0,
    "YUV422_10BIT": 2.0,
    "STAT": 1.0,
}

BPP_DEFAULT = 1.0

# Packed formats whose name fixes the pixel size (bytes / pixel), whatever the declared bitwidth / bitdepth:
# RGBA1010102 is 4 bytes, not 4 x 10 / 8.
PACKED_BYTES_PER_PIXEL: dict[str, float] = {
    "RGBA8888": 4.0,
    "BGRA8888": 4.0,
    "ARGB8888": 4.0,
    "ABGR8888": 4.0,
    "RGBX8888": 4.0,
    "RGBA1010102": 4.0,
    "BGRA1010102": 4.0,
    "ARGB2101010": 4.0,
    "RGB565": 2.0,
    "RGBA16F": 8.0,
    "RGBA_FP16": 8.0,
}


def format_bpp_factor(fmt: str | None, bitwidth: float | None = 8) -> tuple[float, str]:
    """The ``format_bpp_factor`` of the BW formula (bytes / pixel = factor x bitwidth / 8) and how it was found.

    Order: a packed format (factor = its bytes over bitwidth / 8, so the product is the packed size), the exact
    ``BPP_MAP`` name, the longest ``BPP_MAP`` prefix (``RAW_BAYER_16`` -> ``RAW``), else ``BPP_DEFAULT``
    (basis ``default``: callers warn). Steady BW, the debug trace and event jobs share this lookup.
    """
    name = str(fmt or "").upper()
    width = float(bitwidth or 8)
    if name in PACKED_BYTES_PER_PIXEL:
        return PACKED_BYTES_PER_PIXEL[name] / (width / 8.0), "packed"
    if name in BPP_MAP:
        return BPP_MAP[name], "exact"
    keys = [k for k in BPP_MAP if name.startswith(k)]
    if keys:
        key = max(keys, key=len)
        return BPP_MAP[key], f"prefix:{key}"
    return BPP_DEFAULT, "default"

BW_POWER_COEFF_DEFAULT = 80.0
SW_MARGIN_DEFAULT = 0.15
REFERENCE_VOLTAGE_MV = 710.0
REFERENCE_FPS = 30.0
VBAT_DEFAULT = 4.0
PMIC_EFFICIENCY_DEFAULT = 0.85
H_BLANK_MARGIN_DEFAULT = 0.05
