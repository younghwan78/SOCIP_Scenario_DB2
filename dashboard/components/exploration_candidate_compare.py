from __future__ import annotations

import json
from typing import Any

import streamlit as st

from dashboard.components.evidence_actions import rounded_number
from dashboard.components.table_actions import render_copyable_dataframe


COMPARISON_PRIORITY = [
    "case_id",
    "variant_id",
    "feasible",
    "tradeoff_status",
    "condition_label",
    "pareto_candidate",
    "baseline",
    "warning_count",
    "total_power_mw",
    "delta_total_power_mw",
    "core_power_mw",
    "delta_core_power_mw",
    "bw_power_mw",
    "delta_bw_power_mw",
    "total_bw_mbs",
    "delta_total_bw_mbs",
    "hw_time_max_ms",
    "delta_hw_time_max_ms",
    "timeline_end_ms",
    "delta_timeline_end_ms",
    "infeasible_reason",
]

DELTA_SOURCES = {
    "delta_total_power_mw": "total_power_mw",
    "delta_core_power_mw": "core_power_mw",
    "delta_bw_power_mw": "bw_power_mw",
    "delta_total_bw_mbs": "total_bw_mbs",
    "delta_hw_time_max_ms": "hw_time_max_ms",
    "delta_timeline_end_ms": "timeline_end_ms",
}

PARETO_METRICS = ["total_power_mw", "total_bw_mbs", "hw_time_max_ms", "timeline_end_ms", "warning_count"]

METRIC_SPECS = [
    ("Power", "total_power_mw", "mW"),
    ("DMA BW", "total_bw_mbs", "MB/s"),
    ("HW Time", "hw_time_max_ms", "ms"),
]

METRIC_TABLE_COLORS = {
    "Power": "#FFF7ED",
    "DMA BW": "#EFF6FF",
    "HW Time": "#F3F7EC",
}


def comparison_rows(
    preview: dict[str, Any],
    *,
    baseline_case_id: str | None = None,
    feasible_only: bool = False,
    pareto_only: bool = False,
    hide_warning_cases: bool = False,
) -> list[dict[str, Any]]:
    raw_rows = comparison_raw_rows(preview, baseline_case_id=baseline_case_id)
    if feasible_only:
        raw_rows = [row for row in raw_rows if row.get("feasible", True)]
    if hide_warning_cases:
        raw_rows = [row for row in raw_rows if not _numeric(row.get("warning_count"))]
    if pareto_only:
        raw_rows = [row for row in raw_rows if row.get("pareto_candidate")]
    rows: list[dict[str, Any]] = []
    for item in raw_rows:
        row = {key: _format_value(item.get(key)) for key in COMPARISON_PRIORITY if key in item}
        for key, value in item.items():
            if key not in row:
                row[key] = _format_value(value)
        rows.append(row)
    return rows


def comparison_raw_rows(preview: dict[str, Any], *, baseline_case_id: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in preview.get("comparison") or []:
        if isinstance(item, dict):
            rows.append(dict(item))
    if not rows:
        rows = [_comparison_from_case(case) for case in preview.get("cases") or [] if isinstance(case, dict)]
    if not rows:
        return []
    ids = {str(row.get("case_id")) for row in rows}
    baseline_case_id = baseline_case_id if baseline_case_id in ids else str(rows[0].get("case_id"))
    baseline = next((row for row in rows if str(row.get("case_id")) == baseline_case_id), rows[0])
    pareto_ids = pareto_case_ids(rows)
    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized_row = dict(row)
        case_id = str(normalized_row.get("case_id") or "")
        normalized_row["baseline"] = case_id == baseline_case_id
        normalized_row["pareto_candidate"] = case_id in pareto_ids
        normalized_row["tradeoff_status"] = _tradeoff_status(normalized_row)
        normalized_row["condition_label"] = _condition_label(normalized_row)
        for delta_key, source_key in DELTA_SOURCES.items():
            value = _numeric(normalized_row.get(source_key))
            base_value = _numeric(baseline.get(source_key))
            if value is not None and base_value is not None:
                normalized_row[delta_key] = value - base_value
        normalized.append(normalized_row)
    return normalized


def pareto_case_ids(rows: list[dict[str, Any]]) -> set[str]:
    candidates = [row for row in rows if row.get("case_id") and row.get("feasible", True)]
    pareto: set[str] = set()
    for row in candidates:
        if not _is_dominated(row, candidates):
            pareto.add(str(row["case_id"]))
    return pareto


def tradeoff_plot_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plot_rows: list[dict[str, Any]] = []
    for row in rows:
        power = _numeric(row.get("total_power_mw"))
        bw = _numeric(row.get("total_bw_mbs"))
        if power is None or bw is None:
            continue
        plot_rows.append(
            {
                **row,
                "total_power_mw": power,
                "total_bw_mbs": bw,
                "tradeoff_status": row.get("tradeoff_status") or _tradeoff_status(row),
                "condition_label": row.get("condition_label") or _condition_label(row),
                "compression_label": _compression_label(row),
                "point_label": _point_label(row),
            }
        )
    return plot_rows


def candidate_ids(preview: dict[str, Any]) -> list[str]:
    ids = []
    for case in preview.get("cases") or []:
        if isinstance(case, dict) and case.get("case_id"):
            ids.append(str(case["case_id"]))
    return ids


def preview_warning_summary(preview: dict[str, Any], *, limit: int = 12) -> list[str]:
    return _unique_preview_warnings(preview)[: max(0, int(limit))]


def preview_warning_count(preview: dict[str, Any]) -> int:
    return len(_unique_preview_warnings(preview))


def selected_candidate(preview: dict[str, Any], case_id: str | None) -> dict[str, Any] | None:
    cases = [case for case in preview.get("cases") or [] if isinstance(case, dict)]
    if not cases:
        return None
    if case_id:
        for case in cases:
            if str(case.get("case_id")) == case_id:
                return case
    return cases[0]


def render_candidate_comparison(preview: dict[str, Any], *, key_prefix: str) -> str | None:
    ids = candidate_ids(preview)
    if not ids:
        st.info("No preview candidates are available. Run Simulation after compiling exploration YAML.")
        return None

    control_cols = st.columns([1.1, 0.9, 0.9, 1.1])
    baseline_key = f"{key_prefix}_baseline_case"
    if st.session_state.get(baseline_key) not in ids:
        st.session_state[baseline_key] = ids[0]
    baseline_id = control_cols[0].selectbox("Baseline candidate", ids, key=baseline_key)
    feasible_only = control_cols[1].checkbox("Feasible only", value=False, key=f"{key_prefix}_feasible_only")
    pareto_only = control_cols[2].checkbox("Pareto only", value=False, key=f"{key_prefix}_pareto_only")
    hide_warnings = control_cols[3].checkbox("Hide warnings", value=False, key=f"{key_prefix}_hide_warnings")

    raw_rows = comparison_raw_rows(preview, baseline_case_id=baseline_id)
    _render_candidate_summary(raw_rows)
    _render_metric_distribution(raw_rows, key_prefix=key_prefix)

    rows = comparison_rows(
        preview,
        baseline_case_id=baseline_id,
        feasible_only=feasible_only,
        pareto_only=pareto_only,
        hide_warning_cases=hide_warnings,
    )
    if not rows:
        st.info("No candidates match the current comparison filters.")
        return None

    render_copyable_dataframe(rows, key=f"{key_prefix}_candidate_comparison", use_container_width=True, hide_index=True)
    selectable_ids = [str(row.get("case_id")) for row in rows if row.get("case_id")] or ids
    selected_key = f"{key_prefix}_selected_case"
    if st.session_state.get(selected_key) not in selectable_ids:
        st.session_state[selected_key] = selectable_ids[0]
    return st.selectbox("Selected candidate", selectable_ids, key=selected_key)


def _comparison_from_case(case: dict[str, Any]) -> dict[str, Any]:
    kpi = case.get("kpi") if isinstance(case.get("kpi"), dict) else {}
    return {
        "case_id": case.get("case_id"),
        "variant_id": case.get("variant_id"),
        "feasible": case.get("feasible", True),
        "warning_count": len(case.get("warnings") or []),
        "total_power_mw": kpi.get("total_power_mw"),
        "core_power_mw": kpi.get("core_power_mw"),
        "bw_power_mw": kpi.get("bw_power_mw"),
        "total_bw_mbs": kpi.get("total_bw_mbs"),
        "hw_time_max_ms": kpi.get("hw_time_max_ms"),
        "timeline_end_ms": kpi.get("timeline_end_ms"),
        "infeasible_reason": case.get("infeasible_reason"),
        **(case.get("axis_values") if isinstance(case.get("axis_values"), dict) else {}),
    }


def _unique_preview_warnings(preview: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    seen: set[str] = set()
    for value in preview.get("warnings") or []:
        _append_warning(warnings, seen, value)
    for case in preview.get("cases") or []:
        if not isinstance(case, dict):
            continue
        for value in case.get("warnings") or []:
            _append_warning(warnings, seen, value)
    return warnings


def _append_warning(warnings: list[str], seen: set[str], value: Any) -> None:
    text = str(value).strip() if value is not None else ""
    if not text or text in seen:
        return
    seen.add(text)
    warnings.append(text)


def _render_candidate_summary(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    pareto_count = sum(1 for row in rows if row.get("pareto_candidate"))
    feasible_count = sum(1 for row in rows if row.get("feasible", True))
    best_power = _best_row(rows, "total_power_mw")
    best_bw = _best_row(rows, "total_bw_mbs")
    cols = st.columns(4)
    cols[0].metric("Candidates", len(rows))
    cols[1].metric("Feasible", feasible_count)
    cols[2].metric("Pareto", pareto_count)
    cols[3].metric(
        "Best power / BW",
        f"{_short_case(best_power)} / {_short_case(best_bw)}",
        help="Lowest total_power_mw and lowest total_bw_mbs among feasible candidates.",
    )
    recs = _recommendation_rows(rows)
    if recs:
        st.caption("Candidate quick picks")
        render_copyable_dataframe(recs, key="explore_candidate_quick_picks", use_container_width=True, hide_index=True)


def _render_metric_distribution(rows: list[dict[str, Any]], *, key_prefix: str) -> None:
    if len(rows) < 2:
        return
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except Exception:
        return
    st.markdown("**KPI Distribution by Sweep**")
    st.caption("Box plots show variation across all candidates. Markers identify default, lowest, and highest combinations for each KPI.")
    fig = make_subplots(
        rows=len(METRIC_SPECS),
        cols=1,
        shared_xaxes=False,
        vertical_spacing=0.16,
        subplot_titles=[label for label, _, _ in METRIC_SPECS],
    )
    for index, (label, metric, unit) in enumerate(METRIC_SPECS, start=1):
        values = _metric_values(rows, metric)
        if not values:
            continue
        default_row = next((row for row in rows if row.get("baseline") and _numeric(row.get(metric)) is not None), rows[0])
        low_row = _best_row(rows, metric)
        high_row = _worst_row(rows, metric)
        fig.add_trace(
            go.Box(
                x=values,
                y=[label] * len(values),
                orientation="h",
                boxpoints="all",
                jitter=0.22,
                pointpos=0,
                marker={"color": "#9BA8B8", "size": 7, "opacity": 0.55},
                line={"color": "#2F7D6D", "width": 2},
                fillcolor="rgba(47, 125, 109, 0.18)",
                customdata=[[row.get("case_id"), row.get("condition_label") or _condition_label(row)] for row in rows if _numeric(row.get(metric)) is not None],
                hovertemplate=(
                    "case=%{customdata[0]}<br>"
                    "condition=%{customdata[1]}<br>"
                    f"{label}=%{{x:.3f}} {unit}<extra></extra>"
                ),
                showlegend=False,
            ),
            row=index,
            col=1,
        )
        marker_rows = [
            ("default", default_row, "#334155", "diamond"),
            ("lowest", low_row, "#2F7D6D", "triangle-left"),
            ("highest", high_row, "#C17A2F", "triangle-right"),
        ]
        for marker_name, marker_row, color, symbol in marker_rows:
            marker_value = _numeric(marker_row.get(metric)) if marker_row else None
            if marker_value is None:
                continue
            fig.add_trace(
                go.Scatter(
                    x=[marker_value],
                    y=[label],
                    mode="markers+text",
                    marker={"size": 14, "color": color, "symbol": symbol, "line": {"color": "#FFFFFF", "width": 1}},
                    text=[marker_name],
                    textposition="top center",
                    customdata=[[marker_row.get("case_id"), marker_row.get("condition_label") or _condition_label(marker_row)]],
                    hovertemplate=(
                        f"{marker_name}<br>"
                        "case=%{customdata[0]}<br>"
                        "condition=%{customdata[1]}<br>"
                        f"{label}=%{{x:.3f}} {unit}<extra></extra>"
                    ),
                    showlegend=False,
                ),
                row=index,
                col=1,
            )
        _pad_metric_axis(fig, values, row=index, col=1, title=f"{label} ({unit})")
        fig.update_yaxes(showticklabels=False, row=index, col=1)
    fig.update_layout(
        height=max(620, 210 * len(METRIC_SPECS)),
        margin={"l": 64, "r": 32, "t": 56, "b": 52},
        plot_bgcolor="#FBFAF7",
        paper_bgcolor="#FBFAF7",
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_metric_distribution_box")
    summary = metric_distribution_rows(rows)
    if summary:
        st.caption("Min/default/max summary. Delta columns are relative to the selected default candidate.")
        render_copyable_dataframe(
            metric_distribution_table(summary),
            copy_data=summary,
            key=f"{key_prefix}_metric_distribution_summary",
            use_container_width=True,
            hide_index=True,
        )


def metric_distribution_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for label, metric, unit in METRIC_SPECS:
        metric_rows = [row for row in rows if _numeric(row.get(metric)) is not None]
        if not metric_rows:
            continue
        default = next((row for row in metric_rows if row.get("baseline")), metric_rows[0])
        low = min(metric_rows, key=lambda row: _numeric(row.get(metric)) or 0.0)
        high = max(metric_rows, key=lambda row: _numeric(row.get(metric)) or 0.0)
        default_value = _numeric(default.get(metric)) or 0.0
        low_value = _numeric(low.get(metric)) or 0.0
        high_value = _numeric(high.get(metric)) or 0.0
        spread = high_value - low_value
        for point, row, value in (
            ("min", low, low_value),
            ("default", default, default_value),
            ("max", high, high_value),
        ):
            result.append(_metric_summary_row(label, unit, point, row, value, default_value))
        result.append(
            {
                "metric": label,
                "point": "spread",
                "unit": unit,
                "value": rounded_number(spread),
                "delta_vs_default": rounded_number(spread),
                "delta_pct_vs_default": _rounded_ratio(spread, default_value),
                "case_id": f"{low.get('case_id')} .. {high.get('case_id')}",
                "condition": f"{low.get('condition_label') or _condition_label(low)} .. {high.get('condition_label') or _condition_label(high)}",
            }
        )
    return result


def metric_distribution_table(rows: list[dict[str, Any]]) -> Any:
    try:
        import pandas as pd
    except Exception:
        return rows
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.style.apply(metric_distribution_row_style, axis=1)


def metric_distribution_row_style(row: Any) -> list[str]:
    metric = row.get("metric") if hasattr(row, "get") else None
    color = METRIC_TABLE_COLORS.get(str(metric), "#FFFFFF")
    font_weight = "font-weight: 700;" if row.get("point") == "default" else ""
    return [f"background-color: {color}; {font_weight}" for _ in row]


def _metric_summary_row(
    metric: str,
    unit: str,
    point: str,
    row: dict[str, Any],
    value: float,
    default_value: float,
) -> dict[str, Any]:
    return {
        "metric": metric,
        "point": point,
        "unit": unit,
        "value": rounded_number(value),
        "delta_vs_default": rounded_number(value - default_value),
        "delta_pct_vs_default": _rounded_pct(value, default_value),
        "case_id": row.get("case_id"),
        "condition": row.get("condition_label") or _condition_label(row),
    }


def chart_candidate_rows(rows: list[dict[str, Any]], *, sort_key: str, limit: int) -> list[dict[str, Any]]:
    normalized = [{**row, "condition_label": row.get("condition_label") or _condition_label(row)} for row in rows]
    if sort_key == "Power":
        normalized.sort(key=lambda row: (_numeric(row.get("total_power_mw")) is None, _numeric(row.get("total_power_mw")) or 0.0))
    elif sort_key == "DMA BW":
        normalized.sort(key=lambda row: (_numeric(row.get("total_bw_mbs")) is None, _numeric(row.get("total_bw_mbs")) or 0.0))
    elif sort_key == "HW Time":
        normalized.sort(key=lambda row: (_numeric(row.get("hw_time_max_ms")) is None, _numeric(row.get("hw_time_max_ms")) or 0.0))
    elif sort_key == "Pareto first":
        normalized.sort(
            key=lambda row: (
                not bool(row.get("pareto_candidate")),
                not bool(row.get("feasible", True)),
                _numeric(row.get("total_power_mw")) or 0.0,
            )
        )
    return normalized[: max(1, limit)]


def metric_bar_rows(rows: list[dict[str, Any]], *, metric: str, unit: str) -> list[dict[str, Any]]:
    baseline = next((row for row in rows if row.get("baseline")), rows[0] if rows else None)
    if not baseline:
        return []
    baseline_value = _numeric(baseline.get(metric))
    result: list[dict[str, Any]] = []
    for row in rows:
        value = _numeric(row.get(metric))
        if value is None:
            continue
        delta = value - baseline_value if baseline_value is not None else 0.0
        delta_pct = (delta / baseline_value * 100.0) if baseline_value not in (None, 0.0) else None
        result.append(
            {
                "case_id": row.get("case_id"),
                "condition": row.get("condition_label") or _condition_label(row),
                "status": row.get("tradeoff_status") or _tradeoff_status(row),
                "value": value,
                "delta": delta,
                "delta_pct": delta_pct,
                "delta_pct_label": _delta_pct_label(delta_pct),
                "label": _bar_value_label(value, delta, delta_pct, unit, baseline=bool(row.get("baseline"))),
                "short_label": _bar_short_label(value, delta, delta_pct, unit, baseline=bool(row.get("baseline"))),
                "color": _bar_color(row, delta),
            }
        )
    return result


def _bar_value_label(value: float, delta: float, delta_pct: float | None, unit: str, *, baseline: bool) -> str:
    value_text = f"{rounded_number(value)} {unit}"
    if baseline:
        return f"{value_text} | baseline"
    pct = _delta_pct_label(delta_pct)
    sign = "+" if delta > 0 else ""
    return f"{value_text} | {sign}{rounded_number(delta)} ({pct})"


def _bar_short_label(value: float, delta: float, delta_pct: float | None, unit: str, *, baseline: bool) -> str:
    value_text = f"{rounded_number(value)} {unit}"
    if baseline:
        return f"{value_text}\nbaseline"
    pct = _delta_pct_label(delta_pct)
    sign = "+" if delta > 0 else ""
    return f"{value_text}\n{sign}{rounded_number(delta)} / {pct}"


def _delta_pct_label(delta_pct: float | None) -> str:
    if delta_pct is None:
        return "n/a"
    sign = "+" if delta_pct > 0 else ""
    return f"{sign}{rounded_number(delta_pct)}%"


def _bar_color(row: dict[str, Any], delta: float) -> str:
    if row.get("baseline"):
        return "#2F7D6D"
    if not row.get("feasible", True):
        return "#DC2626"
    if delta > 0:
        return "#C17A2F"
    if delta < 0:
        return "#2F7D6D"
    return "#94A3B8"


def _recommendation_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_power = _best_row(rows, "total_power_mw")
    best_bw = _best_row(rows, "total_bw_mbs")
    best_timing = _best_row(rows, "hw_time_max_ms") or _best_row(rows, "timeline_end_ms")
    picks = [
        ("lowest_power", best_power, "Lowest total_power_mw among feasible candidates."),
        ("lowest_bw", best_bw, "Lowest total_bw_mbs among feasible candidates."),
        ("fastest_hw", best_timing, "Lowest hw_time_max_ms or timeline_end_ms among feasible candidates."),
    ]
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for label, row, reason in picks:
        if not row:
            continue
        key = (label, str(row.get("case_id")))
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "pick": label,
                "case_id": row.get("case_id"),
                "condition": row.get("condition_label") or _condition_label(row),
                "power_mw": _format_value(row.get("total_power_mw")),
                "bw_mbs": _format_value(row.get("total_bw_mbs")),
                "hw_time_ms": _format_value(row.get("hw_time_max_ms")),
                "reason": reason,
            }
        )
    return result


def _best_row(rows: list[dict[str, Any]], metric: str) -> dict[str, Any] | None:
    candidates = [row for row in rows if row.get("feasible", True) and _numeric(row.get(metric)) is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda row: _numeric(row.get(metric)) or 0.0)


def _worst_row(rows: list[dict[str, Any]], metric: str) -> dict[str, Any] | None:
    candidates = [row for row in rows if _numeric(row.get(metric)) is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda row: _numeric(row.get(metric)) or 0.0)


def _metric_values(rows: list[dict[str, Any]], metric: str) -> list[float]:
    return [value for row in rows if (value := _numeric(row.get(metric))) is not None]


def _pad_metric_axis(fig: Any, values: list[float], *, row: int, col: int, title: str) -> None:
    minimum = min(values)
    maximum = max(values)
    span = maximum - minimum
    pad = span * 0.22 if span > 0 else max(abs(maximum) * 0.08, 1.0)
    fig.update_xaxes(title_text=title, range=[minimum - pad, maximum + pad], row=row, col=col)


def _rounded_pct(value: float, baseline: float) -> float | None:
    if baseline == 0:
        return None
    return rounded_number((value - baseline) / baseline * 100.0)


def _rounded_ratio(value: float, baseline: float) -> float | None:
    if baseline == 0:
        return None
    return rounded_number(value / baseline * 100.0)


def _short_case(row: dict[str, Any] | None) -> str:
    if not row:
        return "-"
    return str(row.get("case_id") or row.get("variant_id") or "-")


def _tradeoff_status(row: dict[str, Any]) -> str:
    if not row.get("feasible", True):
        return "Infeasible"
    if row.get("pareto_candidate"):
        return "Pareto candidate"
    return "Non-Pareto"


def _condition_label(row: dict[str, Any]) -> str:
    width = _first_present(row, ["scale_width", "output_width", "width"])
    height = _first_present(row, ["scale_height", "output_height", "height"])
    resolution = f"{width}x{height}" if width and height else None
    compression = _compression_label(row)
    compression = None if compression == "compression n/a" else compression
    fps = _first_present(row, ["fps", "source_fps"])
    bitwidth = _bitwidth_label(row)
    if fps and bitwidth and not resolution and not compression:
        return f"{_format_axis_number(fps)} ({bitwidth})"
    parts = [part for part in (f"{_format_axis_number(fps)}fps" if fps else None, bitwidth, resolution, compression) if part]
    return " / ".join(parts) if parts else str(row.get("case_id") or row.get("variant_id") or "candidate")


def _compression_label(row: dict[str, Any]) -> str:
    value = _first_present(row, ["compression", "output_compression", "source_compression"])
    return str(value) if value not in (None, "") else "compression n/a"


def _bitwidth_label(row: dict[str, Any]) -> str | None:
    value = _first_present(row, ["bitwidth", "source_bitwidth"])
    if value not in (None, ""):
        return f"{_format_axis_number(value)}b"
    for key in ("source_format", "format", "output_format"):
        text = str(row.get(key) or "")
        if "_" in text:
            tail = text.rsplit("_", 1)[-1]
            if tail.isdigit():
                return f"{tail}b"
    return None


def _format_axis_number(value: Any) -> str:
    number = _numeric(value)
    if number is None:
        return str(value)
    return str(int(number)) if number.is_integer() else str(rounded_number(number))


def _point_label(row: dict[str, Any]) -> str:
    width = _first_present(row, ["scale_width", "output_width", "width"])
    height = _first_present(row, ["scale_height", "output_height", "height"])
    if width and height:
        return f"{width}x{height}"
    return str(row.get("case_id") or "")


def _first_present(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _is_dominated(row: dict[str, Any], candidates: list[dict[str, Any]]) -> bool:
    row_values = [_numeric(row.get(metric)) for metric in PARETO_METRICS]
    if all(value is None for value in row_values):
        return False
    for other in candidates:
        if other is row:
            continue
        other_values = [_numeric(other.get(metric)) for metric in PARETO_METRICS]
        no_worse = True
        strictly_better = False
        for row_value, other_value in zip(row_values, other_values):
            if row_value is None or other_value is None:
                continue
            if other_value > row_value:
                no_worse = False
                break
            if other_value < row_value:
                strictly_better = True
        if no_worse and strictly_better:
            return True
    return False


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _format_value(value: Any) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return rounded_number(value)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value
