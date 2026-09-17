"""Small producer-defined camera graph; no raw event inference."""

from __future__ import annotations

from typing import Literal
from pydantic import Field, model_validator
from scenario_db.models.common import BaseScenarioModel
from scenario_db.models.evidence.profiling import TimingStatistics


class CameraTask(BaseScenarioModel):
    task_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: Literal["sensor", "sw", "hw", "group"]
    stage: Literal["sensor", "rt", "sw_m2m", "nrt", "eis", "gdc"]
    node_refs: list[str] = Field(default_factory=list)
    timing_scope: Literal["exclusive_sw", "hw_execution", "inclusive_stage"] | None = None
    includes_task_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def scope(self):
        if self.timing_scope == "exclusive_sw" and (self.kind != "sw" or self.includes_task_ids):
            raise ValueError("exclusive_sw must be SW without included tasks")
        if self.timing_scope == "hw_execution" and self.kind != "hw":
            raise ValueError("hw_execution requires HW")
        if self.timing_scope == "inclusive_stage" and not self.includes_task_ids:
            raise ValueError("inclusive_stage requires includes_task_ids")
        if len(self.node_refs) != len(set(self.node_refs)):
            raise ValueError("duplicate node_refs")
        return self


class CameraEdge(BaseScenarioModel):
    edge_id: str = Field(min_length=1)
    source_task_id: str
    target_task_id: str
    source_anchor: Literal["start", "end"] = "end"
    target_anchor: Literal["start"] = "start"
    dependency_kind: Literal["finish_to_start", "start_to_start"] = "finish_to_start"
    frame_offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def anchors(self):
        if (self.source_anchor == "end") != (self.dependency_kind == "finish_to_start"):
            raise ValueError("dependency kind and anchor disagree")
        return self


class DisabledTask(BaseScenarioModel):
    task_id: str
    reason: str = Field(min_length=1)


class CameraPath(BaseScenarioModel):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    enabled_task_ids: list[str] = Field(min_length=1)
    disabled_tasks: list[DisabledTask] = Field(default_factory=list)
    mixed_path: bool = False


class CameraPipeline(BaseScenarioModel):
    tasks: list[CameraTask] = Field(min_length=1, max_length=1000)
    edges: list[CameraEdge] = Field(default_factory=list, max_length=5000)
    execution_path: CameraPath
    model_binding: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def graph(self):
        ids = [t.task_id for t in self.tasks]
        enabled = self.execution_path.enabled_task_ids
        disabled = [t.task_id for t in self.execution_path.disabled_tasks]
        for values in (ids, enabled, disabled, [e.edge_id for e in self.edges]):
            if len(values) != len(set(values)):
                raise ValueError("duplicate camera graph identity")
        if set(enabled) - set(ids) or set(enabled) & set(disabled):
            raise ValueError("invalid enabled/disabled task set")
        if set(ids) - set(enabled) - set(disabled):
            raise ValueError("each declared task needs an explicit path state")
        adjacency = {key: [] for key in enabled}
        for edge in self.edges:
            if {edge.source_task_id, edge.target_task_id} - set(enabled):
                raise ValueError("edge references unknown/inactive task")
            if edge.frame_offset == 0:
                adjacency[edge.source_task_id].append(edge.target_task_id)
        pending = set(adjacency)
        while pending:
            leaves = {n for n in pending if not (set(adjacency[n]) & pending)}
            if not leaves:
                raise ValueError("same-frame camera dependency cycle")
            pending -= leaves
        return self


class StageTiming(TimingStatistics):
    task_id: str
    measurement_basis: Literal["first_start_to_last_end"] = "first_start_to_last_end"
    measurement_conditions: dict = Field(default_factory=dict)
    usage: Literal["validation_only"] = "validation_only"


class ProfilingMetadata(BaseScenarioModel):
    format_version: Literal["camera-profile-v1"] = "camera-profile-v1"
    generator_version: str = Field(min_length=1)
    measurement_scope: str = Field(min_length=1)
    workload: dict
    notes: str | None = None


def validate_camera_evidence(evidence):
    model = evidence.pipeline_model
    if model is None:
        if evidence.execution_path_id or evidence.stage_timing or evidence.profiling_metadata:
            raise ValueError("camera metadata requires pipeline_model")
        return evidence
    if evidence.execution_path_id != model.execution_path.id or evidence.profiling_metadata is None:
        raise ValueError("camera path/metadata mismatch")
    from datetime import datetime

    if evidence.execution_context.method != "measurement":
        raise ValueError("curated camera evidence requires method=measurement")
    if not evidence.measured_at or datetime.fromisoformat(evidence.measured_at).utcoffset() is None:
        raise ValueError("curated camera evidence requires measured_at with timezone")
    active = set(model.execution_path.enabled_task_ids)
    tasks = {t.task_id: t for t in model.tasks}
    for stat in evidence.sw_task_timing:
        if stat.value_source not in (None, "measured"):
            raise ValueError("camera timing must be measured")
    for group, identity in (
        (evidence.sw_task_timing, "task"),
        (evidence.hw_task_timing, "task"),
        (evidence.stage_timing, "task_id"),
        (evidence.sw_event_latency, "edge_id"),
    ):
        ids = [getattr(item, identity) for item in group]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate camera statistic")
    for stat in evidence.sw_task_timing:
        task = tasks.get(stat.task)
        if stat.task not in active or task.kind != "sw" or task.timing_scope is None:
            raise ValueError("SW timing needs active SW task and explicit scope")
        if (
            stat.timing_scope != task.timing_scope
            or stat.includes_task_ids != task.includes_task_ids
        ):
            raise ValueError("SW timing scope disagrees with task")
        TimingStatistics.model_validate(
            {k: getattr(stat, k) for k in TimingStatistics.model_fields}
        )
    for stat in evidence.hw_task_timing:
        task = tasks.get(stat.task)
        if stat.task not in active or task.kind != "hw" or stat.node_id not in task.node_refs:
            raise ValueError("HW timing needs an active HW node")
    for stat in evidence.stage_timing:
        task = tasks.get(stat.task_id)
        if (
            stat.task_id not in active
            or task.kind != "group"
            or task.timing_scope != "inclusive_stage"
        ):
            raise ValueError("stage timing requires active inclusive group")
    edges = {e.edge_id: e for e in model.edges}
    for stat in evidence.sw_event_latency:
        edge = edges.get(stat.edge_id)
        if edge is None or (stat.predecessor_task, stat.successor_task, stat.source_anchor) != (
            edge.source_task_id,
            edge.target_task_id,
            edge.source_anchor,
        ):
            raise ValueError("latency disagrees with declared edge")
    return evidence
