from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from scenario_db.db.models.capability import IpCatalog, SocPlatform, SwProfile
from scenario_db.db.models.decision import GateRule, Issue, Review, Waiver
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.db.models.evidence import Evidence


@dataclass(slots=True)
class CanonicalScenarioGraph:
    """DB-backed aggregate used by resolver, gate, API, and view projection."""

    scenario: Scenario
    variant: ScenarioVariant
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
        pipeline = self.scenario.pipeline or {}
        return list(pipeline.get("nodes") or [])

    @property
    def pipeline_edges(self) -> list[dict[str, Any]]:
        pipeline = self.scenario.pipeline or {}
        return list(pipeline.get("edges") or [])

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

    variant = (
        db.query(ScenarioVariant)
        .filter_by(scenario_id=scenario_id, id=variant_id)
        .one_or_none()
    )
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

    ip_refs = {
        node.get("ip_ref")
        for node in (scenario.pipeline or {}).get("nodes", [])
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
