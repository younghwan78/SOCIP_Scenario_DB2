"""Runtime graph, resolver, and review-gate API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db
from scenario_db.db.repositories.scenario_graph import load_canonical_graph
from scenario_db.resolver.engine import resolve_graph
from scenario_db.resolver.models import ResolverResult
from scenario_db.review_gate.engine import run_review_gate
from scenario_db.review_gate.models import GateExecutionResult

router = APIRouter(tags=["runtime"])


@router.get(
    "/scenarios/{scenario_id}/variants/{variant_id}/graph",
    summary="Canonical scenario graph summary",
)
def get_canonical_graph_summary(
    scenario_id: str,
    variant_id: str,
    db: Session = Depends(get_db),
) -> dict:
    graph = _load_graph_or_404(db, scenario_id, variant_id)
    return {
        "scenario_id": graph.scenario_id,
        "variant_id": graph.variant_id,
        "project_ref": graph.scenario.project_ref,
        "soc_ref": graph.soc.id if graph.soc else None,
        "node_count": len(graph.pipeline_nodes),
        "edge_count": len(graph.pipeline_edges),
        "ip_refs": sorted(graph.ip_catalog),
        "sw_profile_refs": sorted(graph.sw_profiles),
        "evidence_refs": [ev.id for ev in graph.evidence],
        "issue_refs": [issue.id for issue in graph.issues],
        "waiver_refs": [waiver.id for waiver in graph.waivers],
        "gate_rule_refs": [rule.id for rule in graph.gate_rules],
    }


@router.get(
    "/scenarios/{scenario_id}/variants/{variant_id}/resolve",
    response_model=ResolverResult,
    summary="Resolve variant requirements against capability catalog",
)
def get_resolver_result(
    scenario_id: str,
    variant_id: str,
    db: Session = Depends(get_db),
) -> ResolverResult:
    graph = _load_graph_or_404(db, scenario_id, variant_id)
    return resolve_graph(graph)


@router.get(
    "/scenarios/{scenario_id}/variants/{variant_id}/gate",
    response_model=GateExecutionResult,
    summary="Run review gate for a scenario variant",
)
def get_review_gate_result(
    scenario_id: str,
    variant_id: str,
    db: Session = Depends(get_db),
) -> GateExecutionResult:
    graph = _load_graph_or_404(db, scenario_id, variant_id)
    resolver = resolve_graph(graph)
    return run_review_gate(graph, resolver)


def _load_graph_or_404(db: Session, scenario_id: str, variant_id: str):
    try:
        return load_canonical_graph(db, scenario_id, variant_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
