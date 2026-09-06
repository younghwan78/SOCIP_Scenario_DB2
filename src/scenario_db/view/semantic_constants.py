"""Semantic view projection constants."""
from __future__ import annotations


_LEVEL1_HIERARCHY_ORDER = {
    "Sensor": 0,
    "ISP": 1,
    "Compute": 2,
    "NPU": 3,
    "GPU": 4,
    "CODEC": 5,
    "DPU": 6,
    "Display": 7,
    "CPU/SW": 8,
    "Memory": 9,
    "Other": 99,
}

_LEVEL1_IP_GROUP_ORDER = {
    "Sensor": 0,
    "CSIS": 9,
    "CSIS/PDP": 10,
    "3AA/CSTAT": 20,
    "BYRP": 30,
    "RGBP": 40,
    "YUVSC": 50,
    "MTNR": 60,
    "MSNR": 70,
    "YUVP": 80,
    "MCSC": 90,
    "GDC": 100,
    "LME": 110,
    "ISP Core": 115,
    "SGPU": 120,
    "NPU": 130,
    "GPU": 140,
    "MFC": 150,
    "APV": 160,
    "DPU": 170,
    "Panel": 180,
    "CPU/SW": 190,
}

_LEVEL2_ALIAS_GROUPS = {
    "camera": "camera",
    "cam": "camera",
    "isp": "camera",
    "camera_pipeline": "camera",
    "camera-pipeline": "camera",
    "video": "video",
    "codec": "video",
    "mfc": "video",
    "encode": "video",
    "display": "display",
    "dpu": "display",
    # Full-SoC module detail, matching the legacy Level 3 view.
    "all": "all",
    "full": "all",
}

_LEVEL2_REFERENCE_ALIASES = {
    "camera",
    "cam",
    "csis",
    "isp",
    "camera-pipeline",
    "camera_pipeline",
    "video",
    "codec",
    "mfc",
    "encode",
    "encoder",
    "display",
    "dpu",
    "decon",
}

_LEVEL2_BLOCK_BY_IP_GROUP = {
    "CSIS": "CSIS",
    "CSIS/PDP": "CSISPDP",
    "3AA/CSTAT": "3AA",
    "BYRP": "BYRP",
    "RGBP": "RGBP",
    "YUVSC": "YUVSC",
    "MTNR": "MTNR",
    "MSNR": "MSNR",
    "YUVP": "YUVP",
    "MCSC": "MCSC",
    "GDC": "GDC",
    "LME": "LME",
    "MFC": "MFC",
    "APV": "APV",
    "DPU": "DPU",
    "SGPU": "SGPU",
    "GPU": "GPU",
    "NPU": "NPU",
}

_LEVEL2_REQUIRED_DATA = [
    "capabilities.properties.modules for DMA/CIN/COUT module nodes",
    "capabilities.properties.subblocks or hierarchy.submodules for functional blocks",
    "capabilities.properties.internal_edges and scenario pipeline edges for module routing",
    "pipeline.buffers or variant.buffer_overrides for buffer format, compression, and LLC placement",
]
