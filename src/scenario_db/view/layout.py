"""Level 0 layout constants — explicit and easy to tune."""
from __future__ import annotations

# Canvas dimensions (Cytoscape coordinate space)
CANVAS_W = 1100
CANVAS_H = 680

# Stage header height at top of canvas
STAGE_HEADER_H = 30

# Lane label width at left of canvas
LANE_LABEL_W = 80

# Height of each lane band
LANE_H = 95

# Gap between lane bands
LANE_GAP = 8

# Bottom legend area
LEGEND_H = 45


def _lane_center_y(index: int) -> float:
    """Return the Y center of the i-th lane (0=App)."""
    top = STAGE_HEADER_H + index * (LANE_H + LANE_GAP)
    return top + LANE_H / 2


# Lane Y centers (Cytoscape coordinate space)
LANE_Y: dict[str, float] = {
    "app":       _lane_center_y(0),   # ~77
    "framework": _lane_center_y(1),   # ~180
    "hal":       _lane_center_y(2),   # ~283
    "kernel":    _lane_center_y(3),   # ~386
    "hw":        _lane_center_y(4),   # ~489
    "memory":    _lane_center_y(5),   # ~592
}

# Stage column X centers (Cytoscape coordinate space, within content area)
STAGE_X: dict[str, float] = {
    "capture":    195.0,
    "processing": 510.0,
    "encode":     790.0,
    "display":    1020.0,
}

# Stage column x-boundaries
STAGE_BOUNDS: dict[str, tuple[float, float]] = {
    "capture":    (LANE_LABEL_W, 310.0),
    "processing": (310.0, 670.0),
    "encode":     (670.0, 920.0),
    "display":    (920.0, float(CANVAS_W)),
}

# Preset node widths by type
NODE_W: dict[str, int] = {
    "sw":     135,
    "ip":     100,
    "buffer": 155,
    "lane_label": 65,
    "stage_header": 160,
}

NODE_H: dict[str, int] = {
    "sw":     38,
    "ip":     36,
    "buffer": 38,
    "lane_label": 30,
    "stage_header": 25,
}

# Lane background node x-center (centered in content area)
BG_CENTER_X = (LANE_LABEL_W + CANVAS_W) / 2   # ~590
BG_WIDTH = CANVAS_W - LANE_LABEL_W             # ~1020

# Lane colors (background fill gradients)
LANE_COLORS: dict[str, dict] = {
    "app":       {"start": "#a78bfa", "end": "#c4b5fd", "bg": "rgba(167,139,250,0.08)", "border": "#c4b5fd"},
    "framework": {"start": "#5b7cfa", "end": "#7ea1ff", "bg": "rgba(91,124,250,0.08)",  "border": "#7ea1ff"},
    "hal":       {"start": "#2bb3aa", "end": "#66d1ca", "bg": "rgba(43,179,170,0.08)",  "border": "#66d1ca"},
    "kernel":    {"start": "#a78bd9", "end": "#d8c4f0", "bg": "rgba(167,139,217,0.08)", "border": "#d8c4f0"},
    "hw":        {"start": "#fdba74", "end": "#fed7aa", "bg": "rgba(253,186,116,0.10)", "border": "#fed7aa"},
    "memory":    {"start": "#149f9a", "end": "#4fd1c5", "bg": "rgba(20,159,154,0.08)",  "border": "#4fd1c5"},
}

LANE_LABEL_ORDER = ["app", "framework", "hal", "kernel", "hw", "memory"]
LANE_DISPLAY_NAMES = {
    "app": "App", "framework": "Framework", "hal": "HAL",
    "kernel": "Kernel", "hw": "HW", "memory": "Buffer",
}
