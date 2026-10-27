"""Bounded value-grid exploration on a single authoritative baseline."""
from __future__ import annotations

from itertools import product
from math import prod

from scenario_db.api.schemas.scenario_whatif import WhatIfPreviewRequest, WhatIfScope, WhatIfSweepRequest
from scenario_db.api.services import scenario_whatif as engine
from scenario_db.config import get_settings
from scenario_db.exceptions import ConflictError, UnprocessableError


def _latency(report):
    values = [v for k, v in (report.get("latency") or {}).items()
              if k.endswith("_ms") and isinstance(v, (int, float))]
    return max(values) if values else None


_IQ_EXCLUDED = "IQ 평가 필요 후보 제외"


def _eligibility(result, constraints):
    metrics = result["candidate"]["metrics"]
    report = result["candidate"]["report"]
    slack = engine._min_slack(report)[1]
    latency = _latency(report)
    reasons = list(report["verdict"].get("reasons") or []) if not metrics["feasible"] else []
    for key, value, label in (("max_power_mw", metrics["modeled_power_mw"], "모델 전력 상한"),
                              ("max_bw_mbs", metrics["bw_mbs"], "BW 상한"),
                              ("max_latency_ms", latency, "지연 상한")):
        cap = getattr(constraints, key)
        if cap is not None and (value is None or value > cap):
            reasons.append(f"{label}: {'모델 없음' if value is None else f'{value:g} > {cap:g}'}")
    if constraints.min_slack_ms is not None and slack < constraints.min_slack_ms:
        reasons.append(f"최소 여유 {slack:g} < {constraints.min_slack_ms:g} ms")
    if result.get("iq_required") and not constraints.allow_iq_required:
        reasons.append(_IQ_EXCLUDED)
    if result["candidate"]["coverage"].get("missing_components"):
        reasons.append("IP 성능/전력 모델 누락")
    return not reasons, reasons, slack, latency


def pareto(rows):
    """Exact small-grid frontier: minimize modeled power, traffic and latency.

    A row without a modeled latency stays a candidate: dominance is judged on the axes both rows have,
    so it is compared on power and traffic only."""
    eligible = [r for r in rows if r.get("eligible")]
    def values(row):
        return (row["metrics"]["modeled_power_mw"], row["metrics"]["bw_mbs"], row.get("latency_ms"))

    def dominates(a_row, b_row):
        pairs = [(a, b) for a, b in zip(values(a_row), values(b_row)) if a is not None and b is not None]
        return all(a <= b for a, b in pairs) and any(a < b for a, b in pairs)
    return [r["id"] for r in eligible if not any(dominates(other, r) for other in eligible if other is not r)]


def run_sweep(db, request: WhatIfSweepRequest, *, checkpoint=None, previous=None, base=None):
    count = prod(len(axis.values) for axis in request.axes)
    if count > get_settings().exploration_max_cases:
        raise UnprocessableError("What-if sweep exceeds the configured case limit")
    scope = WhatIfScope(**request.model_dump(include={"project_ref", "scenario_id", "variant_id"}))
    base = base or engine._baseline(db, scope, request)
    identity = base["analysis_hash"]
    if previous and previous.get("analysis_hash") != identity:
        raise ConflictError("Sweep inputs changed; start a new sweep instead of resuming")
    rows = list((previous or {}).get("rows") or [])
    out = {"scope": scope.model_dump(), "baseline_hash": request.expected_baseline_hash,
           "analysis_hash": identity, "baseline": {k: base["case"][k] for k in ("metrics", "coverage")},
           "model_lineage": base.get("lineage", {}), "rows": rows, "total_cases": count,
           "completed_cases": len(rows), "cancelled": False, "comparison": request.comparison,
           "constraints": request.constraints.model_dump(exclude_none=True),
           "pareto_ids": [], "best_id": None,
           "assumptions": ["범위 내 모델 계산이며 실측/IQ/배선 호환성을 보증하지 않습니다.",
                           "전력 제약과 순위는 센서/장치 누락분을 포함하지 않는 모델 소계 기준입니다."]}
    for index, values in enumerate(product(*(axis.values for axis in request.axes))):
        if index < len(rows):
            continue
        if checkpoint and not checkpoint(out):
            out["cancelled"] = True
            break
        changes = request.changes + list(values)
        row = {"id": f"case-{index + 1}", "label": " · ".join(
            f"{axis.label}={value.option or (f'{value.width}×{value.height}' if value.width else value.level if value.level is not None else value.value)}"
            for axis, value in zip(request.axes, values)),
            "changes": [c.model_dump(mode="json", exclude_none=True) for c in changes]}
        try:
            preview = WhatIfPreviewRequest(**scope.model_dump(), basis_ref=request.basis_ref,
                config=request.config, options=request.options, changes=changes, comparison=request.comparison,
                expected_baseline_hash=request.expected_baseline_hash, expected_analysis_hash=identity)
            row["preview_request"] = preview.model_dump(mode="json", exclude_unset=True)
            result = engine._preview_from(base, preview)
            eligible, reasons, slack, latency = _eligibility(result, request.constraints)
            row.update(metrics=result["candidate"]["metrics"], delta=result["delta"]["metrics"],
                       feasible=result["candidate"]["metrics"]["feasible"], eligible=eligible,
                       reasons=reasons, iq_required=result["iq_required"],
                       condition_hash=result["condition_hash"], min_slack_ms=slack, latency_ms=latency)
        except (ValueError, UnprocessableError) as exc:
            row.update(metrics=None, delta=None, feasible=False, eligible=False, reasons=[str(exc)],
                       iq_required=[], condition_hash=None, min_slack_ms=None, latency_ms=None)
        rows.append(row)
        out["completed_cases"] = len(rows)
    out["pareto_ids"] = pareto(rows)
    eligible = [r for r in rows if r.get("eligible")]
    out["best_id"] = min(eligible, key=lambda r: r["metrics"]["modeled_power_mw"])["id"] if eligible else None
    # IQ-trade alternative: rows that fail only because IQ-required candidates are excluded
    trade = [r for r in rows if r.get("metrics") and r.get("reasons") == [_IQ_EXCLUDED]]
    cheaper = [r for r in trade if not eligible or r["metrics"]["modeled_power_mw"]
               < min(e["metrics"]["modeled_power_mw"] for e in eligible)]
    best_trade = min(cheaper, key=lambda r: r["metrics"]["modeled_power_mw"]) if cheaper else None
    out["best_trade_id"] = best_trade["id"] if best_trade else None
    if checkpoint:
        checkpoint(out)
    return out
