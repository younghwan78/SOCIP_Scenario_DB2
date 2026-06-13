"""Measurement evidence rendering for the Evidence Dashboard.

Data-shaping helpers are pure (no Streamlit) so they can be unit-tested; the
``render_*`` functions wrap them with Streamlit + Plotly. Measurement evidence
carries statistical KPIs (mean/p95/ci), cpu_breakdown (cluster power + freq
residency), sw_task_timing, vdd_power, and raw artifact pointers.
"""
from __future__ import annotations

from typing import Any

MEASUREMENT_TABS = ("Overview", "Power", "CPU / Freq", "SW Timing", "Provenance")
COMPARISON_METRIC_ORDER = ("total_power_mw", "peak_power_mw", "frame_latency_ms", "fps_effective")


# --- scalar extraction -------------------------------------------------------

def kpi_mean(value: Any) -> float | None:
    if isinstance(value, dict):
        v = value.get("mean")
        return float(v) if isinstance(v, (int, float)) else None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def kpi_p95(value: Any) -> float | None:
    if isinstance(value, dict) and isinstance(value.get("p95"), (int, float)):
        return float(value["p95"])
    return None


def _ci(value: Any) -> list[float] | None:
    if isinstance(value, dict):
        ci = value.get("ci_95")
        if isinstance(ci, list) and len(ci) == 2 and all(isinstance(x, (int, float)) for x in ci):
            return [float(ci[0]), float(ci[1])]
    return None


def _rail_mw(entry: Any, *keys: str) -> float | None:
    if isinstance(entry, (int, float)):
        return float(entry)
    if isinstance(entry, dict):
        for key in keys:
            if isinstance(entry.get(key), (int, float)):
                return float(entry[key])
    return None


# --- row builders (pure) -----------------------------------------------------

def measurement_list_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ev in items:
        kpi = ev.get("kpi") if isinstance(ev.get("kpi"), dict) else {}
        rows.append(
            {
                "id": ev.get("id"),
                "measured_at": ev.get("measured_at"),
                "sw_version": (ev.get("execution_context") or {}).get("sw_baseline_ref")
                if isinstance(ev.get("execution_context"), dict)
                else ev.get("sw_version_hint"),
                "silicon_rev": (ev.get("execution_context") or {}).get("silicon_rev")
                if isinstance(ev.get("execution_context"), dict)
                else None,
                "total_power_mw": kpi_mean(kpi.get("total_power_mw")),
            }
        )
    return rows


def kpi_summary_rows(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    kpi = evidence.get("kpi") if isinstance(evidence.get("kpi"), dict) else {}
    rows: list[dict[str, Any]] = []
    for metric, value in kpi.items():
        rows.append(
            {
                "metric": metric,
                "mean": kpi_mean(value),
                "p95": kpi_p95(value),
                "ci_95": _ci(value),
                "n": value.get("n") if isinstance(value, dict) else None,
            }
        )
    return rows


def prediction_measurement_comparison_rows(
    *,
    prediction: dict[str, Any],
    measurement: dict[str, Any],
) -> list[dict[str, Any]]:
    pred_kpi = prediction.get("kpi") if isinstance(prediction.get("kpi"), dict) else {}
    meas_kpi = measurement.get("kpi") if isinstance(measurement.get("kpi"), dict) else {}
    metrics = _ordered_overlap(pred_kpi, meas_kpi)
    rows: list[dict[str, Any]] = []
    for metric in metrics:
        pred_value = kpi_mean(pred_kpi.get(metric))
        meas_mean = kpi_mean(meas_kpi.get(metric))
        if pred_value is None or meas_mean is None:
            continue
        delta = _rounded_number(pred_value - meas_mean)
        rows.append(
            {
                "metric": metric,
                "prediction": _rounded_number(pred_value),
                "measurement_mean": _rounded_number(meas_mean),
                "measurement_p95": _rounded_number(kpi_p95(meas_kpi.get(metric))),
                "delta_vs_measurement": delta,
                "delta_pct_vs_measurement": _delta_pct_label(delta, meas_mean),
            }
        )
    return rows


def cpu_cluster_rows(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cluster in evidence.get("cpu_breakdown") or []:
        if not isinstance(cluster, dict):
            continue
        power = cluster.get("power_mw")
        rows.append(
            {
                "cluster": cluster.get("cluster"),
                "power_mean_mw": kpi_mean(power),
                "power_p95_mw": kpi_p95(power),
                "avg_freq_mhz": cluster.get("avg_freq_mhz"),
                "util_pct": cluster.get("util_pct"),
            }
        )
    return rows


def _ordered_overlap(pred_kpi: dict[str, Any], meas_kpi: dict[str, Any]) -> list[str]:
    overlap = [key for key in pred_kpi if key in meas_kpi]
    prioritized = [key for key in COMPARISON_METRIC_ORDER if key in overlap]
    return prioritized + [key for key in overlap if key not in prioritized]


def _rounded_number(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return round(float(value), 3)


def _delta_pct_label(delta: float | None, baseline: float | None) -> str | None:
    if delta is None or baseline in (None, 0):
        return None
    return f"{(delta / baseline) * 100:.3f}%"


def freq_residency_rows(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cluster in evidence.get("cpu_breakdown") or []:
        if not isinstance(cluster, dict):
            continue
        name = cluster.get("cluster")
        for bin_ in cluster.get("freq_residency") or []:
            if not isinstance(bin_, dict):
                continue
            rows.append(
                {
                    "cluster": name,
                    "freq_mhz": bin_.get("freq_mhz"),
                    "ratio": bin_.get("ratio"),
                    "time_ms": bin_.get("time_ms"),
                }
            )
    return rows


def sw_task_rows(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in evidence.get("sw_task_timing") or []:
        if not isinstance(task, dict):
            continue
        rows.append(
            {
                "task": task.get("task"),
                "cluster": task.get("cluster"),
                "mean_ms": task.get("mean_ms"),
                "p50_ms": task.get("p50_ms"),
                "p95_ms": task.get("p95_ms"),
                "max_ms": task.get("max_ms"),
                "count_per_frame": task.get("count_per_frame"),
                "samples": task.get("samples"),
            }
        )
    return rows


def vdd_power_rows(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    vdd = evidence.get("vdd_power") if isinstance(evidence.get("vdd_power"), dict) else {}
    rows: list[dict[str, Any]] = []
    for rail, entry in vdd.items():
        rows.append(
            {
                "rail": rail,
                "mean_mw": _rail_mw(entry, "mean_mw", "power_mw", "power", "mean"),
                "p95_mw": _rail_mw(entry, "p95_mw", "p95"),
            }
        )
    return rows


def artifact_rows(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for art in evidence.get("artifacts") or []:
        if not isinstance(art, dict):
            continue
        rows.append(
            {
                "type": art.get("type"),
                "storage": art.get("storage"),
                "path": art.get("path"),
                "bytes": art.get("bytes"),
                "sha256": art.get("sha256"),
            }
        )
    # legacy pointers under provenance.raw_artifacts
    prov = evidence.get("provenance") if isinstance(evidence.get("provenance"), dict) else {}
    for art in prov.get("raw_artifacts") or []:
        if isinstance(art, dict):
            rows.append(
                {
                    "type": art.get("type"),
                    "storage": "provenance",
                    "path": art.get("path"),
                    "bytes": None,
                    "sha256": art.get("sha256"),
                }
            )
    return rows


def provenance_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    prov = evidence.get("provenance") if isinstance(evidence.get("provenance"), dict) else {}
    ctx = evidence.get("execution_context") if isinstance(evidence.get("execution_context"), dict) else {}
    return {
        "method": ctx.get("method"),
        "silicon_rev": ctx.get("silicon_rev"),
        "thermal": ctx.get("thermal"),
        "ambient_temp_c": ctx.get("ambient_temp_c"),
        "power_state": ctx.get("power_state"),
        "device_id": prov.get("device_id"),
        "build_id": prov.get("build_id"),
        "collection_method": prov.get("collection_method"),
        "sample_count": prov.get("sample_count"),
        "duration_per_sample_s": prov.get("duration_per_sample_s"),
        "tool_versions": prov.get("collection_tool_versions"),
    }


# --- Streamlit rendering -----------------------------------------------------

def render_measurement_result(evidence: dict[str, Any], *, key_prefix: str = "meas") -> None:
    import streamlit as st

    from dashboard.components.table_actions import render_copyable_dataframe

    evidence_id = str(evidence.get("id") or "measurement")
    tabs = st.tabs(list(MEASUREMENT_TABS))

    with tabs[0]:
        _render_overview(st, evidence)
    with tabs[1]:
        _render_power(st, evidence, render_copyable_dataframe, key_prefix=f"{key_prefix}_{evidence_id}")
    with tabs[2]:
        _render_cpu_freq(st, evidence, render_copyable_dataframe, key_prefix=f"{key_prefix}_{evidence_id}")
    with tabs[3]:
        _render_sw_timing(st, evidence, render_copyable_dataframe, key_prefix=f"{key_prefix}_{evidence_id}")
    with tabs[4]:
        _render_provenance(st, evidence, render_copyable_dataframe, key_prefix=f"{key_prefix}_{evidence_id}")


def _render_overview(st, evidence: dict[str, Any]) -> None:
    prov = provenance_summary(evidence)
    chips = [c for c in (prov.get("method"), prov.get("silicon_rev"), prov.get("thermal"), prov.get("power_state")) if c]
    if chips:
        st.caption(" · ".join(str(c) for c in chips))
    measured_at = evidence.get("measured_at")
    if measured_at:
        st.caption(f"measured_at: {measured_at}")

    rows = kpi_summary_rows(evidence)
    headline = [r for r in rows if r["metric"] in ("total_power_mw", "peak_power_mw", "frame_latency_ms", "fps_effective")]
    if headline:
        cols = st.columns(len(headline))
        for col, row in zip(cols, headline):
            mean = row["mean"]
            delta = f"p95 {row['p95']}" if row["p95"] is not None else None
            col.metric(row["metric"], f"{mean:g}" if mean is not None else "—", delta)
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_power(st, evidence, render_table, *, key_prefix: str) -> None:
    clusters = cpu_cluster_rows(evidence)
    if clusters:
        st.markdown("**CPU cluster power (mW)**")
        _bar_with_p95(st, clusters, x="cluster", mean="power_mean_mw", p95="power_p95_mw", key=f"{key_prefix}_cpu")
        render_table(clusters, key=f"{key_prefix}_cpu_tbl", use_container_width=True, hide_index=True)
    rails = vdd_power_rows(evidence)
    if rails:
        st.markdown("**VDD rail power (mW)**")
        _bar_with_p95(st, rails, x="rail", mean="mean_mw", p95="p95_mw", key=f"{key_prefix}_vdd")
        render_table(rails, key=f"{key_prefix}_vdd_tbl", use_container_width=True, hide_index=True)
    if not clusters and not rails:
        st.info("No cpu_breakdown / vdd_power digest in this measurement.")


def _render_cpu_freq(st, evidence, render_table, *, key_prefix: str) -> None:
    rows = freq_residency_rows(evidence)
    if not rows:
        st.info("No freq_residency digest in this measurement.")
        return
    try:
        import plotly.express as px

        fig = px.bar(
            rows,
            x="cluster",
            y="ratio",
            color=[f"{r['freq_mhz']:g} MHz" for r in rows],
            labels={"color": "freq", "ratio": "residency"},
            title="Frequency residency by cluster",
        )
        fig.update_layout(barmode="stack", height=360, legend_title_text="freq")
        st.plotly_chart(fig, use_container_width=True)
    except Exception:  # noqa: BLE001 - chart is best-effort; table is the source of truth
        pass
    render_table(rows, key=f"{key_prefix}_freq_tbl", use_container_width=True, hide_index=True)


def _render_sw_timing(st, evidence, render_table, *, key_prefix: str) -> None:
    rows = sw_task_rows(evidence)
    if not rows:
        st.info("No sw_task_timing digest in this measurement.")
        return
    try:
        import plotly.express as px

        fig = px.bar(
            rows,
            x="p95_ms",
            y="task",
            orientation="h",
            color="cluster",
            title="SW task time (p95, ms)",
        )
        fig.update_layout(height=max(240, 48 * len(rows)))
        st.plotly_chart(fig, use_container_width=True)
    except Exception:  # noqa: BLE001
        pass
    render_table(rows, key=f"{key_prefix}_sw_tbl", use_container_width=True, hide_index=True)


def _render_provenance(st, evidence, render_table, *, key_prefix: str) -> None:
    summary = provenance_summary(evidence)
    st.json({k: v for k, v in summary.items() if v not in (None, {}, [])})
    arts = artifact_rows(evidence)
    if arts:
        st.markdown("**Raw artifacts** (stored outside the DB; sha256 for integrity)")
        render_table(arts, key=f"{key_prefix}_art_tbl", use_container_width=True, hide_index=True)
    else:
        st.caption("No raw artifact pointers recorded.")


def _bar_with_p95(st, rows, *, x: str, mean: str, p95: str, key: str) -> None:
    try:
        import plotly.graph_objects as go

        xs = [r[x] for r in rows]
        means = [r.get(mean) for r in rows]
        p95s = [r.get(p95) for r in rows]
        fig = go.Figure()
        fig.add_bar(x=xs, y=means, name="mean")
        if any(p is not None for p in p95s):
            err = [
                (p - m) if (isinstance(p, (int, float)) and isinstance(m, (int, float)) and p >= m) else 0
                for p, m in zip(p95s, means)
            ]
            fig.update_traces(error_y={"type": "data", "array": err, "visible": True})
        fig.update_layout(height=320, showlegend=False)
        st.plotly_chart(fig, use_container_width=True, key=key)
    except Exception:  # noqa: BLE001
        pass
