"""Library views over reference inputs that are not first-class tables yet."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from scenario_db.api.services.calibration import is_synthetic
from scenario_db.db.models.definition import ScenarioVariant
from scenario_db.db.models.evidence import Evidence


def sw_timing(db: Session, *, scenario_id: str | None = None) -> dict[str, Any]:
    """Per-variant SW task timing assumptions (node_configs.sw_timing) and measured task timing."""
    q = db.query(ScenarioVariant)
    if scenario_id:
        q = q.filter(ScenarioVariant.scenario_id == scenario_id)
    tasks: dict[tuple[str, str], dict[str, Any]] = {}
    for v in q.order_by(ScenarioVariant.scenario_id, ScenarioVariant.id).all():
        cond = v.design_conditions or {}
        for node, cfg in (v.node_configs or {}).items():
            st = (cfg or {}).get("sw_timing") if isinstance(cfg, dict) else None
            if not isinstance(st, dict):
                continue
            key = (v.scenario_id, str(node))
            row = tasks.setdefault(key, {
                "scenario_id": v.scenario_id, "task": str(node), "variants": 0,
                "min_ms": [], "mean_ms": [], "max_ms": [], "latency_ms": [],
                "value_source": set(), "sw_timing_source": set(), "bitrate_scaled": False,
            })
            row["variants"] += 1
            for k in ("min_ms", "mean_ms", "max_ms"):
                if st.get(k) is not None:
                    row[k].append(float(st[k]))
            lat = st.get("start_latency_mean_ms", st.get("start_jitter_mean_ms"))
            if lat is not None:
                row["latency_ms"].append(float(lat))
            if st.get("value_source"):
                row["value_source"].add(str(st["value_source"]))
            if cond.get("sw_timing_source"):
                row["sw_timing_source"].add(str(cond["sw_timing_source"]))
            if (cfg or {}).get("sw_bitrate_scaling"):
                row["bitrate_scaled"] = True

    def rng(xs: list[float]) -> list[float] | None:
        return [round(min(xs), 3), round(max(xs), 3)] if xs else None

    rows = []
    for r in tasks.values():
        rows.append({
            "scenario_id": r["scenario_id"], "task": r["task"], "variants": r["variants"],
            "min_ms": rng(r["min_ms"]), "mean_ms": rng(r["mean_ms"]), "max_ms": rng(r["max_ms"]),
            "latency_ms": rng(r["latency_ms"]),
            "source": sorted(r["value_source"] | r["sw_timing_source"]) or ["unspecified"],
            "bitrate_scaled": r["bitrate_scaled"],
        })
    measured = []
    mq = db.query(Evidence).filter(Evidence.kind == "evidence.measurement")
    if scenario_id:
        mq = mq.filter(Evidence.scenario_ref == scenario_id)
    for m in mq.all():
        for t in m.sw_task_timing or []:
            if isinstance(t, dict) and t.get("task"):
                measured.append({"evidence_id": m.id, "scenario_id": m.scenario_ref, "variant_id": m.variant_ref,
                                 "synthetic": is_synthetic(m.provenance), "count": t.get("samples", t.get("count")),
                                 **{k: t.get(k) for k in ("task", "mean_ms", "p95_ms", "max_ms", "count") if k in t}})
    return {"tasks": sorted(rows, key=lambda r: (r["scenario_id"], r["task"])), "measured": measured}
