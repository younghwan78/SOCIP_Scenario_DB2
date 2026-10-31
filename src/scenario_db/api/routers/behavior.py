"""Which scenario variants have Behavior data (full-stack timeline and / or sdb.handoff/1 flows)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db
from scenario_db.db.models.evidence import Evidence

router = APIRouter(tags=["behavior"])

# full-stack events carry a layer (app … hw); pipeline / simulation events do not
_LAYER_KEY = '%"layer":%'


def behavior_index(rows: list[Any]) -> list[dict[str, Any]]:
    """One entry per (scenario, variant): the newest evidence with Behavior data and what it holds."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for r in sorted(rows, key=lambda r: (str(r.measured_at or ""), r.id), reverse=True):
        events = r.timeline_events or []
        full_stack = any(isinstance(e, dict) and e.get("layer") for e in events)
        flows = (r.handoff_flows or {}).get("flows") or []
        if not full_stack and not flows:
            continue
        key = (r.scenario_ref, r.variant_ref)
        entry = out.setdefault(key, {"scenario_ref": r.scenario_ref, "variant_ref": r.variant_ref, "evidence_ids": [],
                                     "full_stack": False, "flows": 0})
        entry["evidence_ids"].append(r.id)
        entry["full_stack"] = entry["full_stack"] or full_stack
        entry["flows"] = max(entry["flows"], len(flows))
    return sorted(out.values(), key=lambda e: (e["scenario_ref"], e["variant_ref"]))


def index_filter():
    """Rows worth reading: a hand-off document (a JSON object — an absent one may be stored as JSON ``null``,
    which is not SQL NULL) or layered (full-stack) timeline events."""
    return or_(func.jsonb_typeof(Evidence.handoff_flows) == "object",
               cast(Evidence.timeline_events, String).like(_LAYER_KEY))


@router.get("/behavior/index")
def get_behavior_index(project_ref: str | None = Query(None), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Variants with a full-stack trace or a hand-off flow document (Scenario page filter, Behavior links)."""
    q = db.query(Evidence.id, Evidence.scenario_ref, Evidence.variant_ref, Evidence.measured_at,
                 Evidence.timeline_events, Evidence.handoff_flows).filter(
        Evidence.kind == "evidence.measurement",
        index_filter(),
    )
    if project_ref:
        q = q.filter(Evidence.project_ref == project_ref)
    return behavior_index(q.all())
