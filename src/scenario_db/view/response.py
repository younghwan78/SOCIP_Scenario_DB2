"""Shared ViewResponse assembly for view projections."""
from __future__ import annotations

from typing import Any

from scenario_db.api.schemas.view import EdgeElement, NodeElement, RiskCard, ViewResponse, ViewSummary
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.review_gate.engine import run_review_gate
from scenario_db.view.graph_utils import resolution_to_size
from scenario_db.view.level0_v2 import build_resource_overview


def build_view_response(
    graph: CanonicalScenarioGraph,
    level: int,
    mode: str,
    nodes: list[NodeElement],
    edges: list[EdgeElement],
    metadata: dict[str, Any],
) -> ViewResponse:
    enriched_metadata = dict(metadata)
    enriched_metadata["variant_overlay"] = variant_overlay_metadata(graph)
    return ViewResponse(
        level=level,
        mode=mode,
        scenario_id=graph.scenario_id,
        variant_id=graph.variant_id,
        nodes=nodes,
        edges=edges,
        risks=risk_cards(graph),
        summary=summary(graph),
        metadata=enriched_metadata,
        overlays_available=["issues", "review-gate", "memory-path", "llc-allocation", "compression"],
        level0_resource_overview=build_resource_overview(graph) if level == 0 else None,
    )


def variant_overlay_metadata(graph: CanonicalScenarioGraph) -> dict[str, Any]:
    routing = getattr(graph.variant, "routing_switch", None) or {}
    topology_patch = getattr(graph.variant, "topology_patch", None) or {}
    node_configs = getattr(graph.variant, "node_configs", None) or {}
    buffer_overrides = getattr(graph.variant, "buffer_overrides", None) or {}
    return {
        "resolved": bool(getattr(graph.variant, "resolved", True)),
        "inheritance_chain": list(getattr(graph.variant, "inheritance_chain", None) or []),
        "disabled_nodes": list(routing.get("disabled_nodes") or []),
        "disabled_edge_count": len(routing.get("disabled_edges") or []),
        "topology_patch": {
            "add_nodes": len(topology_patch.get("add_nodes") or []),
            "add_edges": len(topology_patch.get("add_edges") or []),
            "remove_edges": len(topology_patch.get("remove_edges") or []),
        },
        "node_config_count": len(node_configs),
        "buffer_override_count": len(buffer_overrides),
        "sw_task_count": sum(
            1
            for config in node_configs.values()
            if isinstance(config, dict)
            and (config.get("kind") == "sw_task" or config.get("processor"))
        ),
    }


def summary(graph: CanonicalScenarioGraph) -> ViewSummary:
    metadata = graph.scenario.metadata_ or {}
    design = graph.variant.design_conditions or {}
    size_profile = graph.scenario.size_profile or {}
    anchors = size_profile.get("anchors") or {}
    size_overrides = getattr(graph.variant, "size_overrides", None) or {}
    fps = int(design.get("fps") or 30)
    period_ms = round(1000 / fps, 2) if fps else 0.0
    resolution = (
        size_overrides.get("record_out")
        or resolution_to_size(design.get("resolution"))
        or anchors.get("record_out")
        or str(design.get("resolution", "unknown"))
    )
    subtitle = f"{design.get('resolution', resolution)} {fps}fps"
    if design.get("codec"):
        subtitle = f"{subtitle}, {design['codec']}"
    return ViewSummary(
        scenario_id=graph.scenario_id,
        variant_id=graph.variant_id,
        name=metadata.get("name") or graph.scenario_id,
        subtitle=subtitle,
        period_ms=period_ms,
        budget_ms=round(period_ms * 0.9, 2) if period_ms else 0.0,
        resolution=str(resolution).replace("x", " x "),
        fps=fps,
        variant_label=graph.soc.id if graph.soc else graph.scenario.project_ref,
        notes=latest_evidence_note(graph),
        captured_at=latest_evidence_timestamp(graph),
    )


def risk_cards(graph: CanonicalScenarioGraph) -> list[RiskCard]:
    gate = run_review_gate(graph)
    cards: list[RiskCard] = []
    for idx, issue in enumerate(gate.matched_issues, start=1):
        cards.append(
            RiskCard(
                id=f"R{idx}",
                title=issue.title,
                component=", ".join(issue_components(graph, issue.issue_id)) or issue.issue_id,
                description=f"Matched by {issue.matched_by}. Status: {issue.status or 'unknown'}",
                severity=severity_to_card(issue.severity),
                impact="Known Issue",
            )
        )
    for rule in gate.matched_rules:
        if rule.status == "PASS":
            continue
        cards.append(
            RiskCard(
                id=f"R{len(cards) + 1}",
                title=f"{rule.status}: {rule.rule_id}",
                component="Review Gate",
                description=rule.message or rule.rule_id,
                severity="High" if rule.status == "BLOCK" else "Medium",
                impact="Gate Result",
            )
        )
    return cards


def issue_components(graph: CanonicalScenarioGraph, issue_id: str) -> list[str]:
    for issue in graph.issues:
        if issue.id == issue_id:
            return [item.get("submodule") or item.get("ip_ref") for item in issue.affects_ip or [] if item]
    return []


def latest_evidence_note(graph: CanonicalScenarioGraph) -> str | None:
    if not graph.evidence:
        return None
    evidence = graph.evidence[-1]
    run = getattr(evidence, "run", None) or {}
    tool = run.get("tool")
    source = run.get("source")
    if tool or source:
        return f"Latest evidence: {tool or 'unknown'} / {source or 'unknown'}"
    return None


def latest_evidence_timestamp(graph: CanonicalScenarioGraph) -> str | None:
    if not graph.evidence:
        return None
    run = getattr(graph.evidence[-1], "run", None) or {}
    return run.get("timestamp")


def severity_to_card(severity: str | None) -> str:
    if severity in {"critical", "heavy", "high"}:
        return "High"
    if severity in {"medium", "moderate"}:
        return "Medium"
    return "Low"
