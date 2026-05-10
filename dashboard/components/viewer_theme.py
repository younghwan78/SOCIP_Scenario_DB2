"""Visual constants for the Scenario DB pipeline viewer."""
from __future__ import annotations

# Layer node gradient colors
LAYER_GRADIENT: dict[str, dict] = {
    "app":       {"g1": "#a78bfa", "g2": "#c4b5fd", "border": "#9061f9",  "text": "#4C1D95"},
    "framework": {"g1": "#5C738A", "g2": "#8AA1B2", "border": "#486376",  "text": "#203645"},
    "hal":       {"g1": "#3D8A82", "g2": "#7AB7AE", "border": "#2F6F68",  "text": "#174D47"},
    "kernel":    {"g1": "#a78bd9", "g2": "#d8c4f0", "border": "#7C3AED",  "text": "#4C1D95"},
    "hw":        {"g1": "#fdba74", "g2": "#fed7aa", "border": "#EA7C00",  "text": "#7C2D12"},
    "memory":    {"g1": "#2F6F68", "g2": "#75B2A8", "border": "#255E58",  "text": "#174D47"},
}

# Lane background tints
LANE_BG_RGBA: dict[str, str] = {
    "app":       "rgba(167,139,250,0.07)",
    "framework": "rgba(92,115,138,0.08)",
    "hal":       "rgba(61,138,130,0.08)",
    "kernel":    "rgba(167,139,217,0.07)",
    "hw":        "rgba(253,186,116,0.09)",
    "memory":    "rgba(47,111,104,0.08)",
}

# Edge type colors
EDGE_COLOR: dict[str, str] = {
    "OTF":     "#4E6E81",   # muted steel
    "vOTF":    "#3D8A82",   # muted teal
    "M2M":     "#F97316",   # orange
    "control": "#9B8EC4",   # gray-purple
    "risk":    "#EF4444",   # red
}

# Severity badge colors
SEVERITY_COLOR: dict[str, str] = {
    "Critical": "#DC2626",
    "High":     "#D97706",
    "Medium":   "#CA8A04",
    "Low":      "#2F6F68",
}

SEVERITY_BG: dict[str, str] = {
    "Critical": "#FEE2E2",
    "High":     "#FEF3C7",
    "Medium":   "#FEF9C3",
    "Low":      "#E8F1EF",
}

# Canvas / page background
PAGE_BG = "#F7F4EF"
CANVAS_BG = "#FBFAF7"
LANE_BORDER = "#DED8CF"
STAGE_DIVIDER = "#E8E0D6"
HEADER_BG = "#FFFFFF"
