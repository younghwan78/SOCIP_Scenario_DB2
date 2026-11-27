"""M-10: the KPI registry - supplemental judgement of the declared KPIs against the R-6 targets.

The frame-interval path (``timing_budget._verdict``) still judges ``interval`` and ``latency`` of the frame
outputs. This registry reads the report sections other models already produced and judges the rest:

* ``event_latency`` / ``event_energy`` / ``peak_*``: ``report.jobs`` (job-v1), per active job declaring the KPI
* ``frame_pacing``: ``report.pacing`` (frame-pacing-v1)
* ``underrun``: ``report.subsystems[*].deadline_slack`` (mcps-v1; v1 = the smallest deadline slack, not a count)
* ``latency``: ``report.subsystems[*].route`` - only when no frame output is judged by the interval path; the
  route's own ``latency_target_ms`` is the target unless a ``judgement.targets`` entry gives one

Status: pass / fail with a target, ``no_target`` (value only), ``no_input`` (the section or value is missing;
never a pass), ``unmodeled`` (no evaluator). A fail fails the verdict; a pass never lifts a ``not_applicable``
verdict (``verdict.kpis`` carries the summary). Without KPI declarations nothing is produced.
"""

from __future__ import annotations

from typing import Any

from scenario_db.models.definition.usecase import JOB_KPIS, KPI_METRICS, JudgementContract, KpiTarget
from scenario_db.sim.judgement import select_targets

# fail > no_input > unmodeled > no_target > pass
STATUS_ORDER = ("fail", "no_input", "unmodeled", "no_target", "pass")
# KPIs with an evaluator here (MODELED_KPIS = interval / latency + these; a test keeps them equal)
KPI_MODELS = ("latency", "underrun", "frame_pacing", "event_latency", "event_energy", "peak_power", "peak_bw",
              "peak_footprint")
PACING_METRICS = {"jank_pct": ("jank_pct",), "achieved_fps": ("achieved_fps",),
                  "frame_p99_ms": ("frame_ms", "p99"), "present_cov": ("present_interval_cov",)}
JOB_VALUES = {"event_energy": ("energy_mj", "event"), "peak_power": ("peak", "power_mw"),
              "peak_bw": ("peak", "bw_mbs"), "peak_footprint": ("peak", "footprint_mb")}


def _dig(section: Any, path: tuple[str, ...]) -> float | None:
    for key in path:
        section = section.get(key) if isinstance(section, dict) else None
    return float(section) if isinstance(section, (int, float)) and not isinstance(section, bool) else None


def _row(kpi: str, value: float | None, target: KpiTarget | None, *, metric: str | None = None,
         job: str | None = None, milestone: str | None = None, sources: list[str] | None = None,
         status: str | None = None, fallback: tuple[float, str, str] | None = None) -> dict[str, Any]:
    """One KPI result. ``fallback`` = (bound value, value_source, basis) when no declared target applies."""
    unit, bound = KPI_METRICS[kpi][metric if metric in KPI_METRICS[kpi] else None]
    limit = None
    value_source = basis = target_id = None
    if target is not None:
        limit = target.max if target.max is not None else target.min
        value_source, basis, target_id = target.value_source, target.basis, target.id
    elif fallback is not None:
        limit, value_source, basis = fallback
    if status is None:
        if value is None:
            status = "no_input"
        elif limit is None:
            status = "no_target"
        else:
            ok = value <= limit + 1e-9 if bound == "max" else value >= limit - 1e-9
            status = "pass" if ok else "fail"
    return {"id": target_id, "kpi": kpi, "metric": metric, "job": job, "milestone": milestone, "status": status,
            "value": None if value is None else round(value, 4), "target": limit,
            "bound": bound if limit is not None else None, "unit": unit, "value_source": value_source,
            "basis": basis, "sources": sorted(set(sources or []))}


def _frame_interval_judged(report: dict[str, Any]) -> bool:
    intervals = report.get("intervals") or {}
    return not ((intervals.get("preview") or {}).get("ok") is None and (intervals.get("video") or {}).get("ok") is None
                and not intervals.get("streams"))


def _scenario_rows(kpi: str, report: dict[str, Any], targets: list[KpiTarget]) -> list[dict[str, Any]]:
    """Rows of a scenario-level KPI (``judgement.kpis``); [] when another path judges it."""
    mine = [t for t in targets if t.kpi == kpi]
    if kpi == "interval":
        return []
    if kpi == "latency":
        if _frame_interval_judged(report):
            return []                      # the frame-interval path judges latency
        routes = [(n, s["route"], s.get("value_source")) for n, s in (report.get("subsystems") or {}).items()
                  if isinstance(s, dict) and isinstance(s.get("route"), dict)]
        if not routes:
            return [_row(kpi, None, mine[0] if mine else None, status="unmodeled" if not report.get("subsystems")
                         else None)]
        rows = []
        for node, route, source in routes:
            own = route.get("latency_target_ms")
            fallback = (float(own), str(source or "assumed"), f"{node} route {route.get('id')} latency_target_ms") \
                if isinstance(own, (int, float)) else None
            rows.append(_row(kpi, _dig(route, ("latency_ms",)), mine[0] if mine else None, fallback=fallback,
                             sources=[str(source)] if source else []))
        return rows
    if kpi == "underrun":
        subs = [s for s in (report.get("subsystems") or {}).values() if isinstance(s, dict)]
        slack = [float(r["slack_ms"]) for s in subs for r in s.get("deadline_slack") or []
                 if isinstance(r.get("slack_ms"), (int, float))]
        return [_row(kpi, min(slack) if slack else None, mine[0] if mine else None,
                     sources=[str(s["value_source"]) for s in subs if s.get("value_source")])]
    if kpi == "frame_pacing":
        pacing = report.get("pacing")
        usable = isinstance(pacing, dict) and pacing.get("status") in ("ok", "fail")
        by_metric = {t.key()[1]: t for t in mine}
        rows = []
        for metric in dict.fromkeys(["jank_pct", *by_metric]):
            value = _dig(pacing, PACING_METRICS[metric]) if usable else None
            rows.append(_row(kpi, value, by_metric.get(metric), metric=metric,
                             sources=[str(pacing["value_source"])] if usable and pacing.get("value_source") else []))
        return rows
    return [_row(kpi, None, mine[0] if mine else None, status="unmodeled")]


def _job_rows(job: dict[str, Any], kpis: list[str], targets: list[KpiTarget]) -> list[dict[str, Any]]:
    """Rows of one evaluated job; a target naming the job wins over one for every job."""
    def pick(kpi: str, milestone: str | None = None) -> KpiTarget | None:
        cands = [t for t in targets if t.kpi == kpi and t.milestone == milestone and t.job in (job["id"], None)]
        return next((t for t in cands if t.job == job["id"]), cands[0] if cands else None)

    sources = sorted({str(st["value_source"]) for st in job.get("stages") or [] if st.get("value_source")})
    rows = []
    for kpi in kpis:
        if kpi == "event_latency":
            for name, at in (job.get("milestones") or {}).items():
                rows.append(_row(kpi, at if isinstance(at, (int, float)) else None, pick(kpi, name), job=job["id"],
                                 milestone=name, sources=sources))
        elif kpi in JOB_VALUES:
            rows.append(_row(kpi, _dig(job, JOB_VALUES[kpi]), pick(kpi), job=job["id"], sources=sources))
        elif kpi in JOB_KPIS:          # event_rate: no evaluator yet
            rows.append(_row(kpi, None, pick(kpi), job=job["id"], status="unmodeled"))
    return rows


def evaluate_kpis(graph, report: dict[str, Any], contract: JudgementContract | None,
                  jobs_evaluated: bool) -> list[dict[str, Any]] | None:
    """``report.kpis`` rows of the declared KPIs, or None when nothing is declared. Job KPIs are judged only when
    the run evaluated the jobs (``jobs_evaluated``; steady-only callers skip them)."""
    targets = select_targets(contract.targets, graph.variant) if contract is not None and contract.targets else []
    rows: list[dict[str, Any]] = []
    declared = list(dict.fromkeys(contract.kpis)) if contract is not None else []
    for kpi in declared:
        if kpi not in JOB_KPIS:
            rows += _scenario_rows(kpi, report, targets)
    if jobs_evaluated and not report.get("jobs_error"):
        specs = {str(j.get("id")): j for j in (getattr(graph.scenario, "pipeline", None) or {}).get("jobs") or []
                 if isinstance(j, dict)}
        scenario_job_kpis = [k for k in declared if k in JOB_KPIS]
        for job in report.get("jobs") or []:
            kpis = list(dict.fromkeys([*((specs.get(job["id"]) or {}).get("kpis") or []), *scenario_job_kpis]))
            rows += _job_rows(job, [k for k in kpis if k in JOB_KPIS], targets)
    return rows or None


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """``verdict.kpis``: the worst status and the count per status."""
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUS_ORDER}
    worst = next(s for s in STATUS_ORDER if counts[s])
    return {"status": worst, **{s: n for s, n in counts.items() if n}}


def describe(row: dict[str, Any]) -> str:
    """The KPI's name in verdict text: target id, else kpi[.metric][ job][ milestone]."""
    name = row["kpi"] + (f".{row['metric']}" if row.get("metric") else "")
    where = " ".join(x for x in (row.get("job"), row.get("milestone")) if x)
    return (row["id"] or name) + (f" ({where})" if where and row["id"] is None else "")


def fail_reason(row: dict[str, Any]) -> str:
    op = ">" if row["bound"] == "max" else "<"
    tag = " (가정 목표)" if row.get("value_source") == "assumed" else ""
    return f"KPI {describe(row)}: {row['value']:g} {row['unit']} {op} {row['target']:g} {row['unit']}{tag}"
