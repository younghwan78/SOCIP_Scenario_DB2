"""Explicit cross-SoC SW assumptions, separate from measured replay."""

from __future__ import annotations
from copy import deepcopy
from typing import Literal

from pydantic import ConfigDict, Field, model_validator
from scenario_db.models.common import BaseScenarioModel
from scenario_db.models.evidence.profiling import TimingStatistics, SwEventLatency


class TimingAdjustment(BaseScenarioModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    scale: float | None = Field(default=None, ge=0)
    delta_ms: float | None = None

    @model_validator(mode="after")
    def one(self):
        if (self.scale is None) == (self.delta_ms is None):
            raise ValueError("choose exactly one of scale or delta_ms")
        return self

    def apply(self, stats):
        values = stats.model_dump()
        for key in ("min_ms", "mean_ms", "max_ms"):
            values[key] = (
                values[key] * self.scale if self.scale is not None else values[key] + self.delta_ms
            )
        return TimingStatistics.model_validate(values)


class TargetEdge(BaseScenarioModel):
    source: str
    target: str


class SwProjectionSelection(BaseScenarioModel):
    source_evidence_ref: str
    target_project_ref: str
    target_scenario_ref: str
    target_variant_ref: str
    target_path_id: str = Field(min_length=1)
    task_mapping: dict[str, str] = Field(default_factory=dict)
    edge_mapping: dict[str, TargetEdge] = Field(default_factory=dict)
    statistic: Literal["min", "mean", "max"] = "mean"
    runtime_overrides: dict[str, TimingAdjustment] = Field(default_factory=dict)
    latency_overrides: dict[str, TimingAdjustment] = Field(default_factory=dict)
    assumption_notes: str = Field(min_length=1)


class ProjectedEventLatency(SwEventLatency):
    value_source: Literal["projected"] = "projected"


class SwTimingProjection(SwProjectionSelection):
    source_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_enabled_node_ids: list[str]
    task_runtime: dict[str, TimingStatistics]
    event_latency: list[ProjectedEventLatency]


def build_projection(evidence, source_hash, graph, selection):
    from scenario_db.sim.measured_timing import baseline_fingerprint
    from scenario_db.sim.timeline_adapter import timeline_tasks, timeline_edges
    from scenario_db.sim.timing_profiles import timing_profiles

    if (
        selection.target_project_ref,
        selection.target_scenario_ref,
        selection.target_variant_ref,
    ) != (graph.scenario.project_ref, graph.scenario_id, graph.variant_id):
        raise ValueError("projection target scope mismatch")
    if selection.source_evidence_ref != str(evidence.id) or not evidence.pipeline_model:
        raise ValueError("projection requires curated camera evidence")
    model = evidence.pipeline_model
    if model.execution_path.mixed_path:
        raise ValueError("mixed-path statistics cannot be projected")
    tasks = {t.task_id: t for t in model.tasks}
    target_tasks = {str(t["id"]): t for t in timeline_tasks(graph)}
    target_profiles = timing_profiles(graph)
    source_stats = {t.task: t for t in evidence.sw_task_timing}
    if len(set(selection.task_mapping.values())) != len(selection.task_mapping):
        raise ValueError("multiple source runtimes mapped to one target")
    if (
        set(selection.runtime_overrides) - selection.task_mapping.keys()
        or set(selection.latency_overrides) - selection.edge_mapping.keys()
    ):
        raise ValueError("override must reference a selected source task/edge")
    runtime = {}
    for source, target in selection.task_mapping.items():
        task = tasks.get(source)
        if task is None or task.observation_only or task.kind != "sw" or task.timing_scope != "exclusive_sw":
            raise ValueError(
                "only exclusive SW runtime can be projected; HW/stage is validation-only"
            )
        stat = source_stats.get(source)
        if stat is None or stat.includes_hw_nodes or stat.includes_task_ids:
            raise ValueError("SW runtime missing or includes hardware")
        if stat.sample_unit != "invocation" or stat.count_per_frame not in (None, 1):
            raise ValueError("projection currently supports one invocation per frame only")
        if target not in target_tasks or target_tasks[target]["task_type"] != "sw":
            raise ValueError("target runtime must be an active SW node")
        if target_profiles.get(target, {}).get("includes_hw_nodes"):
            raise ValueError("target aggregate SW stage must be split before projection")
        stats = TimingStatistics.model_validate(
            {k: getattr(stat, k) for k in TimingStatistics.model_fields}
        )
        runtime[target] = (
            selection.runtime_overrides[source].apply(stats)
            if source in selection.runtime_overrides
            else stats
        )
    edges = {e.edge_id: e for e in model.edges}
    latency_stats = {e.edge_id: e for e in evidence.sw_event_latency}
    target_edges = timeline_edges(graph)
    latencies = []
    seen_pairs = set()
    for source, target in selection.edge_mapping.items():
        edge, stat = edges.get(source), latency_stats.get(source)
        if edge is None or stat is None or edge.source_anchor != "end" or edge.frame_offset:
            raise ValueError("projection requires measured same-frame end-to-start latency")
        pair = (target.source, target.target)
        if pair in seen_pairs:
            raise ValueError("duplicate target edge")
        seen_pairs.add(pair)
        for logical, mapped in (
            (edge.source_task_id, target.source),
            (edge.target_task_id, target.target),
        ):
            if logical in selection.task_mapping and selection.task_mapping[logical] != mapped:
                raise ValueError("edge mapping contradicts task mapping")
        matches = [
            e
            for e in target_edges
            if (str(e.get("from") or e.get("source")), str(e.get("to") or e.get("target"))) == pair
        ]
        if (
            len(matches) != 1
            or target.source not in target_tasks
            or target.target not in target_tasks
        ):
            raise ValueError("target edge must resolve uniquely to active tasks")
        stats = TimingStatistics.model_validate(
            {k: getattr(stat, k) for k in TimingStatistics.model_fields}
        )
        if source in selection.latency_overrides:
            stats = selection.latency_overrides[source].apply(stats)
        latencies.append(
            ProjectedEventLatency(
                **stats.model_dump(),
                edge_id=source,
                predecessor_task=target.source,
                successor_task=target.target,
                pairing=stat.pairing,
            )
        )
    if not runtime and not latencies:
        raise ValueError("projection has no selected SW timing/latency")
    return SwTimingProjection(
        **selection.model_dump(),
        source_evidence_sha256=source_hash,
        target_model_fingerprint=baseline_fingerprint(graph),
        target_enabled_node_ids=sorted(str(n["id"]) for n in graph.pipeline_nodes),
        task_runtime=runtime,
        event_latency=latencies,
    )


def verify_projection(db, graph, projection):
    from scenario_db.db.models.evidence import Evidence
    from scenario_db.api.services.timing_profiles import measurement_from_row

    source = db.get(Evidence, projection.source_evidence_ref)
    if source is None or source.kind != "evidence.measurement":
        raise ValueError("projection source evidence not found")
    selection = SwProjectionSelection.model_validate(
        projection.model_dump(include=set(SwProjectionSelection.model_fields))
    )
    expected = build_projection(measurement_from_row(source), source.yaml_sha256, graph, selection)
    if expected != projection:
        raise ValueError("projection source, target or timing changed; prepare again")


def apply_projection(graph, projection, tasks, edges, profiles):
    from scenario_db.sim.measured_timing import baseline_fingerprint

    if projection.target_model_fingerprint != baseline_fingerprint(graph):
        raise ValueError("projection target model changed")
    if (
        projection.target_project_ref,
        projection.target_scenario_ref,
        projection.target_variant_ref,
    ) != (graph.scenario.project_ref, graph.scenario_id, graph.variant_id):
        raise ValueError("projection target scope mismatch")
    tasks, edges, profiles = deepcopy(tasks), deepcopy(edges), deepcopy(profiles)
    by_id = {str(t["id"]): t for t in tasks}
    for target, stats in projection.task_runtime.items():
        if (
            target not in by_id
            or by_id[target]["task_type"] != "sw"
            or profiles.get(target, {}).get("includes_hw_nodes")
        ):
            raise ValueError("projection runtime target must be exclusive active SW")
        by_id[target]["duration_ms"] = getattr(stats, f"{projection.statistic}_ms")
        by_id[target]["measured_duration"] = (
            True  # fixed duration; source classification below is projected
        )
        profiles[target] = {
            **profiles.get(target, {}),
            **stats.model_dump(),
            "task": target,
            "value_source": "projected",
            "timing_scope": "exclusive_sw",
            "source_note": f"Projected from {projection.source_evidence_ref}: {projection.assumption_notes}",
        }
        for stale in ("p50_ms", "p95_ms", "start_jitter_mean_ms"):
            profiles[target].pop(stale, None)
    for latency in projection.event_latency:
        matches = [
            e
            for e in edges
            if (str(e.get("from") or e.get("source")), str(e.get("to") or e.get("target")))
            == (latency.predecessor_task, latency.successor_task)
        ]
        if len(matches) != 1:
            raise ValueError("projected edge no longer resolves uniquely")
        matches[0]["latency_ms"] = getattr(latency, f"{projection.statistic}_ms")
    return tasks, edges, profiles
