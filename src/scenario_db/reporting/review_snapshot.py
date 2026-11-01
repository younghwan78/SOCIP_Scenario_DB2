"""Data-only review evidence and pure assembly behind ``build_snapshot``.

Database readers collect facts without constructing a partial snapshot. The report
builder owns the order: evidence, criteria, verdicts, risks, then final conclusion.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from scenario_db.reporting.review_verdict import power_verdicts
from scenario_db.reporting.risk_rules import build_risks
from scenario_db.sim.timing_budget import DERIVED_VARIANT_MARKERS


@dataclass
class ProjectEvidence:
    project_ref: str
    metadata: dict[str, Any] = field(default_factory=dict)
    globals: dict[str, Any] = field(default_factory=dict)
    scenarios: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)
    variants: list[tuple[str, str, str | None]] = field(default_factory=list)
    measurements: list[tuple[str, str, str]] = field(default_factory=list)
    model: dict[str, Any] = field(default_factory=dict)
    cpu: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ReviewEvidence:
    scope: dict[str, Any]
    context: dict[str, Any]
    references: dict[str, Any]
    calibration: list[dict[str, Any]] = field(default_factory=list)
    clock_residency: list[dict[str, Any]] = field(default_factory=list)
    thermal: dict[str, Any] = field(default_factory=lambda: {"items": [], "reason": "과제 범위 없음"})
    option_states: dict[tuple[str, str, str], str] = field(default_factory=dict)
    project: ProjectEvidence | None = None


def _assemble_review(snapshot: dict[str, Any], predictions: dict[tuple[str, str], dict[str, Any]],
                     evidence: ReviewEvidence) -> dict[str, Any]:
    """Internal assembly step; only the completed report leaves ``build_snapshot``."""
    snapshot = deepcopy(snapshot)
    evidence = deepcopy(evidence)
    o, s = snapshot["overview"], snapshot["spec_summary"]
    ctx, refs = evidence.context, evidence.references
    policy = ctx.get("policy") or {}
    snapshot["review_context"] = ctx
    snapshot["scope"] = evidence.scope
    if evidence.clock_residency:
        snapshot["clock_residency"] = evidence.clock_residency
    snapshot["basis"] = {
        "throughput_model": policy.get("throughput_model") or "stage",
        "policy_declared": bool(policy.get("declared")),
        "register_baseline": policy.get("register_baseline"),
        "dvfs_table_ref": o.get("dvfs_table_ref"), "sample_dvfs": o.get("sample_dvfs"),
        "engine_rev": o.get("engine_rev"),
        # every engine and model lineage the rows came from (a previous-report diff names model changes)
        "engines": sorted((o.get("engines") or {}).keys()) or None,
        "model_lineages": _lineage_labels(snapshot.get("scenarios") or []),
    }
    pred_vids = {vid for _, vid in predictions}
    ref_vids = sorted(refs["references"])
    missing = [v for v in ref_vids if v not in pred_vids]
    snapshot["reference_check"] = {"total": len(ref_vids), "missing": missing}
    judged = [r for r in ctx.get("rows") or [] if r.get("reference")]
    status = [r["reference"]["status"] for r in judged]
    snapshot["thermal"] = _thermal(evidence.thermal)

    def reach(item: dict[str, Any], pct: int) -> bool | None:
        plan = next((p for p in item["plans"] if p["ask_pct"] == pct), None)
        return None if plan is None else bool(plan["achieved"])

    snapshot["criteria"] = {
        "fps": {"ok": s.get("spec_ok", 0), "total": s.get("explored", 0),
                "fail": [f["variant_id"] for f in s.get("failed") or []],
                "basis": snapshot["basis"]["throughput_model"]},
        "power": {"total": len(ref_vids), "ok": status.count("ok"), "similar": status.count("similar"),
                  "over": status.count("over"), "missing": missing, "tolerance_pct": refs.get("tolerance_pct"),
                  "sample": any(r.get("source") == "explicit" for r in refs["references"].values())},
        "thermal": {"items": [{"variant_id": i["variant_id"], "reach10": reach(i, 10), "reach20": reach(i, 20)}
                              for i in snapshot["thermal"]["items"]],
                    "unassessed": sum(1 for i in snapshot["thermal"]["items"] if i.get("current_mw") is None)},
    }
    snapshot["references"] = refs["references"]
    _option_reviews(snapshot, evidence.option_states)
    if evidence.project is not None:
        project = evidence.project
        m = project.model
        snapshot["model"] = {
            "coverage": m["coverage"], "offsetting": m["offsetting"], "flat_cpu": m["flat_cpu"],
            "confidence": m["confidence"],
            "bias": {c: {k: b.get(k) for k in ("n", "median", "same_sign_pct", "within10", "verdict", "label")}
                     for c, b in m["bias"].items()},
            "rail_bias": [{k: b.get(k) for k in ("key", "label", "category", "n", "median", "same_sign_pct", "within10",
                                               "verdict", "label_verdict", "median_meas_mw", "median_abs_delta_mw")}
                          for b in m.get("rail_bias") or []],
            "latency_bias": {k: (m.get("latency_bias") or {}).get(k) for k in ("n", "median", "within10", "verdict", "label")},
        }
        snapshot["cpu"] = [{k: c[k] for k in ("id", "scenario_id", "variant_id", "profile_ref", "power_params_ref",
                                             "base_power_params_ref", "note", "created_by", "created_at", "summary")}
                           # calc_current False = recorded by an older sweep calculation (flagged, numbers kept)
                           | {k: c.get(k) for k in ("calc_rev", "calc_current")}
                           for c in project.cpu]
        snapshot["project_conditions"] = _project_conditions(snapshot, refs, project)
        snapshot["coverage"] = _coverage(snapshot, predictions, refs, project)
    verdicts = power_verdicts(snapshot)
    if verdicts:
        states = [v["state"] for v in verdicts]
        snapshot["criteria"]["power"] |= {
            "ok": states.count("ok"), "similar": states.count("similar"), "over": states.count("over"),
            "conditional": states.count("conditional"),
            "missing": [v["variant_id"] for v in verdicts if v["state"] in ("na", "uncovered")],
            "unregistered": [v["variant_id"] for v in verdicts
                             if v["state"] not in ("na", "uncovered") and not v["registered"]],
            "flip": [v["variant_id"] for v in verdicts if v.get("flip")], "basis": "verdict",
        }
    snapshot["risks"] = build_risks(snapshot)
    return snapshot


def _lineage_labels(rows: list[dict[str, Any]]) -> list[str] | None:
    """Model lineages of the registered rows, most used first (None: rows from before lineages were frozen)."""
    from scenario_db.sim.model_lineage import lineage_label

    counts: dict[str, int] = {}
    for r in rows:
        if "model_lineage" in r and r.get("prediction_id"):
            label = lineage_label(r.get("model_lineage"))
            counts[label] = counts.get(label, 0) + 1
    return [k for k, _ in sorted(counts.items(), key=lambda kv: -kv[1])] or None


def _thermal(thermal: dict[str, Any]) -> dict[str, Any]:
    if not thermal.get("items") and "reason" in thermal:
        return {"items": [], "reason": thermal["reason"]}
    return {"items": [{
        "scenario_id": i.get("scenario_id"), "variant_id": i["variant_id"], "label": i.get("label"),
        "current_mw": i.get("current_mw"), "baseline": i.get("baseline"), "reference": i.get("reference"),
        "plans": [{k: p.get(k) for k in ("ask_pct", "need_mw", "saving_mw", "achieved", "picked", "iq_pending")}
                  for p in i.get("plans") or []],
        "approved_plans": [{k: p.get(k) for k in ("ask_pct", "need_mw", "saving_mw", "achieved", "picked")}
                           for p in i.get("approved_plans") or []],
        "registered": i.get("prediction_id") is not None, "notes": (i.get("notes") or [])[:3],
    } for i in thermal.get("items") or []]}


def _option_reviews(snapshot: dict[str, Any], states: dict[tuple[str, str, str], str]) -> None:
    for option in snapshot.get("power_options") or []:
        sid, vid = option["scenario_id"], option["variant_id"]
        if option.get("best"):
            option["best"]["review_status"] = states.get((sid, vid, option["best"]["key"]), "candidate")
        for item in option.get("singles") or []:
            item["review_status"] = states.get((sid, vid, item["key"]), "candidate")


def _project_conditions(snapshot: dict[str, Any], refs: dict[str, Any], project: ProjectEvidence) -> dict[str, Any]:
    md, gl = project.metadata, project.globals
    ctx = snapshot["review_context"]
    policy = ctx.get("policy") or {}
    sw_src: dict[str, int] = {}
    for r in snapshot.get("scenarios") or []:
        key = str((r.get("inputs") or {}).get("sw_timing_source") or "미기록")
        sw_src[key] = sw_src.get(key, 0) + 1
    ref_src: dict[str, int] = {}
    for r in refs.get("references", {}).values():
        ref_src[str(r.get("source"))] = ref_src.get(str(r.get("source")), 0) + 1
    o = snapshot["overview"]
    soc = md.get("soc_ref") or o.get("target_soc")
    name = str(soc or "").removeprefix("soc-")
    return {
        "project_ref": project.project_ref, "project_name": md.get("name"), "soc_ref": soc,
        "soc_name": name[:1].upper() + name[1:] if name else "—",
        "board_type": md.get("board_type"), "board_name": md.get("board_name"),
        "sensor_module_ref": md.get("sensor_module_ref"), "display_module_ref": md.get("display_module_ref"),
        "sw_profile_ref": md.get("default_sw_profile_ref") or gl.get("default_sw_profile_ref"),
        "dvfs_table_ref": o.get("dvfs_table_ref"), "sample_dvfs": bool(o.get("sample_dvfs")),
        "sw_timing_source": sw_src, "sw_growth": ((o.get("objective") or {}).get("runtime_scale") or 1.0),
        "sw_growth_budget": policy.get("sw_growth_budget"),
        "reference": {"project_ref": (policy.get("power_reference") or {}).get("project_ref"), "sources": ref_src,
                      "tolerance_pct": refs.get("tolerance_pct"),
                      "note": (policy.get("power_reference") or {}).get("source_note"),
                      "priority": refs.get("source_priority")},
        "throughput_model": policy.get("throughput_model") or "stage", "register_baseline": policy.get("register_baseline"),
        "battery": ctx.get("battery"),
    }


def _coverage(snapshot: dict[str, Any], predictions: dict[tuple[str, str], dict[str, Any]],
              refs: dict[str, Any], project: ProjectEvidence) -> dict[str, Any]:
    measured: dict[tuple[str, str], str] = {}
    for sid, vid, origin in project.measurements:
        measured[(sid, vid)] = "physical" if origin == "physical_capture" or measured.get((sid, vid)) == "physical" else "synthetic"
    explored = {(r["scenario_id"], r["variant_id"]) for r in snapshot.get("scenarios") or []}
    ref_vids = set(refs.get("references") or {})
    rows: list[dict[str, Any]] = []
    for sid, md in project.scenarios:
        variants = [(v, d) for s, v, d in project.variants if s == sid]
        products = [v for v, derived in variants if not derived and not any(m in v for m in DERIVED_VARIANT_MARKERS)]
        keys = [(sid, v) for v in products]
        rows.append({
            "scenario_id": sid, "name": (md or {}).get("name") or sid, "variants": len(products),
            "derived": len(variants) - len(products), "explored": sum(k in explored for k in keys),
            "registered": sum(k in predictions for k in keys), "measured": sum(k in measured for k in keys),
            "measured_physical": sum(measured.get(k) == "physical" for k in keys),
            "measured_no_prediction": sum(k in measured and k not in predictions for k in keys),
            "reference": sum(v in ref_vids for v in products),
        })
    totals = {k: sum(r[k] for r in rows) for k in ("variants", "derived", "explored", "registered", "measured",
                                                 "measured_physical", "measured_no_prediction", "reference")}
    return {"rows": rows, "total": totals}
