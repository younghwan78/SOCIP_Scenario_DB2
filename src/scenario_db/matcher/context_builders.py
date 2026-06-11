from __future__ import annotations

from typing import Any

from scenario_db.matcher.context import MatcherContext


def build_variant_matcher_context(variant: Any) -> MatcherContext:
    return MatcherContext(
        design_conditions=getattr(variant, "design_conditions", None) or {},
        ip_requirements=getattr(variant, "ip_requirements", None) or {},
        sw_requirements=normalized_sw_requirements(
            getattr(variant, "sw_requirements", None) or {},
            None,
        ),
    )


def build_evidence_matcher_context(variant: Any, evidence: Any) -> MatcherContext:
    execution_context = getattr(evidence, "execution_context", None) or {}
    return MatcherContext(
        design_conditions={
            **(getattr(variant, "design_conditions", None) or {}),
            **execution_context,
        },
        ip_requirements=getattr(variant, "ip_requirements", None) or {},
        sw_requirements=normalized_sw_requirements(
            getattr(variant, "sw_requirements", None) or {},
            evidence,
        ),
        execution_context=execution_context,
    )


def normalized_sw_requirements(sw_requirements: dict[str, Any], evidence: Any | None) -> dict[str, Any]:
    normalized = dict(sw_requirements) if isinstance(sw_requirements, dict) else {}
    feature_flags: dict[str, Any] = {}

    existing_flags = normalized.get("feature_flags")
    if isinstance(existing_flags, dict):
        feature_flags.update(existing_flags)

    for item in normalized.get("required_features") or []:
        if isinstance(item, dict):
            feature_flags.update(item)

    if evidence is not None:
        resolution_result = getattr(evidence, "resolution_result", None) or {}
        sw_resolution = resolution_result.get("sw_resolution") if isinstance(resolution_result, dict) else {}
        if not isinstance(sw_resolution, dict):
            sw_resolution = {}
        for check in (sw_resolution or {}).get("required_features_check") or []:
            if isinstance(check, dict) and check.get("feature"):
                feature_flags[str(check["feature"])] = check.get("actual", check.get("status"))

    if feature_flags:
        normalized["feature_flags"] = feature_flags
    return normalized
