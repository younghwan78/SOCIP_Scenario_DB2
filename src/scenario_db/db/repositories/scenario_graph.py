from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from scenario_db.db.models.capability import IpCatalog, SocPlatform, SwProfile
from scenario_db.db.models.decision import GateRule, Issue, Review, Waiver
from scenario_db.db.models.definition import Project, Scenario
from scenario_db.db.models.evidence import Evidence
from scenario_db.db.repositories.variant_resolution import ResolvedScenarioVariant, resolve_variant


@dataclass(slots=True)
class CanonicalScenarioGraph:
    """DB-backed aggregate used by resolver, gate, API, and view projection."""

    scenario: Scenario
    variant: ResolvedScenarioVariant
    project: Project | None = None
    soc: SocPlatform | None = None
    ip_catalog: dict[str, IpCatalog] = field(default_factory=dict)
    sw_profiles: dict[str, SwProfile] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    waivers: list[Waiver] = field(default_factory=list)
    reviews: list[Review] = field(default_factory=list)
    gate_rules: list[GateRule] = field(default_factory=list)

    @property
    def scenario_id(self) -> str:
        return self.scenario.id

    @property
    def variant_id(self) -> str:
        return self.variant.id

    @property
    def pipeline_nodes(self) -> list[dict[str, Any]]:
        return _effective_pipeline(self.scenario.pipeline or {}, self.variant)[0]

    @property
    def pipeline_edges(self) -> list[dict[str, Any]]:
        return _effective_pipeline(self.scenario.pipeline or {}, self.variant)[1]

    @property
    def has_topology_overlay(self) -> bool:
        routing = self.variant.routing_switch or {}
        patch = self.variant.topology_patch or {}
        return bool(
            routing.get("disabled_nodes")
            or routing.get("disabled_edges")
            or patch.get("remove_edges")
            or patch.get("add_nodes")
            or patch.get("add_edges")
        )

    def ip_ref_for_node(self, node_id: str) -> str | None:
        for node in self.pipeline_nodes:
            if node.get("id") == node_id:
                return node.get("ip_ref")
        return None


def load_canonical_graph(
    db: Session,
    scenario_id: str,
    variant_id: str,
) -> CanonicalScenarioGraph:
    scenario = db.query(Scenario).filter_by(id=scenario_id).one_or_none()
    if scenario is None:
        raise LookupError(f"Scenario not found: {scenario_id}")

    variant = resolve_variant(db, scenario_id, variant_id)
    if variant is None:
        raise LookupError(f"Variant not found: {scenario_id}/{variant_id}")

    project = db.query(Project).filter_by(id=scenario.project_ref).one_or_none()
    soc = None
    if project is not None:
        globals_ = project.globals_ or {}
        metadata = project.metadata_ or {}
        soc_ref = metadata.get("soc_ref") or globals_.get("soc_ref")
        if soc_ref:
            soc = db.query(SocPlatform).filter_by(id=soc_ref).one_or_none()

    effective_nodes, _ = _effective_pipeline(scenario.pipeline or {}, variant)
    ip_refs = {
        node.get("ip_ref")
        for node in effective_nodes
        if node.get("ip_ref")
    }
    ip_catalog = {
        row.id: row
        for row in db.query(IpCatalog).filter(IpCatalog.id.in_(ip_refs)).all()
    } if ip_refs else {}

    evidence = (
        db.query(Evidence)
        .filter_by(scenario_ref=scenario_id, variant_ref=variant_id)
        .all()
    )
    sw_refs = {
        ev.sw_baseline_ref
        for ev in evidence
        if ev.sw_baseline_ref
    }
    sw_profiles = {
        row.id: row
        for row in db.query(SwProfile).filter(SwProfile.id.in_(sw_refs)).all()
    } if sw_refs else {}

    issues = db.query(Issue).all()
    waivers = db.query(Waiver).all()
    reviews = (
        db.query(Review)
        .filter_by(scenario_ref=scenario_id, variant_ref=variant_id)
        .all()
    )
    gate_rules = db.query(GateRule).all()

    return CanonicalScenarioGraph(
        scenario=scenario,
        variant=variant,
        project=project,
        soc=soc,
        ip_catalog=ip_catalog,
        sw_profiles=sw_profiles,
        evidence=evidence,
        issues=issues,
        waivers=waivers,
        reviews=reviews,
        gate_rules=gate_rules,
    )


def _effective_pipeline(
    pipeline: dict[str, Any],
    variant: ResolvedScenarioVariant,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [deepcopy(node) for node in pipeline.get("nodes") or []]
    edges = [deepcopy(edge) for edge in pipeline.get("edges") or []]

    routing_switch = getattr(variant, "routing_switch", None) or {}
    topology_patch = getattr(variant, "topology_patch", None) or {}
    disabled_nodes = set((routing_switch or {}).get("disabled_nodes") or [])
    remove_specs = [
        *((routing_switch or {}).get("disabled_edges") or []),
        *((topology_patch or {}).get("remove_edges") or []),
    ]

    patch = topology_patch or {}
    for add_node in patch.get("add_nodes") or []:
        if not isinstance(add_node, dict):
            continue
        node_id = add_node.get("id")
        if not node_id or node_id in disabled_nodes:
            continue
        if not any(node.get("id") == node_id for node in nodes):
            nodes.append(deepcopy(add_node))

    valid_node_ids = {node.get("id") for node in nodes if node.get("id") not in disabled_nodes}
    nodes = [node for node in nodes if node.get("id") in valid_node_ids]

    edges = [
        edge
        for edge in edges
        if not _edge_removed(edge, remove_specs)
        and _edge_source(edge) in valid_node_ids
        and _edge_target(edge) in valid_node_ids
    ]

    existing_keys = {_edge_key(edge) for edge in edges}
    for add_edge in patch.get("add_edges") or []:
        if not isinstance(add_edge, dict):
            continue
        source = _edge_source(add_edge)
        target = _edge_target(add_edge)
        if source not in valid_node_ids or target not in valid_node_ids:
            continue
        normalized = deepcopy(add_edge)
        if "source" in normalized and "from" not in normalized:
            normalized["from"] = normalized.pop("source")
        if "target" in normalized and "to" not in normalized:
            normalized["to"] = normalized.pop("target")
        key = _edge_key(normalized)
        if key not in existing_keys:
            edges.append(normalized)
            existing_keys.add(key)

    return nodes, edges


def _edge_removed(edge: dict[str, Any], remove_specs: list[Any]) -> bool:
    return any(isinstance(spec, dict) and _edge_matches(edge, spec) for spec in remove_specs)


def _edge_matches(edge: dict[str, Any], spec: dict[str, Any]) -> bool:
    spec_id = spec.get("id")
    if spec_id and spec_id == edge.get("id"):
        return True
    return _edge_source(edge) == _edge_source(spec) and _edge_target(edge) == _edge_target(spec)


def _edge_key(edge: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    return (edge.get("id"), _edge_source(edge), _edge_target(edge), edge.get("type"))


def _edge_source(edge: dict[str, Any]) -> Any:
    return edge.get("from") if edge.get("from") is not None else edge.get("source")


def _edge_target(edge: dict[str, Any]) -> Any:
    return edge.get("to") if edge.get("to") is not None else edge.get("target")
