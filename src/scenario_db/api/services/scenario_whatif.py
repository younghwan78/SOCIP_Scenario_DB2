"""What-if planning, authoritative calculation, and private/shared frozen experiments."""
from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.orm import Session

from scenario_db.api.resource_limits import enforce_timeline_frame_limit
from scenario_db.api.schemas.scenario_whatif import WhatIfAskRequest, WhatIfExperimentRequest, WhatIfModelSettings, WhatIfPlanRequest, WhatIfPreviewRequest, WhatIfScope
from scenario_db.api.schemas.timing_budget import TimingBudgetRequest
from scenario_db.api.services.review_policy import apply_throughput, scenario_policy
from scenario_db.api.services.timing_budget import _load, _shim
from scenario_db.api.services.whatif_conditions import apply_whatif_changes, whatif_targets
from scenario_db.api.services.whatif_llm import LlmUnavailable, interpret as llm_interpret, llm_status
from scenario_db.api.services.whatif_query import plan_query
from scenario_db.db.models.definition import Project, Scenario
from scenario_db.db.models.whatif import WhatIfExperiment
from scenario_db.db.repositories.scenario_graph import load_canonical_graph
from scenario_db.config import get_settings
from scenario_db.exceptions import ConflictError, NotFoundError, UnprocessableError
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.measured_timing import baseline_fingerprint
from scenario_db.sim.service import _apply_config_profile, _enforce_input_limits
from scenario_db.sim.timing_budget import _stage_slack, analyze_timing_budget

ENGINE_REV = "scenario-whatif/1"


def _guard(graph, scope: WhatIfScope) -> None:
    """SoC-agnostic: any project whose Timing Budget evaluates can run What-if (see whatif_targets capability)."""
    if graph.scenario.project_ref != scope.project_ref:
        raise UnprocessableError("What-if project does not own the selected scenario")


def _graph(db: Session, scope: WhatIfScope):
    try:
        graph = load_canonical_graph(db, scope.scenario_id, scope.variant_id)
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    _guard(graph, scope)
    return graph


def _planning_inputs(db: Session, scope: WhatIfScope, settings: WhatIfModelSettings | None = None):
    settings = settings or WhatIfModelSettings(**scope.model_dump())
    req = TimingBudgetRequest(scenario_id=scope.scenario_id, variant_id=scope.variant_id,
                              config=settings.config.model_copy(deep=True), options=settings.options.model_copy(deep=True))
    shim = _shim(req, req.variant_id)
    _apply_config_profile(db, shim)
    WhatIfModelSettings(**scope.model_dump(), config=shim.config, options=req.options)
    return req, shim


ASK_KINDS = [{"ask": "what_if", "label": "조건 바꿔보기", "description": "DVFS level · IP clock · 크기 · FPS를 바꾸면 timing · 전력 · BW가 어떻게 되나"},
             {"ask": "search_limit", "label": "어디까지 낮출 수 있나", "description": "DVFS domain level을 한 단계씩 낮추며 timing을 충족하는 최저 level 탐색"},
             {"ask": "diagnose", "label": "병목 찾기", "description": "기준 조건에서 가장 빠듯한 구간 · IP와 domain별 여유"}]


def _baseline(db: Session, scope: WhatIfScope, settings: WhatIfModelSettings | None = None) -> dict[str, Any]:
    """One baseline Timing Budget run with the same inputs as preview's baseline case."""
    req, shim = _planning_inputs(db, scope, settings)
    enforce_timeline_frame_limit(max(req.options.frames, req.options.timeline_frames + 4,
                                    shim.config.timeline_frame_count), get_settings().simulation_max_timeline_frames)
    graph, tables, ref = _load(db, shim, True)
    _guard(graph, scope)
    options = apply_throughput(req.options, scenario_policy(db, scope.scenario_id))
    return {"graph": graph, "config": shim.config, "tables": tables, "ref": ref, "options": options,
            "case": _case(graph, shim.config, options, tables, ref)}


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
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
    return {**scope.model_dump(), "baseline_hash": baseline_fingerprint(graph), **out,
            "soc_ref": out["capability"]["soc_ref"], "asks": ASK_KINDS, "llm": llm_status()}


def _baseline_clocks(db: Session, scope: WhatIfScope, settings: WhatIfModelSettings | None = None) -> dict[str, float]:
    """Set clock per IP in the baseline timing budget (same inputs as preview's baseline case)."""
    report = _baseline(db, scope, settings)["case"]["report"]
    return {row["node"]: float(row["set_clock_mhz"]) for row in report["ips"] if row.get("set_clock_mhz")}


def _resolve_relative_clocks(db: Session, scope: WhatIfScope, out: dict, settings: WhatIfModelSettings | None = None) -> None:
    """Relative IP clocks ("20% 낮추면") -> MHz against the baseline set clock, in changes and in choices."""
    pending = [c for c in out["changes"] if "scale" in c] + [
        ch["change"] for cl in out["clarifications"] for ch in cl["choices"] if ch.get("change") and "scale" in ch["change"]]
    if not pending:
        return
    try:
        clocks = _baseline_clocks(db, scope, settings)
    except (LookupError, ValueError) as exc:
        clocks, reason = {}, str(exc)
    else:
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
    _resolve_relative_clocks(db, scope, out, request)
    return {**out, "baseline_hash": available["baseline_hash"], "scope": scope.model_dump()}


def _case(graph, config, options, tables, ref):
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
    coverage = {"complete": not missing and not excluded, "scope": "modeled CPU + IP + memory",
                "missing_components": missing, "excluded_components": excluded, "cpu_model": "flat",
                "assumptions": ["Per-frame SW runtime remains the baseline assumption; no measured extrapolation",
                                "Existing stream bitrate stays fixed", "Sensor mode and input dimensions stay fixed",
                                "FPS changes are hypothetical cadence; selected sensor mode support is not validated",
                                "Model calculation does not validate IQ or wiring compatibility"]}
    metrics = {"modeled_power_mw": p["total_mw"], "total_power_mw": p["total_mw"] if coverage["complete"] else None,
               "cpu_power_mw": p["cpu_mw"], "ip_power_mw": p["hw_mw"], "memory_power_mw": p["bw_mw"],
               "bw_mbs": report["bw"]["total_mbs"], "fps": report["fps"], "period_ms": report["period_ms"],
               "feasible": report["verdict"]["status"] != "fail"}
    return {"report": report, "metrics": metrics, "coverage": coverage}


def preview(db: Session, request: WhatIfPreviewRequest) -> dict:
    req = TimingBudgetRequest(scenario_id=request.scenario_id, variant_id=request.variant_id,
                              config=request.config.model_copy(deep=True), options=request.options.model_copy(deep=True))
    shim = _shim(req, req.variant_id)
    try:
        _apply_config_profile(db, shim)
        # An active basis can fill restricted inputs after the original request was validated.
        WhatIfPreviewRequest.model_validate(
            {**request.model_dump(), "config": shim.config.model_dump()})
        graph, tables, ref = _load(db, shim, True)
        _guard(graph, request)
        baseline_hash = baseline_fingerprint(graph)
        if baseline_hash != request.expected_baseline_hash:
            raise ConflictError("What-if baseline changed; interpret and preview the condition again")
        options = apply_throughput(req.options, scenario_policy(db, request.scenario_id))
        before = _case(graph, shim.config, options, tables, ref)
        candidate, config, changes = apply_whatif_changes(graph, request.changes, shim.config,
                                                          _domains(before["report"], tables))
        after = _case(candidate, config, options, tables, ref)
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
    scope = request.model_dump(include={"project_ref", "scenario_id", "variant_id"})
    normalized = {"scope": scope, "changes": changes, "config": config.model_dump(mode="json"),
                  "options": options.model_dump(mode="json")}
    hash_payload = {"baseline": baseline_hash, "condition": normalized, "engine": ENGINE_REV,
                    "tables": {k: t.model_dump(mode="json") for k, t in tables.items()},
                    "baseline_config": shim.config.model_dump(mode="json"),
                    "baseline_inputs": build_simulation_inputs(graph, shim.config).model_dump(mode="json"),
                    "candidate_inputs": build_simulation_inputs(candidate, config).model_dump(mode="json"),
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
    return {"persisted": False, "baseline_hash": baseline_hash, "condition_hash": condition_hash,
            "normalized_condition": normalized, "baseline": before, "candidate": after,
            "delta": {"metrics": metrics_delta, "ips": ips}, "warnings": warnings,
            "model_lineage": {"engine": "timing-budget", "engine_rev": ENGINE_REV,
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
    if "width" in change:
        return f"{change.get('anchor_id') or change.get('node_id') or change.get('stream_id') or t} {change['width']}x{change['height']}"
    return f"{change.get('node_id') or ''} {change.get('param') or t} {change.get('value')}".strip()


def _search_limit(base: dict, domains: list[dict], ids: list[str]) -> list[dict[str, Any]]:
    """Lower each domain one OPP level at a time until timing fails (the engine verdict decides)."""
    graph, config, options, tables, ref = base["graph"], base["config"], base["options"], base["tables"], base["ref"]
    base_mw = base["case"]["metrics"]["modeled_power_mw"]
    out = []
    for d in [d for d in domains if not ids or d["id"] in ids]:
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


def _answer(plan: dict, targets: dict, result, search, diag, boundaries: list[str]) -> dict[str, Any] | None:
    actions: list[dict[str, Any]] = []
    if result is not None:
        b, c = result["baseline"], result["candidate"]
        desc = " · ".join(_change_text(ch, targets) for ch in result["normalized_condition"]["changes"])
        _, s1, n1 = _min_slack(c["report"])
        _, s0, n0 = _min_slack(b["report"])
        bm, cm = b["metrics"], c["metrics"]
        if cm["feasible"]:
            verdict, headline = "ok", f"가능 — {desc}: timing 충족, 최소 여유 {n1} {s1:.2f} ms (기준 {n0} {s0:.2f} ms)"
        else:
            verdict = "fail"
            headline = f"불가 — {desc}: {(c['report']['verdict']['reasons'] or ['timing 미달'])[0]}"
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
        base_clock = {ip["node"]: ip["set_clock_mhz"] for ip in b["report"]["ips"]}
        domains = {d["id"]: d for d in targets.get("domains") or []}
        for ch in result["normalized_condition"]["changes"]:
            if ch["target"] == "node_clock_mhz" and ch["value"] < (base_clock.get(ch["node_id"]) or 0):
                dom = next((ip.get("dvfs_group") for ip in b["report"]["ips"] if ip["node"] == ch["node_id"]), None)
                facts.append(f"{ch['node_id']}: clock 하한 {ch['value']:g} MHz < 현재 {base_clock[ch['node_id']]:g} MHz — 하한이라 적용 clock은 그대로"
                             + (f" (낮추려면 DVFS level 조건: {dom})" if dom else ""))
            if ch["target"] == "dvfs_level" and ch["domain"] in domains and domains[ch["domain"]]["level"] == ch["level"]:
                facts.append(f"{ch['domain']}는 기준과 같은 level(L{ch['level']})입니다")
        for ch in result["normalized_condition"]["changes"]:
            if ch["target"] == "dvfs_level" and cm["feasible"]:
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
        headline = (f"{'timing 충족' if ok else 'timing 미달'} — 가장 빠듯한 구간 {t['name']}, 여유 {t['slack_ms']:.2f} ms"
                    if t else ("timing 충족" if ok else "timing 미달"))
        facts = _diag_facts(diag)[1:] + [f"미달: {r}" for r in diag["reasons"][:3]]
        facts += [f"{d['id']} L{d['level']} ({d['mhz']:g} MHz): " + ("최저 OPP" if d["down"] == 0 else f"{d['down']}단계 낮출 여지")
                  + f" · {', '.join(d['ips'])}" for d in diag["domains"]]
        actions = [{"label": f"{d['id']} 어디까지 낮출 수 있나", "ask": "search_limit", "search_domains": [d["id"]]}
                   for d in diag["domains"] if d["down"] > 0]
        if boundaries:   # nothing to change (already at the OPP edge): say so, then the current state
            return {"verdict": "boundary", "headline": boundaries[0], "facts": boundaries[1:] + [f"현재 {headline}"] + facts,
                    "actions": actions}
        return {"verdict": "ok" if ok else "fail", "headline": headline, "facts": facts, "actions": actions}
    return None


def ask(db: Session, request: WhatIfAskRequest) -> dict:
    scope = WhatIfScope(**request.model_dump(include={"project_ref", "scenario_id", "variant_id"}))
    try:
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
            got = llm_interpret(request.query, targets_)
        except LlmUnavailable as exc:
            return {**common, "interpretation": {"status": "llm_unavailable", "reason": str(exc), **llm_status()},
                    "plan": None, "answer": None, "result": None, "search": None, "diagnose": None}
        boundaries = got["boundaries"]
        plan_ = {k: got[k] for k in ("ask", "changes", "search_domains", "focus")}
        runnable = plan_["ask"] != "what_if" or bool(plan_["changes"])
        status = ("clarification" if got["clarification"] else "ready" if runnable
                  else "boundary" if boundaries else "unsupported")
        interpretation = {"status": status, **got["meta"], "clarification": got["clarification"], "ignored": got["ignored"],
                          "notes": got["notes"], "boundaries": boundaries}
        if status in ("clarification", "unsupported"):
            return {**common, "interpretation": interpretation, "plan": plan_, "answer": None,
                    "result": None, "search": None, "diagnose": None}
    result = search = diag = None
    if plan_["ask"] == "search_limit":
        search = _search_limit(base, targets_["domains"], plan_["search_domains"])
    elif plan_["ask"] == "diagnose" or not plan_["changes"]:
        if plan_["ask"] == "what_if" and not boundaries:
            raise UnprocessableError("바꿀 조건을 하나 이상 지정하세요")
        diag = _diagnose(base, targets_["domains"])
    else:
        result = preview(db, WhatIfPreviewRequest(**scope.model_dump(), config=request.config, options=request.options,
                                                  changes=plan_["changes"], expected_baseline_hash=baseline_hash))
    return {**common, "interpretation": interpretation, "plan": plan_,
            "answer": _answer(plan_, targets_, result, search, diag, boundaries),
            "result": result, "search": search, "diagnose": diag}


def _record(row, *, detail=False):
    keys = ("id", "project_ref", "title", "purpose", "description", "assumptions", "conclusion", "query",
            "visibility", "created_by", "baseline_hash", "condition_hash")
    out = {key: getattr(row, key) for key in keys}
    out.update(scenario_id=row.scenario_ref, variant_id=row.variant_ref,
               created_at=row.created_at.isoformat() if row.created_at else None)
    if detail:
        out.update(preview_request=row.preview_request, normalized_condition=row.normalized_condition, result=row.result)
    else:
        out["metrics"] = (row.result or {}).get("candidate", {}).get("metrics", {})
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
                          preview_request=scope.model_dump(mode="json"),
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
    rows = query.order_by(WhatIfExperiment.created_at.desc(), WhatIfExperiment.id).offset(offset).limit(limit).all()
    return {"items": [_record(row) for row in rows], "total": total, "limit": limit,
            "offset": offset, "has_next": offset + limit < total}


def get_experiment(db: Session, experiment_id: str, subject: str):
    row: Any = db.query(WhatIfExperiment).filter(WhatIfExperiment.id == experiment_id,
              or_(WhatIfExperiment.visibility == "shared", WhatIfExperiment.created_by == subject)).one_or_none()
    if row is None:
        raise NotFoundError("What-if experiment not found")
    _list_scope(db, row.project_ref, row.scenario_ref)
    return _record(row, detail=True)
