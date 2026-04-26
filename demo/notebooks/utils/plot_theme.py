"""사내 색상 팔레트 + 공통 matplotlib/seaborn/plotly 스타일."""
from __future__ import annotations

import matplotlib.pyplot as plt
import matplotlib as mpl
import seaborn as sns

# ---------------------------------------------------------------------------
# 색상 팔레트
# ---------------------------------------------------------------------------

# Feasibility 상태별 — 신호등 계열
FEASIBILITY_COLORS = {
    "production_ready":  "#2ECC71",   # 초록
    "exploration_only":  "#F39C12",   # 주황
    "infeasible":        "#E74C3C",   # 빨강
    "unknown":           "#95A5A6",   # 회색
}

# Gate Result
GATE_COLORS = {
    "PASS":  "#27AE60",
    "WARN":  "#E67E22",
    "BLOCK": "#C0392B",
}

# SW Baseline 계열 — 버전 비교용
SW_VERSION_PALETTE = [
    "#3498DB",  # blue   — v1.x
    "#9B59B6",  # purple — v2.x
    "#1ABC9C",  # teal   — v3.x
    "#E74C3C",  # red    — legacy
]

# IP 카테고리별
IP_CATEGORY_COLORS = {
    "camera":  "#3498DB",
    "codec":   "#E67E22",
    "display": "#9B59B6",
    "memory":  "#1ABC9C",
    "other":   "#95A5A6",
}

# 배경색 / 강조색
BG_LIGHT   = "#F8F9FA"
ACCENT     = "#2C3E50"
GRID_COLOR = "#DEE2E6"

# ---------------------------------------------------------------------------
# 기본 팔레트 (seaborn 기본값으로 등록)
# ---------------------------------------------------------------------------
PALETTE_NAME = "scenariodb"
sns.set_palette(list(FEASIBILITY_COLORS.values()))


# ---------------------------------------------------------------------------
# 공통 테마 적용 함수
# ---------------------------------------------------------------------------

def apply_theme(context: str = "notebook", font_scale: float = 1.1) -> None:
    """notebook 전체에 한 번 호출하면 모든 plot에 반영."""
    sns.set_theme(
        context=context,
        style="whitegrid",
        font_scale=font_scale,
        rc={
            "axes.facecolor":    BG_LIGHT,
            "figure.facecolor":  "white",
            "grid.color":        GRID_COLOR,
            "axes.spines.top":   False,
            "axes.spines.right": False,
            "axes.labelcolor":   ACCENT,
            "xtick.color":       ACCENT,
            "ytick.color":       ACCENT,
            "font.family":       "sans-serif",
        },
    )


def fig_ax(w: float = 10, h: float = 5, **kwargs):
    """표준 figure / axes 생성 shortcut."""
    return plt.subplots(figsize=(w, h), **kwargs)


# ---------------------------------------------------------------------------
# Plotly 공통 레이아웃
# ---------------------------------------------------------------------------

def plotly_layout(title: str = "", **overrides) -> dict:
    """plotly go.Figure.update_layout(**plotly_layout(...)) 용."""
    base = dict(
        title=dict(text=title, font=dict(size=16, color=ACCENT)),
        paper_bgcolor="white",
        plot_bgcolor=BG_LIGHT,
        font=dict(family="sans-serif", color=ACCENT),
        margin=dict(l=60, r=40, t=60, b=60),
        xaxis=dict(gridcolor=GRID_COLOR, showgrid=True),
        yaxis=dict(gridcolor=GRID_COLOR, showgrid=True),
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 편의 함수
# ---------------------------------------------------------------------------

def feasibility_color(value: str) -> str:
    return FEASIBILITY_COLORS.get(value, FEASIBILITY_COLORS["unknown"])


def gate_color(value: str) -> str:
    return GATE_COLORS.get(value, "#95A5A6")
