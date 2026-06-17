from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from scenario_db.db.models.capability import IpCatalog
from scenario_db.db.models.decision import Issue, Review, Waiver
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.db.models.evidence import Evidence


@dataclass(slots=True)
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_loaded_db(db: Session) -> ValidationReport:
    """Semantic validation after YAML has been loaded into PostgreSQL."""

    report = ValidationReport()

    projects = db.query(Project).all()
    scenarios = db.query(Scenario).all()
    variants = db.query(ScenarioVariant).all()
    ips = db.query(IpCatalog).all()

    project_ids = {p.id for p in projects}
    scenario_by_id = {s.id: s for s in scenarios}
    scenario_ids = set(scenario_by_id)
    variant_keys = {
        (v.scenario_id, v.id)
        for v in variants
    }
    ip_by_id = {ip.id: ip for ip in ips}
    ip_ids = set(ip_by_id)
    issue_ids = {i.id for i in db.query(Issue).all()}
    waiver_ids = {w.id for w in db.query(Waiver).all()}
    evidence_ids = {e.id for e in db.query(Evidence).all()}

    for scenario in scenarios:
        if scenario.project_ref not in project_ids:
            report.errors.append(
                f"Scenario {scenario.id} references missing project {scenario.project_ref}"
            )
        for node in (scenario.pipeline or {}).get("nodes", []):
            ip_ref = node.get("ip_ref")
            if ip_ref and ip_ref not in ip_ids:
                report.errors.append(
                    f"Scenario {scenario.id} node {node.get('id')} references missing IP {ip_ref}"
                )

    for variant in variants:
        if variant.scenario_id not in scenario_ids:
            report.errors.append(
                f"Variant {variant.id} references missing scenario {variant.scenario_id}"
            )
            continue
        scenario = scenario_by_id[variant.scenario_id]
        pipeline = scenario.pipeline or {}
        base_nodes = {
            str(node.get("id")): node
            for node in (pipeline.get("nodes") or [])
            if isinstance(node, dict) and node.get("id")
        }
        buffer_ids = set((pipeline.get("buffers") or {}).keys())
        topology_patch = variant.topology_patch or {}
        injected_nodes = {
            str(node.get("id"))
            for node in (topology_patch.get("add_nodes") or [])
            if isinstance(node, dict) and node.get("id")
        }
        known_nodes = set(base_nodes) | injected_nodes

        for node_id, config in (variant.node_configs or {}).items():
            if node_id not in known_nodes:
                report.errors.append(
                    f"Variant {variant.scenario_id}/{variant.id} node_configs references missing node {node_id}"
                )
                continue
            if not isinstance(config, dict):
                report.errors.append(
                    f"Variant {variant.scenario_id}/{variant.id} node_config {node_id} must be an object"
                )
                continue
            selected_mode = config.get("selected_mode")
            if selected_mode is None:
                continue
            node = base_nodes.get(str(node_id))
            ip_ref = node.get("ip_ref") if isinstance(node, dict) else None
            if not ip_ref:
                report.errors.append(
                    f"Variant {variant.scenario_id}/{variant.id} selected_mode requires an IP-backed node {node_id}"
                )
                continue
            modes = _operating_mode_ids(ip_by_id.get(str(ip_ref)))
            if modes and str(selected_mode) not in modes:
                report.errors.append(
                    f"Variant {variant.scenario_id}/{variant.id} selected_mode '{selected_mode}' "
                    f"is not supported by {ip_ref}"
                )

        for buffer_id in (variant.buffer_overrides or {}):
            if buffer_id not in buffer_ids:
                report.errors.append(
                    f"Variant {variant.scenario_id}/{variant.id} buffer_overrides references missing buffer {buffer_id}"
                )

    for evidence in db.query(Evidence).all():
        if evidence.scenario_ref not in scenario_ids:
            report.errors.append(
                f"Evidence {evidence.id} references missing scenario {evidence.scenario_ref}"
            )
        if (evidence.scenario_ref, evidence.variant_ref) not in variant_keys:
            report.errors.append(
                f"Evidence {evidence.id} references missing variant "
                f"{evidence.scenario_ref}/{evidence.variant_ref}"
            )

    for issue in db.query(Issue).all():
        for affect in issue.affects or []:
            if not isinstance(affect, dict):
                report.errors.append(f"Issue {issue.id} has non-object affects entry")
                continue
            scenario_ref = affect.get("scenario_ref")
            if scenario_ref and scenario_ref != "*" and scenario_ref not in scenario_ids:
                report.errors.append(
                    f"Issue {issue.id} affects missing scenario {scenario_ref}"
                )

    for waiver in db.query(Waiver).all():
        if waiver.issue_ref and waiver.issue_ref not in issue_ids:
            report.errors.append(
                f"Waiver {waiver.id} references missing issue {waiver.issue_ref}"
            )

    for review in db.query(Review).all():
        if review.scenario_ref not in scenario_ids:
            report.errors.append(
                f"Review {review.id} references missing scenario {review.scenario_ref}"
            )
        if (review.scenario_ref, review.variant_ref) not in variant_keys:
            report.errors.append(
                f"Review {review.id} references missing variant "
                f"{review.scenario_ref}/{review.variant_ref}"
            )
        for evidence_ref in review.evidence_refs or []:
            if evidence_ref not in evidence_ids:
                report.warnings.append(
                    f"Review {review.id} references missing evidence {evidence_ref}"
                )
        if review.waiver_ref and review.waiver_ref not in waiver_ids:
            report.errors.append(
                f"Review {review.id} references missing waiver {review.waiver_ref}"
            )

    return report


def _operating_mode_ids(ip: IpCatalog | None) -> set[str]:
    if ip is None:
        return set()
    caps = ip.capabilities or {}
    modes = caps.get("operating_modes") if isinstance(caps, dict) else None
    result: set[str] = set()
    for mode in modes or []:
        if isinstance(mode, dict) and mode.get("id") is not None:
            result.add(str(mode["id"]))
        elif getattr(mode, "id", None) is not None:
            result.add(str(mode.id))
    return result
