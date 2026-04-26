"""Lane/stage layout constants for the dashboard side (mirrors src/view/layout.py)."""
from __future__ import annotations

from scenario_db.view.layout import (  # re-export for dashboard use
    BG_CENTER_X, BG_WIDTH, CANVAS_H, CANVAS_W,
    LANE_COLORS, LANE_DISPLAY_NAMES, LANE_GAP, LANE_H,
    LANE_LABEL_ORDER, LANE_LABEL_W, LANE_Y,
    NODE_H, NODE_W, STAGE_BOUNDS, STAGE_HEADER_H, STAGE_X,
)

__all__ = [
    "BG_CENTER_X", "BG_WIDTH", "CANVAS_H", "CANVAS_W",
    "LANE_COLORS", "LANE_DISPLAY_NAMES", "LANE_GAP", "LANE_H",
    "LANE_LABEL_ORDER", "LANE_LABEL_W", "LANE_Y",
    "NODE_H", "NODE_W", "STAGE_BOUNDS", "STAGE_HEADER_H", "STAGE_X",
]

# Stage display names (used in HTML)
STAGE_NAMES = {
    "capture":    "Capture",
    "processing": "ISP / Processing",
    "encode":     "Encode",
    "display":    "Display / Output",
}

# Lane icon characters (Unicode approximations)
LANE_ICONS = {
    "app":       "⊡",
    "framework": "≡",
    "hal":       "⬡",
    "kernel":    "⊛",
    "hw":        "⚙",
    "memory":    "⊙",
}
