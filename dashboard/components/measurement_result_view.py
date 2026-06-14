"""Measurement evidence rendering for the Evidence Dashboard.

Data-shaping helpers are pure (no Streamlit) so they can be unit-tested; the
``render_*`` functions wrap them with Streamlit + Plotly. Measurement evidence
carries statistical KPIs (mean/p95/ci), cpu_breakdown (cluster power + freq
residency), sw_task_timing, vdd_power, and raw artifact pointers.
"""
from __future__ import annotations

import colorsys
import hashlib
from collections import defaultdict
from typing import Any

from scenario_db.sim.constants import PMIC_EFFICIENCY_DEFAULT, VBAT_DEFAULT

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
        row = {
            "metric": metric,
            "prediction": _rounded_number(pred_value),
            "measurement_mean": _rounded_number(meas_mean),
            "measurement_p95": _rounded_number(kpi_p95(meas_kpi.get(metric))),
            "delta_vs_measurement": delta,
            "delta_pct_vs_measurement": _delta_pct_label(delta, meas_mean),
        }
        if metric == "total_power_mw":
            row.update(_power_current_comparison(prediction, pred_kpi, meas_kpi, pred_value, meas_mean))
        rows.append(row)
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


def _power_current_comparison(
    prediction: dict[str, Any],
    pred_kpi: dict[str, Any],
    meas_kpi: dict[str, Any],
    pred_power_mw: float,
    meas_power_mw: float,
) -> dict[str, float]:
    pred_current_ma = kpi_mean(pred_kpi.get("total_power_ma")) or kpi_mean(pred_kpi.get("power_ma"))
    meas_current_ma = kpi_mean(meas_kpi.get("total_power_ma")) or kpi_mean(meas_kpi.get("power_ma"))
    vbat, pmic_efficiency = _conversion_settings(prediction, pred_power_mw, pred_current_ma)
    if pred_current_ma is None:
        pred_current_ma = _mw_to_ma(pred_power_mw, vbat, pmic_efficiency)
    if meas_current_ma is None:
        meas_current_ma = _mw_to_ma(meas_power_mw, vbat, pmic_efficiency)

    out: dict[str, float] = {}
    if pred_current_ma is not None:
        out["prediction_current_ma"] = _rounded_number(pred_current_ma)
    if meas_current_ma is not None:
        out["measurement_current_ma"] = _rounded_number(meas_current_ma)
    if pred_current_ma is not None and meas_current_ma is not None:
        out["delta_current_ma"] = _rounded_number(pred_current_ma - meas_current_ma)
    out["vbat_voltage_v"] = _rounded_number(vbat)
    out["pmic_efficiency"] = _rounded_number(pmic_efficiency)
    return out


def _conversion_settings(
    prediction: dict[str, Any],
    pred_power_mw: float,
    pred_current_ma: float | None,
) -> tuple[float, float]:
    trace = prediction.get("calculation_trace") if isinstance(prediction.get("calculation_trace"), dict) else {}
    kpi_trace = trace.get("kpi") if isinstance(trace.get("kpi"), dict) else {}
    total_ma_trace = kpi_trace.get("total_power_ma") if isinstance(kpi_trace.get("total_power_ma"), dict) else {}
    inputs = total_ma_trace.get("inputs") if isinstance(total_ma_trace.get("inputs"), dict) else {}

    vbat = inputs.get("vbat")
    pmic = inputs.get("pmic_efficiency")
    vbat_value = float(vbat) if isinstance(vbat, (int, float)) and vbat > 0 else float(VBAT_DEFAULT)
    if isinstance(pmic, (int, float)) and pmic > 0:
        return vbat_value, float(pmic)
    if pred_current_ma is not None and pred_current_ma > 0 and pred_power_mw > 0:
        return vbat_value, pred_power_mw / pred_current_ma / vbat_value
    return vbat_value, float(PMIC_EFFICIENCY_DEFAULT)


def _mw_to_ma(power_mw: float, vbat: float, pmic_efficiency: float) -> float | None:
    if vbat <= 0 or pmic_efficiency <= 0:
        return None
    return power_mw / vbat / pmic_efficiency


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
    """Per-rail measurement rows.

    Supports both the rail_long triplet shape ({voltage_v, current_ma,
    power_mw, std_mw}) and the legacy power-only shape ({mean_mw, p95_mw}).
    Columns that are entirely empty (e.g. voltage on a legacy digest) are
    dropped so the table stays clean for either source.
    """
    vdd = evidence.get("vdd_power") if isinstance(evidence.get("vdd_power"), dict) else {}
    rows: list[dict[str, Any]] = []
    for rail, entry in vdd.items():
        rows.append(
            {
                "rail": rail,
                "voltage_v": _rail_mw(entry, "voltage_v", "mean_v"),
                "current_ma": _rail_mw(entry, "current_ma", "mean_ma"),
                "mean_mw": _rail_mw(entry, "mean_mw", "power_mw", "power", "mean"),
                "std_mw": _rail_mw(entry, "std_mw", "std"),
                "p95_mw": _rail_mw(entry, "p95_mw", "p95"),
            }
        )
    return _drop_empty_columns(rows, keep="rail")


def _drop_empty_columns(rows: list[dict[str, Any]], *, keep: str) -> list[dict[str, Any]]:
    if not rows:
        return rows
    cols = list(rows[0].keys())
    keepers = [c for c in cols if c == keep or any(r.get(c) is not None for r in rows)]
    return [{c: r.get(c) for c in keepers} for r in rows]


# Rail-name -> power domain. Project rail names are arbitrary, so classify by
# the well-known tokens they carry. Order matters (ICPU before CPU, etc.).
_DOMAIN_TOKENS: tuple[tuple[str, str], ...] = (
    ("ICPU", "ICPU"),
    ("CPUCL", "CPU"),
    ("G3D", "GPU"),
    ("NPU", "NPU"),
    ("CAM", "CAM"),
    ("MIF", "MIF"),
    ("DRAM", "MEM"),
    ("SRAM", "MEM"),
    ("MEM", "MEM"),
    ("INT", "INT"),
    ("DSU", "CPU"),
)


# Per-project rail -> domain overrides. Rail names differ per project, so a
# fixed token heuristic cannot be universal; populate this (or pass domain_map)
# to override classification for a given project_ref. Heuristic is the fallback.
PROJECT_RAIL_DOMAINS: dict[str, dict[str, str]] = {}


def resolve_domain_map(evidence: dict[str, Any]) -> dict[str, str] | None:
    """Rail -> domain map for the evidence.

    Priority: domain declared on the vdd_power entry (from meta.power.rails /
    hand-written canonical) > per-project override > (per-rail) name heuristic.
    Returns None when nothing is declared so callers fall back to the heuristic.
    """
    vdd = evidence.get("vdd_power") if isinstance(evidence.get("vdd_power"), dict) else {}
    declared = {
        rail: entry["domain"]
        for rail, entry in vdd.items()
        if isinstance(entry, dict) and isinstance(entry.get("domain"), str)
    }
    project = PROJECT_RAIL_DOMAINS.get(str(evidence.get("project_ref") or "")) or {}
    merged = {**project, **declared}
    return merged or None


def rail_domain(rail: str, domain_map: dict[str, str] | None = None) -> str:
    """Classify a rail name into a coarse power domain for rollups.

    A per-project ``domain_map`` (rail -> domain) wins; otherwise fall back to
    the token heuristic.
    """
    if domain_map and rail in domain_map:
        return domain_map[rail]
    upper = str(rail).upper()
    for token, domain in _DOMAIN_TOKENS:
        if token in upper:
            return domain
    return "OTHER"


def vdd_domain_rows(
    evidence: dict[str, Any],
    *,
    source_key: str = "mean_mw",
    out_key: str = "power_mw",
    domain_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate a per-rail metric into coarse domains, sorted desc."""
    totals: dict[str, float] = {}
    for row in vdd_power_rows(evidence):
        value = row.get(source_key)
        if value is None:
            continue
        domain = rail_domain(row["rail"], domain_map)
        totals[domain] = totals.get(domain, 0.0) + float(value)
    rows = [{"domain": d, out_key: round(v, 3)} for d, v in totals.items()]
    rows.sort(key=lambda r: r[out_key], reverse=True)
    return rows


# Fixed hue (0..1) per known domain so a category keeps a stable colour family;
# unknown domains hash to a hue. Within a category, lightness varies per rail.
_DOMAIN_HUES: dict[str, float] = {
    "CPU": 0.58, "MEM": 0.33, "CAM": 0.07, "GPU": 0.80,
    "INT": 0.12, "MIF": 0.50, "ICPU": 0.63, "NPU": 0.92, "OTHER": 0.00,
}


def _domain_hue(domain: str) -> float:
    hue = _DOMAIN_HUES.get(domain)
    if hue is not None:
        return hue
    digest = hashlib.sha1(str(domain).encode("utf-8")).digest()
    return (int.from_bytes(digest[:4], "big") % 360) / 360.0


def _hsl_rgb(hue: float, light: float, sat: float = 0.62) -> str:
    r, g, b = colorsys.hls_to_rgb(hue, light, sat)
    return f"rgb({int(r * 255)},{int(g * 255)},{int(b * 255)})"


def domain_colors(domains: list[str]) -> list[str]:
    """One representative colour per domain (for the domain rollup bar)."""
    return [_hsl_rgb(_domain_hue(d), 0.52) for d in domains]


def rail_bar_colors(rows: list[dict[str, Any]], domain_map: dict[str, str] | None = None) -> list[str]:
    """Colour per rail: same hue within a domain, distinct lightness per rail."""
    groups: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        groups[rail_domain(row["rail"], domain_map)].append(i)
    colors: list[str] = [""] * len(rows)
    for domain, idxs in groups.items():
        hue = _domain_hue(domain)
        n = len(idxs)
        for k, i in enumerate(idxs):
            light = 0.40 + (0.34 * k / (n - 1) if n > 1 else 0.12)
            colors[i] = _hsl_rgb(hue, light)
    return colors


def frame_budget_status(evidence: dict[str, Any]) -> dict[str, Any] | None:
    """Frame latency vs the fps budget (1000/fps ms). None if no frame latency."""
    kpi = evidence.get("kpi") if isinstance(evidence.get("kpi"), dict) else {}
    latency = kpi.get("frame_latency_ms")
    p95 = kpi_p95(latency)
    mean = kpi_mean(latency)
    if p95 is None and mean is None:
        return None
    fps = kpi_mean(kpi.get("fps_effective")) or 30.0
    budget_ms = round(1000.0 / fps, 2) if fps > 0 else None
    ref = p95 if p95 is not None else mean
    ok = (budget_ms is not None and ref is not None and ref <= budget_ms)
    return {"fps": fps, "budget_ms": budget_ms, "p95_ms": p95, "mean_ms": mean, "ok": ok}


def top_sw_task(evidence: dict[str, Any]) -> dict[str, Any] | None:
    """The heaviest SW task by p95 (fallback mean), for the overview headline."""
    best: dict[str, Any] | None = None
    best_key = -1.0
    for row in sw_task_rows(evidence):
        key = row.get("p95_ms")
        if key is None:
            key = row.get("mean_ms")
        if key is None:
            continue
        if float(key) > best_key:
            best_key, best = float(key), row
    return best


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

    status = frame_budget_status(evidence)
    if status and status["budget_ms"] is not None:
        ref = status["p95_ms"] if status["p95_ms"] is not None else status["mean_ms"]
        label = "p95" if status["p95_ms"] is not None else "mean"
        mark = "✅ within" if status["ok"] else "⚠️ exceeds"
        st.caption(
            f"Frame {label} {ref:g}ms vs {status['fps']:g}fps budget {status['budget_ms']:g}ms — {mark}"
        )
    top = top_sw_task(evidence)
    if top:
        cluster = f" ({top['cluster']})" if top.get("cluster") else ""
        metric = top.get("p95_ms") if top.get("p95_ms") is not None else top.get("mean_ms")
        st.caption(f"Top SW task: {top.get('task')}{cluster} · {metric:g}ms")

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
    domain_map = resolve_domain_map(evidence)
    rails = vdd_power_rows(evidence)
    has_current = any(r.get("current_ma") is not None for r in rails)
    value_key = "current_ma" if has_current else "mean_mw"
    unit = "mA" if has_current else "mW"

    domains = vdd_domain_rows(evidence, source_key=value_key, out_key=value_key, domain_map=domain_map)
    if domains:
        st.markdown(f"**Current by domain ({unit})** — where the current goes" if has_current
                    else f"**Power by domain ({unit})**")
        _value_bar(
            st, domains, x="domain", y=value_key,
            colors=domain_colors([d["domain"] for d in domains]), key=f"{key_prefix}_dom",
        )

    if rails:
        rails = sorted(rails, key=lambda r: (r.get(value_key) is not None, r.get(value_key) or 0.0), reverse=True)
        st.markdown(f"**Rails by current ({unit})** — sorted, coloured by domain" if has_current
                    else f"**Rails by power ({unit})** — sorted")
        _value_bar(
            st, rails, x="rail", y=value_key,
            colors=rail_bar_colors(rails, domain_map), key=f"{key_prefix}_vdd",
        )
        st.caption("같은 domain 은 같은 색 계열(명도만 다름). 전압(V)·전력(mW)은 표 참조.")
        render_table(_rows_with_domain(rails, domain_map), key=f"{key_prefix}_vdd_tbl", use_container_width=True, hide_index=True)

    clusters = cpu_cluster_rows(evidence)
    if clusters:
        st.markdown("**CPU cluster power (mW)**")
        _bar_with_p95(st, clusters, x="cluster", mean="power_mean_mw", p95="power_p95_mw", key=f"{key_prefix}_cpu")
        render_table(clusters, key=f"{key_prefix}_cpu_tbl", use_container_width=True, hide_index=True)

    if not rails and not clusters:
        st.info("No vdd_power / cpu_breakdown digest in this measurement.")


def _rows_with_domain(rows: list[dict[str, Any]], domain_map: dict[str, str] | None) -> list[dict[str, Any]]:
    """Insert a 'domain' column right after 'rail' so the table shows the mapping."""
    out: list[dict[str, Any]] = []
    for row in rows:
        new = {"rail": row.get("rail"), "domain": rail_domain(row["rail"], domain_map)}
        new.update({k: v for k, v in row.items() if k != "rail"})
        out.append(new)
    return out


def _value_bar(st, rows, *, x: str, y: str, colors: list[str], key: str) -> None:
    """Bar with per-bar colours; label shows the value and its share of total."""
    try:
        import plotly.graph_objects as go

        ys = [r.get(y) for r in rows]
        total = sum(v for v in ys if isinstance(v, (int, float)))

        def _label(v: Any) -> str:
            if not isinstance(v, (int, float)):
                return ""
            pct = (v / total * 100.0) if total else 0.0
            return f"{v:.1f} ({pct:.1f}%)"

        fig = go.Figure(
            go.Bar(
                x=[r[x] for r in rows],
                y=ys,
                marker_color=colors,
                text=[_label(v) for v in ys],
                textposition="outside",
                cliponaxis=False,
            )
        )
        fig.update_layout(height=340, showlegend=False, margin={"t": 28, "b": 8})
        st.plotly_chart(fig, use_container_width=True, key=key)
    except Exception:  # noqa: BLE001 - chart is best-effort; table is the source of truth
        pass


def _render_cpu_freq(st, evidence, render_table, *, key_prefix: str) -> None:
    rows = freq_residency_rows(evidence)
    if not rows:
        st.info("No freq_residency digest in this measurement.")
        return
    chips = [
        f"{c['cluster']}: {c['avg_freq_mhz']:g}MHz avg · util {c['util_pct']:g}%"
        for c in cpu_cluster_rows(evidence)
        if c.get("avg_freq_mhz") is not None or c.get("util_pct") is not None
    ]
    if chips:
        st.caption(" · ".join(chips))
    try:
        import plotly.express as px

        fig = px.bar(
            rows,
            x="cluster",
            y="ratio",
            color=[f"{r['freq_mhz']:g} MHz" for r in rows],
            text=[f"{(r.get('ratio') or 0) * 100:.0f}%" for r in rows],
            labels={"color": "freq", "ratio": "residency"},
            title="Frequency residency by cluster (% of time)",
        )
        fig.update_traces(textposition="inside", insidetextanchor="middle")
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
    rows = sorted(rows, key=lambda r: (r.get("p95_ms") is not None, r.get("p95_ms") or 0.0), reverse=True)
    status = frame_budget_status(evidence)
    try:
        import plotly.express as px

        fig = px.bar(
            rows,
            x="p95_ms",
            y="task",
            orientation="h",
            color="cluster",
            title="SW task time (p95, ms) — sorted",
        )
        fig.update_layout(height=max(240, 48 * len(rows)), yaxis={"categoryorder": "total ascending"})
        if status and status["budget_ms"] is not None:
            fig.add_vline(
                x=status["budget_ms"],
                line_dash="dash",
                line_color="#DC2626",
                annotation_text=f"frame budget {status['budget_ms']:g}ms",
            )
        st.plotly_chart(fig, use_container_width=True)
    except Exception:  # noqa: BLE001
        pass
    st.caption("count_per_frame = 프레임당 호출 수. p95/max 로 병목·jank 판단.")
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
