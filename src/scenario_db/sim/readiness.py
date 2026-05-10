from __future__ import annotations

from typing import Any, Literal

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.models import SimulationRunConfig
from scenario_db.sim.soc_profiles import profile_for_graph


Severity = Literal["error", "warning"]


def check_simulation_readiness(
    graph: CanonicalScenarioGraph,
    config: SimulationRunConfig | None = None,
) -> dict[str, Any]:
    """Return a structured preflight report for scenario simulation readiness."""

    run_config = config or SimulationRunConfig(include_timeline=False)
    inputs = build_simulation_inputs(graph, run_config)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    profile = profile_for_graph(graph)

    if not inputs.workloads:
        errors.append(_issue("error", "NO_COMPUTE_WORKLOADS", "No compute workloads were resolved."))

    for workload in inputs.workloads:
        params = workload.sim_params
        if params.ppc <= 0:
            errors.append(
                _issue(
                    "error",
                    "MISSING_PPC",
                    "ppc is required for clock and timing simulation.",
                    node_id=workload.node_id,
                    ip_ref=workload.ip_ref,
                )
            )
        if params.unit_power_mw_mp <= 0:
            warnings.append(
                _issue(
                    "warning",
                    "MISSING_UNIT_POWER",
                    "unit_power_mw_mp is zero; core power will be under-estimated.",
                    node_id=workload.node_id,
                    ip_ref=workload.ip_ref,
                )
            )
        if not params.dvfs_group:
            default_group = profile.default_dvfs_groups.get(workload.hw_name.upper())
            warnings.append(
                _issue(
                    "warning",
                    "MISSING_DVFS_GROUP",
                    f"dvfs_group is missing; default profile group is {default_group or 'not defined'}.",
                    node_id=workload.node_id,
                    ip_ref=workload.ip_ref,
                )
            )
        if not params.vdd:
            warnings.append(
                _issue(
                    "warning",
                    "MISSING_VDD",
                    "vdd is missing; power-domain alignment may be incomplete.",
                    node_id=workload.node_id,
                    ip_ref=workload.ip_ref,
                )
            )

    for message in inputs.warnings:
        target = warnings
        if "no capabilities.sim" in message or "ppc=0" in message:
            target = errors
        target.append(_issue("error" if target is errors else "warning", "ADAPTER_WARNING", message))

    status = "blocked" if errors else "warning" if warnings else "ready"
    return {
        "status": status,
        "scenario_id": graph.scenario_id,
        "variant_id": graph.variant_id,
        "soc_id": profile.soc_id,
        "profile": profile.as_dict(),
        "summary": {
            "compute_nodes": len(inputs.workloads),
            "dma_transfers": len(inputs.port_transfers),
            "timeline_tasks": len(inputs.timeline_tasks),
            "external_devices": len(inputs.external_devices),
        },
        "errors": _dedupe_issues(errors),
        "warnings": _dedupe_issues(warnings),
    }


def _issue(
    severity: Severity,
    code: str,
    message: str,
    *,
    node_id: str | None = None,
    ip_ref: str | None = None,
) -> dict[str, Any]:
    issue = {"severity": severity, "code": code, "message": message}
    if node_id:
        issue["node_id"] = node_id
    if ip_ref:
        issue["ip_ref"] = ip_ref
    return issue


def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    result: list[dict[str, Any]] = []
    for issue in issues:
        key = (
            issue.get("severity"),
            issue.get("code"),
            issue.get("message"),
            issue.get("node_id"),
            issue.get("ip_ref"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(issue)
    return result

