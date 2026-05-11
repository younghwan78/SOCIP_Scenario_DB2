"""Preview-versus-saved comparison helpers for simulation evidence."""
from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.components.table_actions import render_copyable_dataframe


METRIC_DEFS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("Power", ("total_power_mw", "power_mw"), "mW"),
    ("Current", ("total_power_ma", "power_ma"), "mA"),
    ("Bandwidth", ("total_bw_mbs", "bw_mbs"), "MB/s"),
    ("HW Time", ("hw_time_max_ms", "hw_time_ms"), "ms"),
    ("Timeline End", ("timeline_end_ms",), "ms"),
    ("Critical Path", ("critical_path_ms",), "ms"),
    ("Max Resource Wait", ("max_resource_wait_ms",), "ms"),
    ("Max Token Wait", ("max_token_wait_ms",), "ms"),
)


def comparison_rows(preview: dict[str, Any], saved: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a stable KPI comparison table from a preview and saved result."""

    preview_kpi = _kpi(preview)
    saved_kpi = _kpi(saved)
    rows: list[dict[str, Any]] = []
    for metric, keys, unit in METRIC_DEFS:
        preview_value = _first_number(preview_kpi, keys)
        saved_value = _first_number(saved_kpi, keys)
        delta = _delta(preview_value, saved_value)
        rows.append(
            {
                "metric": metric,
                "preview": _display(preview_value),
                "saved": _display(saved_value),
                "delta": _display(delta),
                "delta_pct": _delta_pct(delta, saved_value),
                "unit": unit,
            }
        )
    return rows


def context_rows(preview: dict[str, Any], saved: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare identity and execution context fields that often explain KPI drift."""

    preview_ctx = _context(preview)
    saved_ctx = _context(saved)
    fields: tuple[tuple[str, str], ...] = (
        ("id", "id"),
        ("scenario_ref", "scenario_ref"),
        ("variant_ref", "variant_ref"),
        ("silicon_rev", "silicon_rev"),
        ("sw_baseline_ref", "sw_baseline_ref"),
        ("thermal", "thermal"),
        ("params_hash", "params_hash"),
    )
    rows: list[dict[str, Any]] = []
    for label, key in fields:
        preview_value = preview.get(key, preview_ctx.get(key))
        saved_value = saved.get(key, saved_ctx.get(key))
        rows.append(
            {
                "field": label,
                "preview": _context_display(preview_value),
                "saved": _context_display(saved_value),
                "match": preview_value == saved_value,
            }
        )
    return rows


def render_preview_saved_comparison(
    *,
    preview: dict[str, Any] | None,
    saved: dict[str, Any],
    key_prefix: str,
) -> None:
    """Render comparison UI for the active preview and selected saved evidence."""

    if not isinstance(preview, dict):
        return
    with st.expander("Preview vs Saved Comparison", expanded=False):
        st.caption("Delta is preview minus saved. Use this before replacing a confirmed evidence result.")
        rows = comparison_rows(preview, saved)
        render_copyable_dataframe(
            rows,
            key=f"{key_prefix}_preview_saved_kpi_compare",
            use_container_width=True,
            hide_index=True,
        )
        context = context_rows(preview, saved)
        render_copyable_dataframe(
            context,
            key=f"{key_prefix}_preview_saved_context_compare",
            use_container_width=True,
            hide_index=True,
        )


def _kpi(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("kpi")
    return value if isinstance(value, dict) else {}


def _context(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("execution_context")
    return value if isinstance(value, dict) else {}


def _first_number(kpi: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _number(kpi.get(key))
        if value is not None:
            return value
    return None


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _delta_pct(delta: float | None, baseline: float | None) -> str:
    if delta is None or baseline in (None, 0):
        return "-"
    return f"{(delta / baseline) * 100:.3f}%"


def _display(value: float | None) -> float | str:
    if value is None:
        return "-"
    return round(value, 6)


def _context_display(value: Any) -> Any:
    if value in (None, ""):
        return "-"
    return value
