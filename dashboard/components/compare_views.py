"""Pure helpers for the Variant Compare page (structure and evidence diffs)."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from dashboard.components.pipeline_tables import _elements

_DMA_ATTRS = ("Size", "Format", "Bit", "Compression", "WDMA port", "RDMA port")


def _dma_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("Producer") or ""), str(row.get("Buffer") or ""), str(row.get("Consumer") or ""))


def dma_diff(rows_a: Iterable[Mapping[str, Any]], rows_b: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Transfer-level diff: B only / A only / changed attributes."""
    a = {_dma_key(row): row for row in rows_a}
    b = {_dma_key(row): row for row in rows_b}
    out = []
    for key in sorted(set(a) | set(b)):
        ra, rb = a.get(key), b.get(key)
        producer, buffer, consumer = key
        base = {"Producer": producer, "Buffer": buffer, "Consumer": consumer}
        if ra is None:
            out.append({**base, "status": "B only", "change": _summary(rb)})
        elif rb is None:
            out.append({**base, "status": "A only", "change": _summary(ra)})
        else:
            changes = [f"{attr}: {ra.get(attr) or '—'} → {rb.get(attr) or '—'}"
                       for attr in _DMA_ATTRS if str(ra.get(attr) or "") != str(rb.get(attr) or "")]
            out.append({**base, "status": "changed" if changes else "same", "change": "; ".join(changes)})
    order = {"B only": 0, "A only": 1, "changed": 2, "same": 3}
    return sorted(out, key=lambda row: (order[row["status"]], row["Producer"], row["Buffer"]))


def _summary(row: Mapping[str, Any] | None) -> str:
    if not row:
        return ""
    parts = [str(row.get(attr)) for attr in ("Size", "Format", "Compression") if row.get(attr)]
    return " · ".join(parts)


def active_units(view: Any) -> dict[str, str]:
    """IP / SW nodes visible in a view, label -> type."""
    out = {}
    for node in _elements(view, "nodes"):
        if node.get("type") in {"ip", "sw"}:
            out[str(node.get("label") or node.get("id"))] = str(node.get("type"))
    return out


def unit_diff(view_a: Any, view_b: Any) -> dict[str, list[str]]:
    a, b = active_units(view_a), active_units(view_b)
    return {
        "common": sorted(set(a) & set(b)),
        "a_only": sorted(set(a) - set(b)),
        "b_only": sorted(set(b) - set(a)),
    }


KPI_FIELDS = (
    ("Total power", ("total_power_mw",), "mW"),
    ("Core power", ("core_power_mw",), "mW"),
    ("BW power", ("bw_power_mw",), "mW"),
    ("Total BW", ("total_bw_mbs",), "MB/s"),
    ("Frame latency", ("frame_latency_ms",), "ms"),
    ("HW time max", ("hw_time_max_ms",), "ms"),
    ("Effective fps", ("fps_effective",), "fps"),
)


def kpi_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Mapping):
        for key in ("mean", "value", "p50"):
            if isinstance(value.get(key), (int, float)):
                return float(value[key])
    return None


def kpi_side_by_side(evidence_a: Mapping[str, Any] | None, evidence_b: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    kpi_a = dict((evidence_a or {}).get("kpi") or {})
    kpi_b = dict((evidence_b or {}).get("kpi") or {})
    rows = []
    for label, keys, unit in KPI_FIELDS:
        va = next((kpi_number(kpi_a.get(key)) for key in keys if key in kpi_a), None)
        vb = next((kpi_number(kpi_b.get(key)) for key in keys if key in kpi_b), None)
        if va is None and vb is None:
            continue
        delta = None if va is None or vb is None else round(vb - va, 3)
        pct = None if delta is None or not va else round(delta / va * 100, 1)
        rows.append({"KPI": label, "unit": unit, "A": va, "B": vb, "Δ (B−A)": delta, "Δ%": pct})
    return rows


def evidence_kind_label(item: Mapping[str, Any]) -> str:
    kind = str(item.get("kind") or "")
    if kind == "evidence.measurement":
        scope = str((item.get("profiling_metadata") or {}).get("measurement_scope") or "")
        return "synthetic" if "synthetic" in scope.lower() or "synthetic" in str(item.get("id")) else "measured"
    if kind == "evidence.simulation":
        return "calculated"
    return kind.replace("evidence.", "") or "unknown"


def evidence_option_label(item: Mapping[str, Any]) -> str:
    ctx = item.get("execution_context") or {}
    parts = [evidence_kind_label(item), str(item.get("id"))]
    extra = " · ".join(str(ctx.get(key)) for key in ("silicon_rev", "sw_baseline_ref") if ctx.get(key))
    return " | ".join(parts) + (f" ({extra})" if extra else "")


def pm_rows(result: Mapping[str, Any], *, metric_filter: str | None = None) -> list[dict[str, Any]]:
    """Prediction-measurement comparison rows ready for a table."""
    rows = []
    for row in result.get("rows") or []:
        metric = str(row.get("metric_id") or "")
        if metric_filter and metric_filter.lower() not in metric.lower():
            continue
        rows.append(
            {
                "metric": metric,
                "scope": str(row.get("scope_ref") or row.get("scope_kind") or ""),
                "unit": row.get("unit") or "",
                "예측": row.get("prediction"),
                "실측": row.get("measurement"),
                "Δ": row.get("delta"),
                "Δ%": row.get("delta_pct"),
                "status": row.get("status"),
            }
        )
    return rows


def domain_chart_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Long-form rows (domain, side, mW) for a grouped bar chart of power.domain."""
    out = []
    for row in result.get("rows") or []:
        if row.get("metric_id") != "power.domain":
            continue
        for side, key in (("예측", "prediction"), ("실측", "measurement")):
            if isinstance(row.get(key), (int, float)):
                out.append({"domain": str(row.get("scope_ref")), "side": side, "mW": float(row[key])})
    return out


def rails_without_domain(evidence: Mapping[str, Any] | None) -> list[tuple[str, float]]:
    """Measured rails that cannot join power.domain because no domain is declared."""
    out = []
    for rail, entry in ((evidence or {}).get("vdd_power") or {}).items():
        if isinstance(entry, Mapping) and not entry.get("domain"):
            power = entry.get("power_mw")
            out.append((str(rail), float(power) if isinstance(power, (int, float)) else 0.0))
    return sorted(out, key=lambda item: -item[1])


def kpi_matrix(evidence_by_variant: Mapping[str, Mapping[str, Any] | None], reference: str) -> list[dict[str, Any]]:
    """KPI rows × variant columns, plus Δ% of each variant against the reference."""
    rows = []
    for label, keys, unit in KPI_FIELDS:
        values = {}
        for variant, evidence in evidence_by_variant.items():
            kpi = dict((evidence or {}).get("kpi") or {})
            values[variant] = next((kpi_number(kpi.get(key)) for key in keys if key in kpi), None)
        if all(value is None for value in values.values()):
            continue
        row: dict[str, Any] = {"KPI": f"{label} ({unit})"}
        base = values.get(reference)
        for variant, value in values.items():
            row[variant] = value
            if variant != reference:
                row[f"Δ% {variant}"] = None if value is None or not base else round((value - base) / base * 100, 1)
        rows.append(row)
    return rows


def dma_matrix(rows_by_variant: Mapping[str, Iterable[Mapping[str, Any]]], *, only_different: bool = True) -> list[dict[str, Any]]:
    """Transfer (Producer→Buffer→Consumer) × variant presence with size/format/compression cells."""
    cells: dict[tuple[str, str, str], dict[str, str]] = {}
    for variant, rows in rows_by_variant.items():
        for row in rows:
            cells.setdefault(_dma_key(row), {})[variant] = _summary(row) or "✓"
    variants = list(rows_by_variant)
    out = []
    for key in sorted(cells):
        values = [cells[key].get(variant, "—") for variant in variants]
        if only_different and len(set(values)) == 1:
            continue
        producer, buffer, consumer = key
        out.append({"transfer": f"{producer} → {buffer} → {consumer}", **dict(zip(variants, values))})
    return out


# ---------------------------------------------------------------------------
# Column-per-variant layouts (N-way compare): rows = attributes, columns = variants
# ---------------------------------------------------------------------------

def short_labels(variant_ids: list[str]) -> dict[str, str]:
    """Strip the shared hyphen-token prefix so variant columns stay narrow."""
    if len(variant_ids) < 2:
        return {vid: vid for vid in variant_ids}
    tokens = [vid.split("-") for vid in variant_ids]
    common = 0
    for parts in zip(*tokens):
        if len(set(parts)) != 1:
            break
        common += 1
    common = min(common, min(len(t) for t in tokens) - 1)
    labels = {vid: "-".join(parts[common:]) or vid for vid, parts in zip(variant_ids, tokens)}
    if len(set(labels.values())) != len(labels):
        return {vid: vid for vid in variant_ids}
    return labels


def common_prefix(variant_ids: list[str]) -> str:
    labels = short_labels(variant_ids)
    first = variant_ids[0] if variant_ids else ""
    short = labels.get(first, first)
    return first[: len(first) - len(short)] if short != first else ""


def condition_matrix(
    selected: list[Mapping[str, Any]],
    reference: str,
    keys: list[str],
) -> tuple[list[dict[str, Any]], set[tuple[int, str]]]:
    """Condition rows × variant columns; returns highlighted (row index, column) cells."""
    from dashboard.components.variant_compare import pivot_rows

    ids = [str(item.get("variant_id")) for item in selected]
    labels = short_labels(ids)
    rows_by_variant, changed_by_variant = {}, {}
    pivot, changed = pivot_rows(selected, reference, keys)
    for row, diff in zip(pivot, changed):
        rows_by_variant[row["variant"]] = row
        changed_by_variant[row["variant"]] = set(diff)
    header_rows = [("Δ vs 기준", "Δ"), ("비교 대상", "vs"), ("load", "load")]
    out: list[dict[str, Any]] = []
    highlight: set[tuple[int, str]] = set()
    def header_value(vid: str, field: str) -> str:
        value = rows_by_variant[vid].get(field)
        if field == "vs":
            return "★ 기준" if vid == reference else labels.get(str(value), str(value or ""))
        return "" if value is None else str(value)

    for title, field in header_rows:
        out.append({"조건": title, **{labels[vid]: header_value(vid, field) for vid in ids}})
    for key in keys + ["assumed"]:
        row = {"조건": key}
        for vid in ids:
            row[labels[vid]] = rows_by_variant[vid].get(key, "")
            if key in changed_by_variant[vid]:
                highlight.add((len(out), labels[vid]))
        if key == "assumed" and not any(row[labels[vid]] for vid in ids):
            continue
        out.append(row)
    return out, highlight


def kpi_matrix_wide(evidence_by_variant: Mapping[str, Mapping[str, Any] | None], reference: str) -> list[dict[str, Any]]:
    """KPI rows × variant columns; each cell is 'value (Δ% vs reference)'."""
    ids = list(evidence_by_variant)
    labels = short_labels(ids)
    out = [{"KPI": "evidence 출처", **{labels[vid]: evidence_kind_label(ev) if ev else "없음"
                                      for vid, ev in evidence_by_variant.items()}}]
    for row in kpi_matrix(evidence_by_variant, reference):
        wide = {"KPI": row["KPI"]}
        for vid in ids:
            value, pct = row.get(vid), row.get(f"Δ% {vid}")
            if value is None:
                wide[labels[vid]] = "—"
            elif vid == reference or pct is None:
                wide[labels[vid]] = f"{value:,.1f}"
            else:
                wide[labels[vid]] = f"{value:,.1f} ({pct:+.1f}%)"
        out.append(wide)
    return out
