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

    project_ids = {p.id for p in db.query(Project).all()}
    scenario_ids = {s.id for s in db.query(Scenario).all()}
    variant_keys = {
        (v.scenario_id, v.id)
        for v in db.query(ScenarioVariant).all()
    }
    ip_ids = {ip.id for ip in db.query(IpCatalog).all()}
    issue_ids = {i.id for i in db.query(Issue).all()}
    waiver_ids = {w.id for w in db.query(Waiver).all()}
    evidence_ids = {e.id for e in db.query(Evidence).all()}

    for scenario in db.query(Scenario).all():
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

    for variant in db.query(ScenarioVariant).all():
        if variant.scenario_id not in scenario_ids:
            report.errors.append(
                f"Variant {variant.id} references missing scenario {variant.scenario_id}"
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

