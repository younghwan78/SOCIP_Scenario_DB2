"""Visual constants for the Scenario DB pipeline viewer."""
from __future__ import annotations

# Layer node gradient colors
LAYER_GRADIENT: dict[str, dict] = {
    "app":       {"g1": "#a78bfa", "g2": "#c4b5fd", "border": "#9061f9",  "text": "#4C1D95"},
    "framework": {"g1": "#5b7cfa", "g2": "#7ea1ff", "border": "#3B5BDB",  "text": "#1E3A8A"},
    "hal":       {"g1": "#2bb3aa", "g2": "#66d1ca", "border": "#0E9F97",  "text": "#064E3B"},
    "kernel":    {"g1": "#a78bd9", "g2": "#d8c4f0", "border": "#7C3AED",  "text": "#4C1D95"},
    "hw":        {"g1": "#fdba74", "g2": "#fed7aa", "border": "#EA7C00",  "text": "#7C2D12"},
    "memory":    {"g1": "#149f9a", "g2": "#4fd1c5", "border": "#0F766E",  "text": "#064E3B"},
}

# Lane background tints
LANE_BG_RGBA: dict[str, str] = {
    "app":       "rgba(167,139,250,0.07)",
    "framework": "rgba(91,124,250,0.07)",
    "hal":       "rgba(43,179,170,0.07)",
    "kernel":    "rgba(167,139,217,0.07)",
    "hw":        "rgba(253,186,116,0.09)",
    "memory":    "rgba(20,159,154,0.07)",
}

# Edge type colors
EDGE_COLOR: dict[str, str] = {
    "OTF":     "#4A6CF7",   # blue
    "vOTF":    "#2BB3AA",   # teal
    "M2M":     "#F97316",   # orange
    "control": "#9B8EC4",   # gray-purple
    "risk":    "#EF4444",   # red
}

# Severity badge colors
SEVERITY_COLOR: dict[str, str] = {
    "Critical": "#DC2626",
    "High":     "#D97706",
    "Medium":   "#CA8A04",
    "Low":      "#2563EB",
}

SEVERITY_BG: dict[str, str] = {
    "Critical": "#FEE2E2",
    "High":     "#FEF3C7",
    "Medium":   "#FEF9C3",
    "Low":      "#DBEAFE",
}

# Canvas / page background
PAGE_BG = "#FAF9F7"
CANVAS_BG = "#FAFAF8"
LANE_BORDER = "#E8E4DF"
STAGE_DIVIDER = "#EDE9E4"
HEADER_BG = "#FFFFFF"
