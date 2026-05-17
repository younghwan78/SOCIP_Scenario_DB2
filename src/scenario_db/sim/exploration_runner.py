from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from scenario_db.db.models.capability import IpCatalog, SocPlatform
from scenario_db.db.models.definition import Project, Scenario
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.db.repositories.variant_resolution import ResolvedScenarioVariant
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.exploration import ExplorationSweep, compile_exploration_sweep
from scenario_db.sim.chain_templates import compile_chain_template
from scenario_db.sim.models import DVFSTable, SimRunResult, SimulationRunConfig
from scenario_db.sim.runner import run_simulation


class SweepPreviewCase(BaseModel):
    case_id: str
    scenario_id: str
    variant_id: str
    axis_values: dict[str, Any] = Field(default_factory=dict)
    kpi: dict[str, Any] = Field(default_factory=dict)
    delta_from_baseline: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    feasible: bool = True
    infeasible_reason: str | None = None
    result: SimRunResult | None = None


class SweepPreviewResult(BaseModel):
    persisted: bool = False
    baseline_case_id: str | None = None
    cases: list[SweepPreviewCase] = Field(default_factory=list)
    comparison: list[dict[str, Any]] = Field(default_factory=list)
    import_bundle: dict[str, Any] = Field(default_factory=dict)


def run_exploration_sweep_preview(
    sweep: ExplorationSweep,
    *,
    ip_catalog: dict[str, IpCatalog],
    project: Project | None = None,
    soc: SocPlatform | None = None,
    config: SimulationRunConfig | None = None,
    dvfs_tables: dict[str, DVFSTable] | None = None,
    include_results: bool = False,
) -> SweepPreviewResult:
    """Compile and run a sweep as preview-only simulation results.

    This helper deliberately does not persist evidence. Callers can decide which
    candidate should be promoted to a variant or saved as evidence later.
    """

    compiled = compile_exploration_sweep(sweep)
    case_meta = {item["variant_id"]: item for item in compiled.cases}
    return run_import_bundle_preview(
        compiled.import_bundle,
        case_meta=case_meta,
        ip_catalog=ip_catalog,
        project=project,
        soc=soc,
        config=config,
        dvfs_tables=dvfs_tables,
        include_results=include_results,
    )


def run_chain_template_preview(
    template: dict[str, Any],
    *,
    ip_catalog: dict[str, IpCatalog],
    project: Project | None = None,
    soc: SocPlatform | None = None,
    config: SimulationRunConfig | None = None,
    dvfs_tables: dict[str, DVFSTable] | None = None,
    include_results: bool = False,
) -> SweepPreviewResult:
    compiled = compile_chain_template(template)
    scenario = compiled.scenario
    variant = (scenario.get("variants") or [{}])[0]
    design = variant.get("design_conditions") or {}
    case_meta = {
        str(variant.get("id")): {
            "case_id": variant.get("id"),
            "axis_values": {"template": design.get("template_ref")},
        }
    }
    return run_import_bundle_preview(
        compiled.import_bundle,
        case_meta=case_meta,
        ip_catalog=ip_catalog,
        project=project,
        soc=soc,
        config=config,
        dvfs_tables=dvfs_tables,
        include_results=include_results,
    )


def run_import_bundle_preview(
    import_bundle: dict[str, Any],
    *,
    case_meta: dict[str, dict[str, Any]] | None = None,
    ip_catalog: dict[str, IpCatalog],
    project: Project | None = None,
    soc: SocPlatform | None = None,
    config: SimulationRunConfig | None = None,
    dvfs_tables: dict[str, DVFSTable] | None = None,
    include_results: bool = False,
) -> SweepPreviewResult:
    docs = import_bundle.get("documents") or []
    meta_by_variant = case_meta or {}
    cases: list[SweepPreviewCase] = []
    run_config = config or SimulationRunConfig(include_timeline=False)
    for doc in docs:
        scenario = _scenario_from_doc(doc)
        for variant_doc in doc.get("variants") or []:
            variant = _variant_from_doc(scenario.id, variant_doc)
            graph = CanonicalScenarioGraph(
                scenario=scenario,
                variant=variant,
                project=project,
                soc=soc,
                ip_catalog=ip_catalog,
            )
            inputs = build_simulation_inputs(graph, run_config)
            result = run_simulation(inputs, dvfs_tables=dvfs_tables or {})
            meta = meta_by_variant.get(variant.id, {})
            cases.append(
                SweepPreviewCase(
                    case_id=str(meta.get("case_id") or variant.id),
                    scenario_id=scenario.id,
                    variant_id=variant.id,
                    axis_values=dict(meta.get("axis_values") or {}),
                    kpi=_kpi_from_result(result),
                    warnings=list(result.warnings),
                    feasible=result.feasible,
                    infeasible_reason=result.infeasible_reason,
                    result=result if include_results else None,
                )
            )

    _apply_deltas(cases)
    return SweepPreviewResult(
        persisted=False,
        baseline_case_id=cases[0].case_id if cases else None,
        cases=cases,
        comparison=[
            {
                "case_id": case.case_id,
                "scenario_id": case.scenario_id,
                "variant_id": case.variant_id,
                **case.axis_values,
                **case.kpi,
                **{f"delta_{key}": value for key, value in case.delta_from_baseline.items()},
                "feasible": case.feasible,
                "warning_count": len(case.warnings),
                "infeasible_reason": case.infeasible_reason,
            }
            for case in cases
        ],
        import_bundle=import_bundle,
    )


def _scenario_from_doc(doc: dict[str, Any]) -> Scenario:
    return Scenario(
        id=doc["id"],
        schema_version=str(doc.get("schema_version") or "2.2"),
        project_ref=doc["project_ref"],
        metadata_=doc.get("metadata") or {},
        pipeline=doc.get("pipeline") or {},
        size_profile=doc.get("size_profile"),
        design_axes=doc.get("design_axes") or [],
        yaml_sha256="exploration-preview",
    )


def _variant_from_doc(scenario_id: str, doc: dict[str, Any]) -> ResolvedScenarioVariant:
    return ResolvedScenarioVariant(
        scenario_id=scenario_id,
        id=doc["id"],
        severity=doc.get("severity"),
        design_conditions=doc.get("design_conditions") or {},
        design_conditions_override=doc.get("design_conditions_override") or {},
        size_overrides=doc.get("size_overrides") or {},
        routing_switch=doc.get("routing_switch") or {},
        topology_patch=doc.get("topology_patch") or {},
        node_configs=doc.get("node_configs") or {},
        buffer_overrides=doc.get("buffer_overrides") or {},
        ip_requirements=doc.get("ip_requirements") or {},
        sw_requirements=doc.get("sw_requirements"),
        violation_policy=doc.get("violation_policy"),
        tags=doc.get("tags") or [],
        derived_from_variant=doc.get("derived_from_variant"),
        resolved=True,
        inheritance_chain=[doc["id"]],
    )


def _kpi_from_result(result: SimRunResult) -> dict[str, Any]:
    return {
        "total_power_mw": result.total_power_mw,
        "core_power_mw": result.core_power_mw,
        "bw_power_mw": result.bw_power_mw,
        "total_bw_mbs": result.bw_total_mbs,
        "hw_time_max_ms": result.hw_time_max_ms,
        "timeline_end_ms": result.timeline_end_ms or 0.0,
    }


def _apply_deltas(cases: list[SweepPreviewCase]) -> None:
    if not cases:
        return
    baseline = cases[0].kpi
    for case in cases:
        case.delta_from_baseline = {
            key: float(case.kpi.get(key) or 0.0) - float(baseline.get(key) or 0.0)
            for key in ("total_power_mw", "core_power_mw", "bw_power_mw", "total_bw_mbs", "hw_time_max_ms", "timeline_end_ms")
        }
