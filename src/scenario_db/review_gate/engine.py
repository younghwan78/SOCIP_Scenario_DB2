from __future__ import annotations

from typing import Any

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.matcher.context import MatcherContext
from scenario_db.matcher.runner import evaluate
from scenario_db.resolver.engine import resolve_graph
from scenario_db.resolver.models import ResolverResult
from scenario_db.review_gate.models import (
    GateExecutionResult,
    IssueMatchResult,
    RuleCheckResult,
    WaiverMatchResult,
)


def run_review_gate(
    graph: CanonicalScenarioGraph,
    resolver_result: ResolverResult | None = None,
) -> GateExecutionResult:
    """Evaluate resolver output, evidence, known issues, and waivers.

    This engine is intentionally deterministic and read-only. Authored YAML/DB
    rows stay as the source data; matched issues and waivers are derived here.
    """

    resolver = resolver_result or resolve_graph(graph)
    issue_matches = _match_issues(graph)
    waiver_matches = _match_waivers(graph, issue_matches)
    rule_checks = _check_gate_rules(graph, resolver, issue_matches)

    waived_issue_ids = {
        waiver.issue_ref
        for waiver in waiver_matches
        if waiver.applies and waiver.issue_ref
    }
    missing_waivers = [
        issue.issue_id
        for issue in issue_matches
        if issue.issue_id not in waived_issue_ids
    ]

    status = _derive_status(resolver, rule_checks, issue_matches, missing_waivers)
    return GateExecutionResult(
        scenario_id=graph.scenario_id,
        variant_id=graph.variant_id,
        status=status,
        matched_rules=rule_checks,
        matched_issues=issue_matches,
        applicable_waivers=waiver_matches,
        missing_waivers=missing_waivers,
        evidence_refs=[ev.id for ev in graph.evidence],
        resolver_warnings=resolver.warnings,
        summary={
            "resolver_failures": len(resolver.unresolved_requirements),
            "issue_matches": len(issue_matches),
            "waivers_applied": len([w for w in waiver_matches if w.applies]),
            "gate_rules": len(rule_checks),
        },
    )


def _derive_status(
    resolver: ResolverResult,
    rule_checks: list[RuleCheckResult],
    issue_matches: list[IssueMatchResult],
    missing_waivers: list[str],
) -> str:
    if resolver.has_failures or any(rule.status == "BLOCK" for rule in rule_checks):
        return "BLOCK"
    if missing_waivers:
        return "WAIVER_REQUIRED"
    if issue_matches or resolver.has_warnings or any(rule.status == "WARN" for rule in rule_checks):
        return "WARN"
    return "PASS"


def _match_issues(graph: CanonicalScenarioGraph) -> list[IssueMatchResult]:
    matches: list[IssueMatchResult] = []
    for issue in graph.issues:
        for affect in issue.affects or []:
            if affect.get("scenario_ref") not in (None, "*", graph.scenario_id):
                continue

            match_rule = affect.get("match_rule")
            if not match_rule:
                matched = True
                matched_by = "scenario_ref"
            else:
                matched, matched_by = _evaluate_against_variant_and_evidence(match_rule, graph)

            if matched:
                metadata = issue.metadata_ or {}
                matches.append(
                    IssueMatchResult(
                        issue_id=issue.id,
                        title=metadata.get("title") or issue.id,
                        severity=metadata.get("severity"),
                        status=metadata.get("status"),
                        matched_by=matched_by,
                    )
                )
                break
    return matches


def _evaluate_against_variant_and_evidence(
    match_rule: dict[str, Any],
    graph: CanonicalScenarioGraph,
) -> tuple[bool, str]:
    if _safe_evaluate(match_rule, _variant_context(graph)):
        return True, "variant"

    for evidence in graph.evidence:
        if _safe_evaluate(match_rule, _evidence_context(graph, evidence)):
            return True, f"evidence:{evidence.id}"
    return False, "no_match"


def _match_waivers(
    graph: CanonicalScenarioGraph,
    issue_matches: list[IssueMatchResult],
) -> list[WaiverMatchResult]:
    issue_ids = {issue.issue_id for issue in issue_matches}
    results: list[WaiverMatchResult] = []

    for waiver in graph.waivers:
        if waiver.issue_ref not in issue_ids:
            continue
        applies = waiver.status in {"approved", "active"} and _waiver_applies(graph, waiver.scope or {})
        results.append(
            WaiverMatchResult(
                waiver_id=waiver.id,
                issue_ref=waiver.issue_ref,
                status=waiver.status,
                applies=applies,
            )
        )
    return results


def _waiver_applies(graph: CanonicalScenarioGraph, scope: dict[str, Any]) -> bool:
    variant_scope = scope.get("variant_scope") or {}
    scenario_ref = variant_scope.get("scenario_ref")
    if scenario_ref not in (None, "*", graph.scenario_id):
        return False

    variant_rule = variant_scope.get("match_rule")
    if variant_rule and not _safe_evaluate(variant_rule, _variant_context(graph)):
        return False

    execution_scope = scope.get("execution_scope")
    if not execution_scope:
        return True

    for evidence in graph.evidence:
        if _safe_evaluate(execution_scope, _execution_axis_context(graph, evidence)):
            return True
    return False


def _check_gate_rules(
    graph: CanonicalScenarioGraph,
    resolver: ResolverResult,
    issue_matches: list[IssueMatchResult],
) -> list[RuleCheckResult]:
    checks: list[RuleCheckResult] = []
    for rule in graph.gate_rules:
        if not _gate_rule_applies(rule, graph):
            continue

        matched = _match_gate_condition(rule.condition or {}, graph)
        if not matched:
            continue

        action = rule.action or {}
        requested_status = action.get("gate_result", "WARN")
        status = requested_status if requested_status in {"PASS", "WARN", "BLOCK"} else "WARN"
        checks.append(
            RuleCheckResult(
                rule_id=rule.id,
                status=status,
                message=action.get("message_template") or (rule.metadata_ or {}).get("name"),
            )
        )

    if resolver.has_failures:
        checks.append(
            RuleCheckResult(
                rule_id="resolver-capability",
                status="BLOCK",
                message="One or more variant requirements cannot be resolved against the capability catalog.",
            )
        )
    elif resolver.has_warnings:
        checks.append(
            RuleCheckResult(
                rule_id="resolver-capability",
                status="WARN",
                message="Resolver completed with warnings.",
            )
        )

    if issue_matches and not any(c.rule_id == "known-issue-derived" for c in checks):
        checks.append(
            RuleCheckResult(
                rule_id="known-issue-derived",
                status="WARN",
                message="Known issue matched the scenario variant or evidence context.",
            )
        )
    return checks


def _gate_rule_applies(rule: Any, graph: CanonicalScenarioGraph) -> bool:
    applies_to = rule.applies_to or {}
    match = applies_to.get("match") or {}
    severity_rule = match.get("variant.severity")
    if severity_rule is None:
        return True
    severity = getattr(graph.variant, "severity", None)
    allowed = severity_rule.get("$in") if isinstance(severity_rule, dict) else None
    return severity in allowed if allowed else True


def _match_gate_condition(condition: dict[str, Any], graph: CanonicalScenarioGraph) -> bool:
    match = condition.get("match") or {}
    if not match:
        return False

    for evidence in graph.evidence:
        evidence_doc = _evidence_doc(evidence)
        if all(_match_operator(_get_path(evidence_doc, path), expr) for path, expr in match.items()):
            return True
    return False


def _match_operator(actual: Any, expr: Any) -> bool:
    if not isinstance(expr, dict):
        return actual == expr
    if "$in" in expr:
        return actual in expr["$in"]
    if "$not_empty" in expr:
        return bool(actual) is bool(expr["$not_empty"])
    if "$eq" in expr:
        return actual == expr["$eq"]
    if "$ne" in expr:
        return actual != expr["$ne"]
    return False


def _variant_context(graph: CanonicalScenarioGraph) -> MatcherContext:
    return MatcherContext(
        design_conditions=graph.variant.design_conditions,
        ip_requirements=graph.variant.ip_requirements,
        sw_requirements=_normalized_sw_requirements(graph.variant.sw_requirements or {}, None),
    )


def _evidence_context(graph: CanonicalScenarioGraph, evidence: Any) -> MatcherContext:
    design_conditions = {
        **(graph.variant.design_conditions or {}),
        **(evidence.execution_context or {}),
    }
    return MatcherContext(
        design_conditions=design_conditions,
        ip_requirements=graph.variant.ip_requirements,
        sw_requirements=_normalized_sw_requirements(graph.variant.sw_requirements or {}, evidence),
        execution_context=evidence.execution_context,
    )


def _execution_axis_context(graph: CanonicalScenarioGraph, evidence: Any) -> MatcherContext:
    return MatcherContext(
        design_conditions={
            **(graph.variant.design_conditions or {}),
            **(evidence.execution_context or {}),
        },
        ip_requirements=graph.variant.ip_requirements,
        sw_requirements=_normalized_sw_requirements(graph.variant.sw_requirements or {}, evidence),
        execution_context=evidence.execution_context,
    )


def _normalized_sw_requirements(sw_requirements: dict[str, Any], evidence: Any | None) -> dict[str, Any]:
    normalized = dict(sw_requirements)
    feature_flags: dict[str, Any] = {}

    for item in sw_requirements.get("required_features") or []:
        if isinstance(item, dict):
            feature_flags.update(item)

    if evidence is not None:
        sw_resolution = (evidence.resolution_result or {}).get("sw_resolution") or {}
        for check in sw_resolution.get("required_features_check") or []:
            if isinstance(check, dict) and "feature" in check:
                feature_flags[check["feature"]] = check.get("actual", check.get("status"))

    if feature_flags:
        normalized["feature_flags"] = feature_flags
    return normalized


def _safe_evaluate(rule: dict[str, Any], ctx: MatcherContext) -> bool:
    try:
        return evaluate(rule, ctx)
    except (KeyError, TypeError, ValueError):
        return False


def _evidence_doc(evidence: Any) -> dict[str, Any]:
    return {
        "evidence": {
            "id": evidence.id,
            "execution_context": evidence.execution_context or {},
            "resolution_result": evidence.resolution_result or {},
            "overall_feasibility": (evidence.resolution_result or {}).get("overall_feasibility"),
            "kpi": evidence.kpi or {},
            "ip_breakdown": evidence.ip_breakdown or [],
        }
    }


def _get_path(document: dict[str, Any], dotted_path: str) -> Any:
    obj: Any = document
    for part in dotted_path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj
