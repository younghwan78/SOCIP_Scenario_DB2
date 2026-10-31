"""What-if planning, authoritative calculation, and private/shared frozen experiments."""
from __future__ import annotations

import hashlib
import json
import logging
from time import perf_counter
from contextlib import nullcontext
from typing import Any
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.orm import Session

from scenario_db.api.resource_limits import enforce_timeline_frame_limit
from scenario_db.api.schemas.scenario_whatif import WhatIfAskRequest, WhatIfExperimentRequest, WhatIfModelSettings, WhatIfPlanRequest, WhatIfPreviewRequest, WhatIfScope
from scenario_db.api.schemas.timing_budget import TimingBudgetRequest
from scenario_db.api.services.review_policy import apply_throughput, scenario_policy
from scenario_db.api.services.analysis_inputs import resolve_analysis_selection
from scenario_db.api.services.compute_session import release_read_connection
from scenario_db.api.services.whatif_conditions import CHANGE_KINDS, apply_whatif_changes, change_iq, whatif_targets
from scenario_db.api.services.whatif_llm import LlmUnavailable, interpret as llm_interpret, llm_status
from scenario_db.api.services.whatif_query import plan_query
from scenario_db.db.models.definition import Project, Scenario
from scenario_db.db.models.whatif import WhatIfExperiment
from scenario_db.config import get_settings
from scenario_db.exceptions import ConflictError, NotFoundError, UnprocessableError
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.measured_timing import baseline_fingerprint
from scenario_db.sim.service import _enforce_input_limits
from scenario_db.sim.timing_budget import _stage_slack, analyze_timing_budget

ENGINE_REV = "scenario-whatif/4"  # 4: v2-vf clock term uses the work clock; 3: SBWC mean ratio = typical in the engine baseline
_log = logging.getLogger("scenario_db.api.analysis")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _analysis_identity(graph, config, options, tables, ref):
    return _digest({"graph": baseline_fingerprint(graph), "power_options": graph.scenario.power_options,
                    "config": config.model_dump(mode="json"),
                    "options": options.model_dump(mode="json"), "engine": ENGINE_REV, "ref": ref,
                    "tables": {k: t.model_dump(mode="json") for k, t in tables.items()}})


def _guard(graph, scope: WhatIfScope) -> None:
    """SoC-agnostic: any project whose Timing Budget evaluates can run What-if (see whatif_targets capability)."""
    if graph.scenario.project_ref != scope.project_ref:
        raise UnprocessableError("What-if project does not own the selected scenario")


ASK_KINDS = [{"ask": "what_if", "label": "조건 바꿔보기", "description": "센서 · crop/downscale · L0 skip · previous DMA 빈도 · 출력 크기 · DVFS level · IP mode · SBWC를 바꾸면 timing · 전력 · BW가 어떻게 되나"},
             {"ask": "combine", "label": "레버 조합 비교", "description": "고른 레버를 각각 · 함께(또는 모든 조합) 적용해 전력 차이와 fps 충족 여부를 한 표로 비교"},
             {"ask": "search_limit", "label": "어디까지 낮출 수 있나", "description": "DVFS domain level을 한 단계씩 낮추며 timing을 충족하는 최저 level 탐색"},
             {"ask": "diagnose", "label": "병목 찾기", "description": "기준 조건에서 가장 빠듯한 구간 · IP와 domain별 여유"}]


def _baseline(db: Session, scope: WhatIfScope, settings: WhatIfModelSettings | None = None,
              *, preview: WhatIfPreviewRequest | None = None) -> dict[str, Any]:
    """Prepare and evaluate one request-local baseline; no cross-request cache.

    ``preview`` keeps the standalone preview contract: the resolved config is validated
    as that preview request, the timeline frame limit is not applied (it is checked when
    targets are discovered), and the expected baseline hash must still match.
    """
    settings = preview or settings or WhatIfModelSettings(**scope.model_dump())
    started = perf_counter()
    req = TimingBudgetRequest(scenario_id=scope.scenario_id, variant_id=scope.variant_id, basis_ref=settings.basis_ref,
                              config=settings.config.model_copy(deep=True), options=settings.options.model_copy(deep=True))
    selection = resolve_analysis_selection(db, req)
    config = selection.request.config
    # Active model defaults can fill restricted inputs after request validation.
    if preview is not None:
        WhatIfPreviewRequest.model_validate({**preview.model_dump(), "config": config.model_dump()})
    else:
        WhatIfModelSettings(**scope.model_dump(include={"project_ref", "scenario_id", "variant_id"}),
                            config=config, options=req.options)
        enforce_timeline_frame_limit(max(req.options.frames, req.options.timeline_frames + 4,
                                        config.timeline_frame_count), get_settings().simulation_max_timeline_frames)
    inputs = selection.load(db)
    graph, tables, ref = inputs.graph, inputs.tables, inputs.dvfs_table_ref
    _guard(graph, scope)
    expected = getattr(settings, "expected_baseline_hash", None)
    if expected is not None and baseline_fingerprint(graph) != expected:
        raise ConflictError("What-if baseline changed; interpret and preview the condition again")
    options = apply_throughput(req.options, scenario_policy(db, scope.scenario_id))
    from scenario_db.api.services.timing_budget import _basis_fields
    # Keep basis identity visible; the calculation already follows this selection.
    basis = _basis_fields(db, selection.request)
    identity = _analysis_identity(graph, config, options, tables, ref)
    expected_analysis = getattr(settings, "expected_analysis_hash", None)
    if expected_analysis is not None and identity != expected_analysis:
        raise ConflictError("What-if model settings changed; refresh the baseline before calculating")
    release_read_connection(db)
    def prepare_candidate(candidate, candidate_config):
        from scenario_db.api.services.whatif_sensors import prepare_sensor_graph
        try:
            return prepare_sensor_graph(db, candidate, candidate_config)
        finally:
            release_read_connection(db)
    if get_settings().performance_log_enabled:
        _log.info("analysis phase=prepare wall_ms=%.3f", (perf_counter() - started) * 1000)
    return {"graph": graph, "config": config, "tables": tables, "ref": ref, "options": options,
            "analysis_hash": identity, "lineage": {**basis, "config_profile_ref": selection.config_profile_ref},
            "prepare_candidate": prepare_candidate, "case": _case(graph, config, options, tables, ref)}


def _domains(report: dict, tables: dict) -> list[dict[str, Any]]:
    """DVFS domains of this variant: resolved level / clock, member IPs and the OPP ladder (slow -> fast)."""
    rows: dict[str, dict[str, Any]] = {}
    for ip in report.get("ips") or []:
        g = ip.get("dvfs_group")
        if not g or g not in tables or ip.get("dvfs_level") is None:
            continue
        d = rows.setdefault(g, {"id": g, "level": ip["dvfs_level"], "mhz": ip["set_clock_mhz"], "ips": [], "stages": set()})
        if ip["set_clock_mhz"] > d["mhz"]:   # a shared domain runs at its fastest member's level
            d["level"], d["mhz"] = ip["dvfs_level"], ip["set_clock_mhz"]
        d["ips"].append(ip["node"])
        d["stages"].add(ip["stage"])
    out = []
    for g, d in sorted(rows.items()):
        ladder = [{"level": lv.level, "mhz": lv.speed_mhz} for lv in sorted(tables[g].levels, key=lambda lv: lv.speed_mhz)]
        index = next((i for i, lv in enumerate(ladder) if lv["level"] == d["level"]), None)
        if index is None:
            continue
        out.append({**d, "stages": sorted(d["stages"]), "ladder": ladder, "index": index})
    return out


def _apply_targets(base: dict[str, Any], config, domains: list[dict] | None) -> dict[str, Any]:
    """Lever targets of the baseline graph for this config, computed once per baseline (combine / sweep cases)."""
    cache = base.setdefault("apply_targets", {})
    key = _digest([config.model_dump(mode="json"), domains])
    if key not in cache:
        cache[key] = whatif_targets(base["graph"], config, domains)
    return cache[key]


def _targets_from(base: dict[str, Any]) -> dict[str, Any]:
    report = base["case"]["report"]
    out = whatif_targets(base["graph"], base["config"], _domains(report, base["tables"]))
    by_node = {row["node"]: row for row in report["ips"]}
    for node in out["nodes"]:
        row = by_node.get(node["id"]) or {}
        node["clock_mhz"] = row.get("set_clock_mhz")
        node["dvfs_group"] = row.get("dvfs_group")
    return out


def targets(db: Session, scope: WhatIfScope, settings: WhatIfModelSettings | None = None) -> dict:
    try:
        base = _baseline(db, scope, settings)
        graph, out = base["graph"], _targets_from(base)
        from scenario_db.api.services.whatif_sensors import catalog_binding_targets
        out["sensor_bindings"] = catalog_binding_targets(db, graph, out.get("fps"))
        kinds = [kind.meta(out) for kind in CHANGE_KINDS.values()]
        out["change_kinds"] = [kind for kind in kinds if kind["choices"] or kind["target"] == "fps" and out.get("fps")]
        out["supported_changes"] = [kind["target"] for kind in out["change_kinds"]]
        release_read_connection(db)
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
    return {**scope.model_dump(), "baseline_hash": baseline_fingerprint(graph), **out,
            "analysis_hash": base.get("analysis_hash"),
            "baseline": {k: base["case"][k] for k in ("metrics", "coverage")},
            "model_lineage": {**base.get("lineage", {}), "engine_rev": ENGINE_REV,
                              "power_params_ref": base["config"].power_params_ref, "dvfs_table_ref": base["ref"]},
            "jobs": {"supported": True, "max_cases": 256},
            "soc_ref": out["capability"]["soc_ref"], "asks": ASK_KINDS, "llm": llm_status()}


def _resolve_relative_clocks(out: dict, available: dict) -> None:
    """Resolve legacy relative clocks from the target catalog's existing baseline."""
    pending = [c for c in out["changes"] if "scale" in c] + [
        ch["change"] for cl in out["clarifications"] for ch in cl["choices"] if ch.get("change") and "scale" in ch["change"]]
    if not pending:
        return
    clocks = {node["id"]: float(node["clock_mhz"]) for node in available["nodes"] if node.get("clock_mhz")}
    reason = "기준 clock 없음"
    noted: set[str] = set()
    for change in pending:
        base = clocks.get(change["node_id"])
        scale = change.pop("scale")
        if base is None:
            change["unresolved"] = f"{change['node_id']} 기준 clock을 구하지 못했습니다 ({reason})"
            continue
        value = round(base * scale, 1)
        if not 0 < value <= 5000:
            change["unresolved"] = f"{change['node_id']} 상대 clock {value:g} MHz: 0보다 크고 5000 MHz 이하여야 합니다"
            continue
        change["value"] = value
        if change in out["changes"] and change["node_id"] not in noted:
            noted.add(change["node_id"])
            out["notes"].append(f"{change['node_id']} 기준 적용 clock {base:g} MHz × {scale:g} = {change['value']:g} MHz (수동 하한)")
    bad = [c for c in out["changes"] if c.get("unresolved")]
    if bad:
        for change in bad:
            out["ignored"].append({"text": change.pop("unresolved"), "reason": "상대 clock을 MHz로 바꾸지 못했습니다",
                                   "hint": "MHz 값으로 직접 지정"})
        keep = [i for i, c in enumerate(out["changes"]) if "value" in c or c["target"] != "node_clock_mhz"]
        out["changes"] = [out["changes"][i] for i in keep]
        out["sources"] = [out["sources"][i] for i in keep]
        if not out["changes"] and not out["clarifications"]:
            out["status"] = "unsupported"
        elif out["status"] == "ready":
            out["status"] = "partial"
    for cl in out["clarifications"]:
        cl["choices"] = [ch for ch in cl["choices"] if not (ch.get("change") or {}).get("unresolved")]
        for ch in cl["choices"]:
            change = ch.get("change") or {}
            if change.get("target") == "node_clock_mhz" and "value" in change and "MHz" not in ch["label"]:
                ch["label"] = f"{ch['label']} ({change['value']:g} MHz)"
        if not cl["choices"]:
            out["ignored"].append({"text": cl.get("source", cl["message"]),
                                   "reason": "유효한 상대 clock 조건이 없습니다", "hint": "MHz 값으로 직접 지정"})
    out["clarifications"] = [cl for cl in out["clarifications"] if cl["choices"]]
    if out["clarifications"]:
        out["status"] = "clarification"
    elif not out["changes"]:
        out["status"] = "unsupported"
    elif out["ignored"]:
        out["status"] = "partial"


def plan(db: Session, request: WhatIfPlanRequest) -> dict:
    scope = WhatIfScope(**request.model_dump(include={"project_ref", "scenario_id", "variant_id"}))
    available = targets(db, scope, request)
    out = plan_query(request.query, available)
    _resolve_relative_clocks(out, available)
    return {**out, "baseline_hash": available["baseline_hash"], "scope": scope.model_dump()}


def _case(graph, config, options, tables, ref):
    from scenario_db.api.services.analysis_cache import whatif_cases
    settings = get_settings()
    started = perf_counter()
    key = _analysis_identity(graph, config, options, tables, ref)
    result, cache = whatif_cases.get_or_compute(key, lambda: _calculate_case(graph, config, options, tables, ref),
        capacity=settings.whatif_case_cache_entries, ttl=settings.whatif_case_cache_ttl_seconds)
    if settings.performance_log_enabled:
        _log.info("analysis phase=case cache=%s wall_ms=%.3f", cache, (perf_counter() - started) * 1000)
    return result


def _calculate_case(graph, config, options, tables, ref):
    from scenario_db.api.services.whatif_sensors import sensor_power_coverage
    inputs = build_simulation_inputs(graph, config)
    _enforce_input_limits(inputs)
    report = analyze_timing_budget(graph, options, config=config, dvfs_tables=tables)
    report["dvfs"]["table_ref"] = ref
    missing = sorted({w.node_id for w in inputs.workloads
                      if w.sim_params.ppc <= 0 or w.sim_params.unit_power_mw_mp <= 0}
                     | {str(n["id"]) for n in graph.pipeline_nodes
                        if n.get("ip_ref") and n["ip_ref"] not in graph.ip_catalog})
    excluded = sorted({str(d.get("device_type") or "external_device") for d in inputs.external_devices})
    excluded.append("unmodeled SoC/display/device baseline and MIF DVFS")
    p = report["power"]
    sensor = sensor_power_coverage(graph, config.fps)
    # complete = every IP of the modeled scope (CPU + IP + memory) has a power/performance model; the excluded
    # components are the scope boundary, so a whole-device total (total_power_mw) is never reported here.
    coverage = {"complete": not missing, "scope": "modeled CPU + IP + memory",
                "missing_components": missing, "excluded_components": excluded, "cpu_model": "flat", "sensor": sensor,
                "assumptions": ["Per-frame SW runtime remains the baseline assumption; no measured extrapolation",
                                "Existing stream bitrate stays fixed", "Sensor mode and input dimensions change only through explicit conditions",
                                "FPS-only changes are hypothetical cadence; explicit sensor selections must support the final FPS",
                                "Model calculation does not validate IQ or wiring compatibility"]}
    metrics = {"modeled_power_mw": p["total_mw"], "total_power_mw": None,
               "sensor_power_mw": sensor["power_mw"],
               "modeled_plus_sensor_mw": p["total_mw"] + sensor["power_mw"] if sensor["power_mw"] is not None else None,
               "cpu_power_mw": p["cpu_mw"], "ip_power_mw": p["hw_mw"], "memory_power_mw": p["bw_mw"],
               "bw_mbs": report["bw"]["total_mbs"], "fps": report["fps"], "period_ms": report["period_ms"],
               "latency_ms": max((v for k, v in (report.get("latency") or {}).items()
                   if k.endswith("_ms") and isinstance(v, (int, float))), default=None),
               "feasible": report["verdict"]["status"] != "fail"}
    return {"report": report, "metrics": metrics, "coverage": coverage,
            "input_fingerprint": _digest(inputs.model_dump(mode="json"))}


def preview(db: Session, request: WhatIfPreviewRequest) -> dict:
    # A separate preview/save request always resolves today's inputs again.
    scope = WhatIfScope(**request.model_dump(include={"project_ref", "scenario_id", "variant_id"}))
    try:
        base = _baseline(db, scope, preview=request)
        return _preview_from(base, request)
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc


def _preview_from(base: dict, request: WhatIfPreviewRequest) -> dict:
    """Compare against the already evaluated baseline of this request."""
    graph, baseline_config = base["graph"], base["config"]
    tables, ref, options, before = base["tables"], base["ref"], base["options"], base["case"]
    baseline_hash = baseline_fingerprint(graph)
    lever_notes: list[str] = []
    candidate_config = baseline_config.model_copy(deep=True)
    if request.comparison == "fixed_opp":
        candidate_config.dvfs_overrides.update({d["id"]: d["level"] for d in _domains(before["report"], tables)})
        lever_notes.append("기준 OPP 고정: 후보의 부하 변화에 따른 DVFS 재선택을 제외합니다.")
    try:
        domains = _domains(before["report"], tables)
        candidate, config, changes = apply_whatif_changes(graph, request.changes, candidate_config, domains, lever_notes,
                                                          prepare_sensor=base.get("prepare_candidate"),
                                                          targets=_apply_targets(base, candidate_config, domains))
        after = _case(candidate, config, options, tables, ref)
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
    scope = request.model_dump(include={"project_ref", "scenario_id", "variant_id"})
    normalized = {"scope": scope, "changes": changes, "comparison": request.comparison, "config": config.model_dump(mode="json"),
                  "options": options.model_dump(mode="json")}
    hash_payload = {"baseline": baseline_hash, "condition": normalized, "engine": ENGINE_REV,
                    "tables": {k: t.model_dump(mode="json") for k, t in tables.items()},
                    "baseline_config": baseline_config.model_dump(mode="json"),
                    "baseline_inputs": before.get("input_fingerprint"),
                    "candidate_inputs": after.get("input_fingerprint"),
                    "resolved_candidate": baseline_fingerprint(candidate)}
    condition_hash = hashlib.sha256(json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    metrics_delta = {key: round(value - before["metrics"][key], 4)
                     for key, value in after["metrics"].items()
                     if isinstance(value, (int, float)) and not isinstance(value, bool)
                     and isinstance(before["metrics"][key], (int, float))}
    baseline_ips = {row["node"]: row for row in before["report"]["ips"]}
    ips = []
    for row in after["report"]["ips"]:
        old = baseline_ips.get(row["node"])
        if old is None:
            continue
        reason = row.get("set_reason") or "calculated"
        leader = row.get("domain_leader")
        ips.append({"node": row["node"], **{k: round(row[k] - old[k], 4) for k in
                    ("required_clock_mhz", "set_clock_mhz", "power_mw")},
                    "explanation": f"set clock: {reason}" + (f" ({leader} shared domain)" if leader else "")})
    warnings = sorted(set(before["report"]["warnings"] + after["report"]["warnings"] + [
        "Calculated model subtotal excludes missing/unmodeled device power; it is not measured whole-device power.",
        "Condition changes keep assumed SW runtime and stream bitrate fixed; review those assumptions before adoption."]))
    lever_targets = _apply_targets(base, candidate_config, domains)
    iq = sorted({c["target"] for c in changes if change_iq(c, lever_targets) != "neutral"})
    if iq:
        warnings.append(f"IQ evaluation required before adoption: {', '.join(iq)}")
    return {"persisted": False, "baseline_hash": baseline_hash, "condition_hash": condition_hash,
            "analysis_hash": base.get("analysis_hash"),
            "normalized_condition": normalized, "baseline": before, "candidate": after,
            "delta": {"metrics": metrics_delta, "ips": ips}, "warnings": warnings, "lever_notes": lever_notes, "iq_required": iq,
            "model_lineage": {**base.get("lineage", {}), "engine": "timing-budget", "engine_rev": ENGINE_REV,
                "power_model": config.power_model, "power_params_ref": config.power_params_ref,
                "dvfs_table_ref": ref, "cpu_model": "flat", "baseline_fingerprint": baseline_hash}}


# ---------------------------------------------------------------- ask: one question -> executed answer
def _min_slack(report: dict) -> tuple[str, float, str]:
    slack = _stage_slack(report)
    names = {st["id"]: st["name"] for st in report["stages"]}
    sid = min(slack, key=lambda k: slack[k])
    return sid, slack[sid], names.get(sid, sid)


def _change_text(change: dict, targets: dict) -> str:
    t = change["target"]
    if t == "dvfs_level":
        d = next((x for x in targets.get("domains") or [] if x["id"] == change["domain"]), None)
        lv = next((x for x in (d or {}).get("ladder", []) if x["level"] == change["level"]), None)
        return f"{change['domain']} L{d['level'] if d else '?'}→L{change['level']}" + (f" ({lv['mhz']:g} MHz)" if lv else "")
    if t == "node_clock_mhz":
        return f"{change['node_id']} clock 하한 {change['value']:g} MHz"
    if t == "fps":
        return f"FPS {change['value']:g}"
    if t == "sensor_mode":
        row: dict[str, Any] = next((r for r in targets.get("sensors") or [] if r["node_id"] == change["node_id"]), {})
        opt = next((o for o in row.get("options") or [] if o["id"] == change["option"]), None)
        return f"센서 → {opt['label'] if opt else change['option']}"
    if t == "sensor_binding":
        binding = change["sensor_binding"]
        return f"{change['node_id']} 센서 → {binding['catalog_ref']} / {binding['mode_label']}"
    if t == "chain_size":
        return f"{change['node_id']} crop/downscale → {change['width']}x{change['height']}"
    if t == "power_knob":
        knob: dict[str, Any] = next((r for r in targets.get("knobs") or [] if r["param"] == change["param"]), {})
        pick = next((o for o in knob.get("options") or [] if o["id"] == change["option"]), None)
        return pick["label"] if pick else f"{change['param']}={change['option']}"
    if t == "history_interval":
        return f"previous DMA {change.get('buffer_id') or '전체'} {change['value']:g} frame마다 1회"
    if t == "ip_mode":
        return f"{change['node_id']} mode → {change['option']}"
    if t == "compression":
        ratio = f" (ratio {change['value']:g})" if change.get("value") else ""
        return f"{change['buffer_id']} → {change['option']}{ratio}"
    if "width" in change:
        return f"{change.get('anchor_id') or change.get('node_id') or change.get('stream_id') or t} {change['width']}x{change['height']}"
    return f"{change.get('node_id') or ''} {change.get('param') or t} {change.get('value')}".strip()


def _search_limit(base: dict, domains: list[dict], ids: list[str]) -> list[dict[str, Any]]:
    """Lower each domain one OPP level at a time until timing fails (the engine verdict decides)."""
    unknown = set(ids) - {d["id"] for d in domains}
    if unknown:
        raise UnprocessableError(f"unknown search domains: {', '.join(sorted(unknown))}")
    selected = [d for d in domains if not ids or d["id"] in ids]
    if sum(d["index"] for d in selected) > get_settings().exploration_max_cases:
        raise UnprocessableError("What-if search exceeds the exploration case limit")
    graph, config, options, tables, ref = base["graph"], base["config"], base["options"], base["tables"], base["ref"]
    base_mw = base["case"]["metrics"]["modeled_power_mw"]
    out = []
    for d in selected:
        rows = []
        for j in range(d["index"] - 1, -1, -1):
            lv = d["ladder"][j]
            cfg = config.model_copy(update={"dvfs_overrides": {**config.dvfs_overrides, d["id"]: lv["level"]}})
            try:
                case = _case(graph, cfg, options, tables, ref)
            except ValueError as exc:
                rows.append({"level": lv["level"], "mhz": lv["mhz"], "feasible": False, "reason": str(exc)})
                break
            _, slack, stage = _min_slack(case["report"])
            m = case["metrics"]
            rows.append({"level": lv["level"], "mhz": lv["mhz"], "feasible": m["feasible"], "power_mw": m["modeled_power_mw"],
                         "delta_mw": round(m["modeled_power_mw"] - base_mw, 2), "min_slack_ms": slack, "tight_stage": stage,
                         "reason": None if m["feasible"] else ((case["report"]["verdict"]["reasons"] or ["timing 미달"])[0])})
            if not m["feasible"]:
                break
        ok = [r for r in rows if r["feasible"]]
        out.append({"domain": d["id"], "level": d["level"], "mhz": d["mhz"], "ips": d["ips"], "at_min": d["index"] == 0,
                    "rows": rows, "lowest": ok[-1] if ok else None, "first_fail": next((r for r in rows if not r["feasible"]), None)})
    return out


_DELTA = ("modeled_power_mw", "cpu_power_mw", "ip_power_mw", "memory_power_mw", "bw_mbs")
_IQ_ORDER = {"neutral": 0, "eval": 1, "trade": 2}


def _combine(base: dict, targets: dict, changes: list[dict], mode: str) -> dict[str, Any]:
    """Baseline + every lever alone + all together (``each``) or every subset (``factorial``) on one table."""
    from itertools import combinations
    n = len(changes)
    if not 2 <= n <= 8 or mode == "factorial" and n > 5:
        raise UnprocessableError("combine requires 2–8 levers; factorial supports at most 5")
    if mode == "factorial":
        subsets = [c for k in range(1, n + 1) for c in combinations(range(n), k)]
    else:
        subsets = [(i,) for i in range(n)] + [tuple(range(n))]
    if len(subsets) > get_settings().exploration_max_cases:
        raise UnprocessableError("What-if combination exceeds the exploration case limit")
    graph, config, options, tables, ref = base["graph"], base["config"], base["options"], base["tables"], base["ref"]
    b = base["case"]
    bm = b["metrics"]
    _, s0, n0 = _min_slack(b["report"])
    rows: list[dict[str, Any]] = [{"key": "baseline", "levers": [], "metrics": bm, "delta": {k: 0.0 for k in _DELTA},
                                   "feasible": bm["feasible"], "min_slack_ms": s0, "tight_stage": n0, "reason": None, "notes": []}]
    for sub in subsets:
        notes: list[str] = []
        try:
            cand, cfg, _ = apply_whatif_changes(graph, [changes[i] for i in sub], config, targets.get("domains"), notes,
                                               prepare_sensor=base.get("prepare_candidate"),
                                               targets=_apply_targets(base, config, targets.get("domains")))
            case = _case(cand, cfg, options, tables, ref)
        except ValueError as exc:
            rows.append({"key": "+".join(map(str, sub)), "levers": list(sub), "metrics": None, "delta": None,
                         "feasible": False, "min_slack_ms": None, "tight_stage": None, "reason": str(exc), "error": True, "notes": notes})
            continue
        m = case["metrics"]
        _, slack, stage = _min_slack(case["report"])
        rows.append({"key": "+".join(map(str, sub)), "levers": list(sub), "metrics": m,
                     "delta": {k: round(m[k] - bm[k], 3) for k in _DELTA}, "feasible": m["feasible"],
                     "min_slack_ms": slack, "tight_stage": stage, "notes": notes,
                     "reason": None if m["feasible"] else (case["report"]["verdict"]["reasons"] or ["timing 미달"])[0]})
    singles = {r["levers"][0]: r for r in rows if len(r["levers"]) == 1}
    together = next((r for r in rows if len(r["levers"]) == n), None)
    interaction = None
    if together and together["delta"] and all(singles.get(i, {}).get("delta") for i in range(n)):
        interaction = round(together["delta"]["modeled_power_mw"] - sum(singles[i]["delta"]["modeled_power_mw"] for i in range(n)), 3)
    levers = []
    for i, ch in enumerate(changes):
        kind = CHANGE_KINDS.get(ch["target"])
        iq_class = change_iq(ch, targets)
        levers.append({"index": i, "change": ch, "label": _change_text(ch, targets), "group": kind.group if kind else "other",
                       "iq": iq_class, "iq_required": iq_class != "neutral"})
    for r in rows:
        r["iq"] = max((levers[i]["iq"] for i in r["levers"]), key=_IQ_ORDER.__getitem__, default="neutral")
    ok = [r for r in rows[1:] if r["feasible"] and r["delta"] is not None]
    lowest = lambda pool: min(pool, key=lambda r: r["delta"]["modeled_power_mw"], default=None)  # noqa: E731
    best = lowest(ok)                                           # any IQ class (kept for older readers)
    keep = lowest([r for r in ok if r["iq"] == "neutral"])      # image quality kept: the recommendation
    gap = round(best["delta"]["modeled_power_mw"] - keep["delta"]["modeled_power_mw"], 3) if best and keep else None
    return {"mode": mode, "levers": levers, "rows": rows, "best": best["key"] if best else None,
            "best_keep": keep["key"] if keep else None, "best_trade": best["key"] if best and best is not keep else None,
            "trade_gain_mw": gap, "interaction_mw": interaction, "baseline_mw": bm["modeled_power_mw"]}


def _combine_answer(combo: dict) -> dict[str, Any]:
    rows, levers = combo["rows"], combo["levers"]
    base_mw = combo["baseline_mw"] or 0.0
    name = lambda r: " + ".join(f"#{i + 1}" for i in r["levers"])  # noqa: E731
    pct = lambda d: f"{d / base_mw * 100:+.1f}%" if base_mw else ""  # noqa: E731
    best = next((r for r in rows if r["key"] == combo["best"]), None)
    facts = [f"#{lv['index'] + 1} {lv['label']}" + (" · IQ 평가 필요" if lv["iq_required"] else "") for lv in levers]
    for r in rows[1:]:
        if len(r["levers"]) != 1:
            continue
        if r.get("error"):
            facts.append(f"{name(r)} 단독: 적용 불가 — {r['reason']}")
        else:
            facts.append(f"{name(r)} 단독: {r['delta']['modeled_power_mw']:+.1f} mW ({pct(r['delta']['modeled_power_mw'])}) · "
                         f"BW {r['delta']['bw_mbs']:+.0f} MB/s · {'fps 충족' if r['feasible'] else '미달: ' + str(r['reason'])}")
    all_row = next((r for r in rows if len(r["levers"]) == len(levers)), None)
    if all_row and all_row.get("delta"):
        facts.append(f"모두 적용: {all_row['delta']['modeled_power_mw']:+.1f} mW ({pct(all_row['delta']['modeled_power_mw'])}) · "
                     f"{'fps 충족' if all_row['feasible'] else '미달: ' + str(all_row['reason'])}"
                     + (f" · 단독 합과 차이 {combo['interaction_mw']:+.1f} mW (레버 간 상호작용 — 공유 DVFS domain · 같은 buffer)"
                        if combo.get("interaction_mw") is not None and abs(combo["interaction_mw"]) >= 0.5 else ""))
    if best is None:
        return {"verdict": "fail", "headline": "fps(처리량)를 충족하는 조합이 없습니다", "facts": facts, "actions": []}
    keep = next((r for r in rows if r["key"] == combo.get("best_keep")), None)
    trade = next((r for r in rows if r["key"] == combo.get("best_trade")), None)
    if trade is not None:
        facts.append(f"IQ trade 포함 최저: {name(trade)} — {trade['delta']['modeled_power_mw']:+.1f} mW"
                     + (f" (화질 유지 대비 추가 {combo['trade_gain_mw']:+.1f} mW)" if combo.get("trade_gain_mw") is not None else "")
                     + f" · {'lossy 화질 trade' if trade.get('iq') == 'trade' else 'IQ 평가 필요'}")
    pick = keep or best
    iq = pick.get("iq", "neutral") != "neutral"
    label = "fps 충족 · 화질 유지 최저 전력" if keep else "fps 충족 최저 전력 (화질 유지 조합 없음)"
    return {"verdict": "ok", "facts": facts, "actions": [],
            "headline": f"{label}: {name(pick)} — {pick['delta']['modeled_power_mw']:+.1f} mW ({pct(pick['delta']['modeled_power_mw'])})"
                        f" · 최소 여유 {pick['tight_stage']} {pick['min_slack_ms']:.2f} ms" + (" · IQ 평가 필요" if iq else "")}


def _diagnose(base: dict, domains: list[dict]) -> dict[str, Any]:
    report = base["case"]["report"]
    slack = _stage_slack(report)
    stages = {st["id"]: st for st in report["stages"]}
    rows = [{"id": sid, "name": stages[sid]["name"], "slack_ms": value, "fill_pct": stages[sid].get("fill_pct"),
             "hw_ms": stages[sid].get("hw_ms"), "sw_ms": stages[sid].get("sw_ms"), "budget_ms": stages[sid].get("budget_ms")}
            for sid, value in sorted(slack.items(), key=lambda kv: kv[1]) if sid in stages]
    tight = rows[0] if rows else None
    dom_of = {ip: d for d in domains for ip in d["ips"]}
    top = sorted([ip for ip in report["ips"] if tight and ip["stage"] == tight["id"] and ip.get("hw_ms") is not None],
                 key=lambda ip: -ip["hw_ms"])[:3]
    return {"verdict": report["verdict"]["status"], "reasons": report["verdict"]["reasons"][:5], "notes": report["verdict"]["notes"][:3],
            "period_ms": report["period_ms"], "stages": rows, "tight": tight,
            "top_ips": [{"node": ip["node"], "hw_ms": ip["hw_ms"], "set_clock_mhz": ip["set_clock_mhz"],
                         "required_clock_mhz": ip["required_clock_mhz"], "domain": (dom_of.get(ip["node"]) or {}).get("id"),
                         "level": ip.get("dvfs_level")} for ip in top],
            "domains": [{"id": d["id"], "level": d["level"], "mhz": d["mhz"], "down": d["index"], "up": len(d["ladder"]) - 1 - d["index"],
                         "ips": d["ips"]} for d in domains]}


def _diag_facts(diag: dict) -> list[str]:
    facts = []
    t = diag.get("tight")
    if t:
        facts.append(f"가장 빠듯한 구간 {t['name']}: 여유 {t['slack_ms']:.2f} ms (frame {diag['period_ms']:.2f} ms"
                     + (f", 사용 {t['fill_pct']:.0f}%" if t.get("fill_pct") is not None else "") + ")")
    for ip in diag["top_ips"]:
        dom = next((d for d in diag["domains"] if d["id"] == ip["domain"]), None)
        room = "" if dom is None else (" · 최저 OPP" if dom["down"] == 0 else f" · {dom['down']}단계 낮출 여지")
        facts.append(f"{ip['node']} HW {ip['hw_ms']:.2f} ms · {ip['set_clock_mhz']:g} MHz (필요 {ip['required_clock_mhz']:g})"
                     + (f" · {ip['domain']} L{ip['level']}" if ip.get("domain") else "") + room)
    return facts


def _answer(plan: dict, targets: dict, result, search, diag, boundaries: list[str], combo=None) -> dict[str, Any] | None:
    actions: list[dict[str, Any]] = []
    if combo is not None:
        out = _combine_answer(combo)
        out["facts"] = boundaries + out["facts"]
        return out
    if result is not None:
        b, c = result["baseline"], result["candidate"]
        desc = " · ".join(_change_text(ch, targets) for ch in result["normalized_condition"]["changes"])
        _, s1, n1 = _min_slack(c["report"])
        _, s0, n0 = _min_slack(b["report"])
        bm, cm = b["metrics"], c["metrics"]
        if cm["feasible"]:
            verdict, headline = "ok", f"{desc}: timing 충족, 최소 여유 {n1} {s1:.2f} ms (기준 {n0} {s0:.2f} ms)"
        else:
            verdict = "fail"
            headline = f"{desc}: {(c['report']['verdict']['reasons'] or ['timing 미달'])[0]}"
        dp = cm["modeled_power_mw"] - bm["modeled_power_mw"]
        facts = [f"모델 전력 {bm['modeled_power_mw']:.1f} → {cm['modeled_power_mw']:.1f} mW ({dp:+.1f} mW · IP {cm['ip_power_mw'] - bm['ip_power_mw']:+.1f}"
                 f" · 메모리 {cm['memory_power_mw'] - bm['memory_power_mw']:+.1f} · CPU {cm['cpu_power_mw'] - bm['cpu_power_mw']:+.1f})",
                 f"BW {bm['bw_mbs']:.0f} → {cm['bw_mbs']:.0f} MB/s ({cm['bw_mbs'] - bm['bw_mbs']:+.0f})"]
        moved = sorted([ip for ip in result["delta"]["ips"] if abs(ip["set_clock_mhz"]) >= 0.5], key=lambda ip: -abs(ip["set_clock_mhz"]))[:4]
        if moved:
            base_ips = {ip["node"]: ip for ip in b["report"]["ips"]}
            facts.append("적용 clock: " + " · ".join(f"{ip['node']} {base_ips[ip['node']]['set_clock_mhz']:g}→"
                                                     f"{base_ips[ip['node']]['set_clock_mhz'] + ip['set_clock_mhz']:g} MHz" for ip in moved))
        facts += [f"미달: {r}" for r in c["report"]["verdict"]["reasons"][1:4]]
        facts += result.get("lever_notes") or []
        if result.get("iq_required"):
            facts.append("IQ 평가 필요: " + ", ".join(CHANGE_KINDS[t].label if t in CHANGE_KINDS else t for t in result["iq_required"])
                         + " — 전력 이득은 화질 평가 후 채택")
        if len(result["normalized_condition"]["changes"]) >= 2:
            actions.append({"label": "레버별로 나눠 비교", "ask": "combine"})
        base_clock = {ip["node"]: ip["set_clock_mhz"] for ip in b["report"]["ips"]}
        domains = {d["id"]: d for d in targets.get("domains") or []}
        for ch in result["normalized_condition"]["changes"]:
            if ch["target"] == "node_clock_mhz" and ch["value"] < (base_clock.get(ch["node_id"]) or 0):
                dom = next((ip.get("dvfs_group") for ip in b["report"]["ips"] if ip["node"] == ch["node_id"]), None)
                facts.append(f"{ch['node_id']}: clock 하한 {ch['value']:g} MHz < 현재 {base_clock[ch['node_id']]:g} MHz — 하한이라 적용 clock은 그대로"
                             + (f" (낮추려면 DVFS level 조건: {dom})" if dom else ""))
            if ch["target"] == "dvfs_level" and ch["domain"] in domains and domains[ch["domain"]]["level"] == ch["level"]:
                facts.append(f"{ch['domain']}는 기준과 같은 level(L{ch['level']})입니다")
        for ch in result["normalized_condition"]["changes"]:   # the limit search starts from the baseline level
            if ch["target"] == "dvfs_level" and cm["feasible"] and (domains.get(ch["domain"]) or {}).get("index", 0) > 0:
                actions.append({"label": f"{ch['domain']} 어디까지 낮출 수 있나", "ask": "search_limit", "search_domains": [ch["domain"]]})
        return {"verdict": verdict, "headline": headline, "facts": boundaries + facts, "actions": actions}
    if search is not None:
        lines = []
        for row in search:
            cur = f"{row['domain']} (현재 L{row['level']}, {row['mhz']:g} MHz)"
            if row["at_min"]:
                lines.append(f"{cur}: 이미 최저 OPP — 더 낮출 수 없음")
            elif row["lowest"] is None:
                f = row["first_fail"] or {}
                lines.append(f"{cur}: 한 단계(L{f.get('level')}, {f.get('mhz', 0):g} MHz)만 낮춰도 미달 — {f.get('reason')}")
            else:
                low, f = row["lowest"], row["first_fail"]
                steps = len([r for r in row["rows"] if r["feasible"]])
                lines.append(f"{cur}: L{low['level']} ({low['mhz']:g} MHz)까지 {steps}단계 가능 · 전력 {low['delta_mw']:+.1f} mW · "
                             f"최소 여유 {low['tight_stage']} {low['min_slack_ms']:.2f} ms"
                             + (f" — L{f['level']}에서 미달: {f['reason']}" if f else " (최저 OPP까지 충족)"))
        if not lines:
            return {"verdict": "info", "headline": "이 variant에는 level을 바꿀 수 있는 DVFS domain이 없습니다", "facts": [], "actions": []}
        return {"verdict": "info", "headline": lines[0] if len(lines) == 1 else "domain별로 낮출 수 있는 한계",
                "facts": boundaries + (lines[1:] if len(lines) == 1 else lines), "actions": []}
    if diag is not None:
        t = diag["tight"]
        ok = diag["verdict"] != "fail"
        headline = (f"가장 빠듯한 구간 {t['name']} — 여유 {t['slack_ms']:.2f} ms (frame {diag['period_ms']:.2f} ms)"
                    if t else ("timing 충족" if ok else "timing 미달"))
        facts = _diag_facts(diag)[1:] + [f"미달: {r}" for r in diag["reasons"][:3]]
        facts += [f"{d['id']} L{d['level']} ({d['mhz']:g} MHz): " + ("최저 OPP" if d["down"] == 0 else f"{d['down']}단계 낮출 여지")
                  + f" · {', '.join(d['ips'])}" for d in diag["domains"]]
        actions = [{"label": f"{d['id']} 어디까지 낮출 수 있나", "ask": "search_limit", "search_domains": [d["id"]]}
                   for d in diag["domains"] if d["down"] > 0]
        if boundaries:   # nothing to change (already at the OPP edge): say so, then the current state
            return {"verdict": "boundary", "headline": boundaries[0],
                    "facts": boundaries[1:] + [f"현재 timing {'충족' if ok else '미달'} · {headline}"] + facts,
                    "actions": actions}
        return {"verdict": "ok" if ok else "fail", "headline": headline, "facts": facts, "actions": actions}
    return None


def ask(db: Session, request: WhatIfAskRequest, *, compute_slot=nullcontext, llm_slot=nullcontext) -> dict:
    scope = WhatIfScope(**request.model_dump(include={"project_ref", "scenario_id", "variant_id"}))
    try:
        with compute_slot():
            base = _baseline(db, scope, request)
            targets_ = _targets_from(base)
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
    baseline_hash = baseline_fingerprint(base["graph"])
    common = {"scope": scope.model_dump(), "baseline_hash": baseline_hash}
    interpretation = None
    boundaries: list[str] = []
    plan_: dict[str, Any] = {"ask": request.ask or "what_if", "changes": [c.model_dump(exclude_none=True) for c in request.changes or []],
             "search_domains": list(request.search_domains or []), "focus": []}
    if request.changes is None and request.ask is None:
        try:
            with llm_slot():
                got = llm_interpret(request.query, targets_)
        except LlmUnavailable as exc:
            return {**common, "interpretation": {"status": "llm_unavailable", "reason": str(exc), **llm_status()},
                    "plan": None, "answer": None, "result": None, "search": None, "diagnose": None, "combine": None}
        boundaries = got["boundaries"]
        plan_ = {k: got[k] for k in ("ask", "changes", "search_domains", "focus")}
        runnable = plan_["ask"] != "what_if" or bool(plan_["changes"])
        status = ("clarification" if got["clarification"] else "ready" if runnable
                  else "boundary" if boundaries else "unsupported")
        interpretation = {"status": status, **got["meta"], "clarification": got["clarification"], "ignored": got["ignored"],
                          "notes": got["notes"], "boundaries": boundaries}
        if status in ("clarification", "unsupported"):
            return {**common, "interpretation": interpretation, "plan": plan_, "answer": None,
                    "result": None, "search": None, "diagnose": None, "combine": None}
    with compute_slot():
        result = search = diag = combo = None
        if request.comparison == "fixed_opp" and (plan_["ask"] != "what_if" or any(
                c.get("target") == "dvfs_level" for c in plan_["changes"])):
            raise UnprocessableError("fixed_opp requires a candidate comparison without DVFS-level changes")
        if plan_["ask"] == "combine" and len(plan_["changes"]) < 2:
            plan_["ask"] = "what_if"   # a single lever (e.g. an LLM reading) is just a what-if
        if plan_["ask"] == "combine":
            try:
                combo = _combine(base, targets_, plan_["changes"], request.combine)
            except ValueError as exc:
                raise UnprocessableError(str(exc)) from exc
        elif plan_["ask"] == "search_limit":
            search = _search_limit(base, targets_["domains"], plan_["search_domains"])
        elif plan_["ask"] == "diagnose" or not plan_["changes"]:
            if plan_["ask"] == "what_if" and not boundaries:
                raise UnprocessableError("바꿀 조건을 하나 이상 지정하세요")
            diag = _diagnose(base, targets_["domains"])
        else:
            result = _preview_from(base, WhatIfPreviewRequest(**scope.model_dump(), basis_ref=request.basis_ref, comparison=request.comparison, config=request.config, options=request.options,
                                                      changes=plan_["changes"], expected_baseline_hash=baseline_hash))
        return {**common, "interpretation": interpretation, "plan": plan_,
                "answer": _answer(plan_, targets_, result, search, diag, boundaries, combo),
                "result": result, "search": search, "diagnose": diag, "combine": combo}


def _record(row, *, detail=False):
    keys = ("id", "project_ref", "title", "purpose", "description", "assumptions", "conclusion", "query",
            "visibility", "created_by", "baseline_hash", "condition_hash")
    out = {key: getattr(row, key) for key in keys}
    out.update(scenario_id=row.scenario_ref, variant_id=row.variant_ref,
               created_at=row.created_at.isoformat() if row.created_at else None)
    if detail:
        out.update(preview_request=row.preview_request, normalized_condition=row.normalized_condition, result=row.result)
    else:
        out["metrics"] = row.metrics if hasattr(row, "metrics") else (row.result or {}).get("candidate", {}).get("metrics", {})
    return out


def save_experiment(db: Session, request: WhatIfExperimentRequest, subject: str) -> dict:
    result = preview(db, request.preview_request)
    if result["condition_hash"] != request.expected_condition_hash:
        raise ConflictError("What-if calculation inputs changed; preview again before saving")
    scope = request.preview_request
    row = WhatIfExperiment(id=f"whatif-{uuid4().hex}", project_ref=scope.project_ref,
                          scenario_ref=scope.scenario_id, variant_ref=scope.variant_id,
                          title=request.title.strip(), purpose=request.purpose, description=request.description,
                          assumptions=request.assumptions, conclusion=request.conclusion, query=request.query,
                          visibility=request.visibility, created_by=subject,
                          baseline_hash=result["baseline_hash"], condition_hash=result["condition_hash"],
                          preview_request=scope.model_dump(mode="json", exclude_unset=True),
                          normalized_condition=result["normalized_condition"], result=result)
    if not row.title:
        raise UnprocessableError("experiment title cannot be blank")
    db.add(row)
    db.commit()
    db.refresh(row)
    return _record(row, detail=True)


def _list_scope(db: Session, project_ref: str, scenario_id: str | None = None):
    project: Any = db.get(Project, project_ref)
    if project is None:
        raise NotFoundError("What-if project not found")
    if scenario_id:
        scenario = db.get(Scenario, scenario_id)
        if scenario is None or scenario.project_ref != project_ref:
            raise NotFoundError("What-if scenario not found in selected project")


def list_experiments(db: Session, subject: str, project_ref: str, *, scenario_id: str | None = None,
                     variant_id: str | None = None, limit=30, offset=0):
    _list_scope(db, project_ref, scenario_id)
    query = db.query(WhatIfExperiment).filter(WhatIfExperiment.project_ref == project_ref,
                or_(WhatIfExperiment.visibility == "shared", WhatIfExperiment.created_by == subject))
    if scenario_id:
        query = query.filter(WhatIfExperiment.scenario_ref == scenario_id)
    if variant_id:
        query = query.filter(WhatIfExperiment.variant_ref == variant_id)
    total = query.count()
    columns = [c for c in WhatIfExperiment.__table__.columns
               if c.name not in {"preview_request", "normalized_condition", "result"}]
    rows = query.with_entities(*columns, WhatIfExperiment.result["candidate"]["metrics"].label("metrics")).order_by(
        WhatIfExperiment.created_at.desc(), WhatIfExperiment.id).offset(offset).limit(limit).all()
    return {"items": [_record(row) for row in rows], "total": total, "limit": limit,
            "offset": offset, "has_next": offset + limit < total}


def get_experiment(db: Session, experiment_id: str, subject: str):
    row: Any = db.query(WhatIfExperiment).filter(WhatIfExperiment.id == experiment_id,
              or_(WhatIfExperiment.visibility == "shared", WhatIfExperiment.created_by == subject)).one_or_none()
    if row is None:
        raise NotFoundError("What-if experiment not found")
    _list_scope(db, row.project_ref, row.scenario_ref)
    return _record(row, detail=True)
