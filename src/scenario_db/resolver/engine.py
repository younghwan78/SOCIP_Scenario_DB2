from __future__ import annotations

from typing import Any

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.resolver.models import IpResolution, ResolverResult


def resolve_graph(graph: CanonicalScenarioGraph) -> ResolverResult:
    """Resolve variant requirements against capability catalog rows."""

    result = ResolverResult(
        scenario_id=graph.scenario_id,
        variant_id=graph.variant_id,
    )

    ip_requirements = graph.variant.ip_requirements or {}
    for node_id, requested in ip_requirements.items():
        if not isinstance(requested, dict):
            continue
        ip_ref = graph.ip_ref_for_node(node_id) or _infer_ip_ref(node_id, graph)
        ip_row = graph.ip_catalog.get(ip_ref or "")
        resolution = _resolve_ip_requirement(node_id, ip_ref, requested, ip_row)
        result.ip_resolutions[node_id] = resolution
        if resolution.status != "PASS":
            result.unresolved_requirements.extend(resolution.violations)

    result.sw_resolutions = _resolve_sw_requirements(graph.variant.sw_requirements or {}, graph)
    return result


def _infer_ip_ref(node_id: str, graph: CanonicalScenarioGraph) -> str | None:
    lowered = node_id.lower()
    for node in graph.pipeline_nodes:
        ip_ref = node.get("ip_ref")
        if not ip_ref:
            continue
        if lowered in ip_ref.lower():
            return ip_ref
    return None


def _resolve_ip_requirement(
    node_id: str,
    ip_ref: str | None,
    requested: dict[str, Any],
    ip_row: Any,
) -> IpResolution:
    if ip_row is None:
        return IpResolution(
            node_id=node_id,
            ip_ref=ip_ref,
            requested=requested,
            status="FAIL",
            violations=[{"field": "ip_ref", "reason": "missing_ip_catalog", "value": ip_ref}],
        )

    capabilities = ip_row.capabilities or {}
    modes = list(capabilities.get("operating_modes") or [])
    supported = capabilities.get("supported_features") or {}
    violations: list[dict] = []

    required_throughput = requested.get("required_throughput_mpps")
    matched_mode = None
    capability_max: dict[str, Any] = {}
    headroom: dict[str, Any] = {}
    if required_throughput is not None:
        modes_with_tp = [
            m for m in modes
            if isinstance(m, dict) and m.get("throughput_mpps") is not None
        ]
        if modes_with_tp:
            capability_max["throughput_mpps"] = max(m["throughput_mpps"] for m in modes_with_tp)
            candidates = [
                m for m in modes_with_tp
                if m["throughput_mpps"] >= required_throughput
            ]
            if candidates:
                best = sorted(candidates, key=lambda m: m["throughput_mpps"])[0]
                matched_mode = best.get("id")
                headroom["throughput_mpps"] = best["throughput_mpps"] - required_throughput
            else:
                best = sorted(modes_with_tp, key=lambda m: m["throughput_mpps"], reverse=True)[0]
                matched_mode = best.get("id")
                violations.append({
                    "field": "required_throughput_mpps",
                    "requested": required_throughput,
                    "capability_max": capability_max["throughput_mpps"],
                    "reason": "throughput_exceeds_capability",
                })

    required_bitdepth = requested.get("required_bitdepth")
    bitdepths = supported.get("bitdepth")
    if required_bitdepth is not None and bitdepths and required_bitdepth not in bitdepths:
        violations.append({
            "field": "required_bitdepth",
            "requested": required_bitdepth,
            "supported": bitdepths,
            "reason": "unsupported_bitdepth",
        })

    required_features = requested.get("required_features") or []
    hdr_formats = supported.get("hdr_formats") or []
    for feature in required_features:
        if isinstance(feature, str) and feature.startswith("HDR") and feature not in hdr_formats:
            violations.append({
                "field": "required_features",
                "requested": feature,
                "supported": hdr_formats,
                "reason": "unsupported_hdr_format",
            })

    status = "FAIL" if violations else "PASS"
    return IpResolution(
        node_id=node_id,
        ip_ref=ip_ref,
        requested=requested,
        matched_mode=matched_mode,
        capability_max=capability_max,
        headroom=headroom,
        violations=violations,
        status=status,
    )


def _resolve_sw_requirements(sw_requirements: dict, graph: CanonicalScenarioGraph) -> dict:
    evidence = graph.evidence[0] if graph.evidence else None
    if evidence and evidence.resolution_result:
        return evidence.resolution_result.get("sw_resolution") or {}
    return {
        "requested": sw_requirements,
        "profile_refs_from_evidence": sorted(graph.sw_profiles),
    }

