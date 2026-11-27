from __future__ import annotations

from enum import StrEnum  # EdgeType에서 사용
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scenario_db.models.definition.job import JobSpec, Selector, expression_names
from scenario_db.models.definition.subsystem import SubsystemSpec
from scenario_db.models.common import (
    BaseScenarioModel,
    DocumentId,
    FeatureFlagValue,
    SchemaVersion,
    Severity,
    ViolationAction,
    ViolationClassification,
)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class PipelineNode(BaseScenarioModel):
    id: str
    ip_ref: DocumentId
    instance_index: int = 0
    role: str | None = None
    # Explicit operation facts (crop/scale/rotate/...) consumed by the view
    # projection's OperationSummary; shape mirrors variant node_configs.
    operations: dict[str, Any] | None = None
    # D-03 workload load model of this node with scenario-local coefficients ({ref, codecs, ...}),
    # see sim/load_models.py; kept on the scenario so the shared IP catalog stays unchanged
    load_model: dict[str, Any] | None = None
    # D-03 domain load (GPU / NPU / audio DSP power: util x f x V^2 + leakage) with scenario-local
    # coefficients ({model, coeff_uw_per_mhz_v2, vf, leakage, ...}), see sim/domain_loads.py
    domain_load: dict[str, Any] | None = None
    # R-4 IP-internal subsystem (units / streams / stages / routes / wake; evaluator mcps-v1) — replaces the
    # node's domain_load when declared (None = none; see models/definition/subsystem.py)
    subsystem: SubsystemSpec | None = None


class EdgeType(StrEnum):
    OTF = "OTF"
    vOTF = "vOTF"
    M2M = "M2M"
    control = "control"


class PortPair(BaseModel):
    """Port-level wiring of one edge: producer port -> consumer port.

    For M2M edges these are the WDMA/RDMA module names; for OTF edges the
    FIFO port names. Optional — edges without pairs keep node-level wiring.
    """

    model_config = ConfigDict(extra="forbid")
    src: str = Field(min_length=1)
    dst: str = Field(min_length=1)


class PipelineEdge(BaseModel):
    # "from" is a Python keyword — use alias
    # populate_by_name=True: accepts both "from" (YAML) and "from_" (Python)
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_: str = Field(alias="from")
    to: str
    type: EdgeType
    buffer: str | None = None
    port_pairs: list[PortPair] = Field(default_factory=list)


JudgementStage = Literal["rt", "nrt", "post", "output"]
JudgementKpi = Literal["interval", "latency", "underrun", "frame_pacing", "start_time",
                       # R-6: the event job KPIs (declared per job in ``pipeline.jobs[].kpis``)
                       "event_latency", "event_rate", "event_energy", "peak_power", "peak_bw", "peak_footprint"]
# the KPIs the Timing Budget evaluates: interval / latency by the frame-interval path, the rest by the M-10
# registry (sim/kpis.py KPI_MODELS; a test keeps the two equal). Declared KPIs outside it are reported unmodelled.
MODELED_KPIS = ("interval", "latency", "underrun", "frame_pacing",
                "event_latency", "event_energy", "peak_power", "peak_bw", "peak_footprint")

# R-6 target vocabulary: KPI -> {metric: (unit, bound)}; None = the KPI's single value
KPI_METRICS: dict[str, dict[str | None, tuple[str, str]]] = {
    "latency": {None: ("ms", "max")},
    "underrun": {None: ("ms", "min")},             # v1: the smallest deadline slack of a period stream
    "frame_pacing": {None: ("%", "max"), "jank_pct": ("%", "max"), "achieved_fps": ("fps", "min"),
                     "frame_p99_ms": ("ms", "max"), "present_cov": ("ratio", "max")},
    "start_time": {None: ("ms", "max")},
    "event_latency": {None: ("ms", "max")},
    "event_rate": {None: ("1/s", "min")},
    "event_energy": {None: ("mJ", "max")},
    "peak_power": {None: ("mW", "max")},
    "peak_bw": {None: ("MB/s", "max")},
    "peak_footprint": {None: ("MB", "max")},
}
JOB_KPIS = ("event_latency", "event_rate", "event_energy", "peak_power", "peak_bw", "peak_footprint")
PEAK_KPIS = ("peak_power", "peak_bw", "peak_footprint")
TARGET_PEAK_WINDOW_MS = 10.0     # sim/jobs.py PEAK_WINDOW_MS (a test keeps them equal)


# sink kinds whose output interval is judged at the frame rate; audio (period buffers) and file (event outputs)
# are judged by their own KPI models, never by the frame interval
INTERVAL_SINK_KINDS = ("preview", "video", "display")


class JudgementSink(BaseScenarioModel):
    """An output the judgement checks. preview / video / display: its interval at the judgement rate;
    audio / file: not a frame interval (their KPI models judge them)."""

    node: str
    kind: Literal["preview", "video", "display", "audio", "file"]
    label: str | None = None


class RateSpec(BaseScenarioModel):
    """R-1: where the judgement rate comes from - exactly one of a fixed ``hz``, a ``design_conditions`` key
    (``condition``) or a node's ``sim.fps`` (``node``)."""

    condition: str | None = Field(default=None, min_length=1)
    hz: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    node: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _one_source(self) -> RateSpec:
        given = [k for k in ("condition", "hz", "node") if getattr(self, k) is not None]
        if len(given) != 1:
            raise ValueError(f"judgement.rate needs exactly one of condition / hz / node (got {given or 'none'})")
        return self


class KpiTarget(Selector):
    """R-6: a KPI target of the judgement contract. ``when`` / ``when_node_enabled`` select the variants; of the
    targets matching one (kpi, metric, job, milestone) the one with the most ``when`` keys wins."""

    id: str = Field(min_length=1)
    kpi: JudgementKpi
    metric: str | None = None         # frame_pacing: jank_pct (default) | achieved_fps | frame_p99_ms | present_cov
    job: str | None = None            # event / peak KPIs: one job (None = every active job declaring the KPI)
    milestone: str | None = None      # event_latency: which milestone (required)
    max: float | None = Field(default=None, allow_inf_nan=False)
    min: float | None = Field(default=None, allow_inf_nan=False)
    window_ms: float | None = Field(default=None, gt=0, allow_inf_nan=False)   # peak KPIs: v1 = 10 ms only
    value_source: Literal["spec", "assumed"] = "assumed"
    basis: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> KpiTarget:
        where = f"judgement.targets.{self.id}"
        if self.kpi == "interval":
            raise ValueError(f"{where}: interval is judged by the frame-interval path; it takes no target")
        metrics = KPI_METRICS[self.kpi]
        if self.metric not in metrics:
            named = sorted(m for m in metrics if m)
            raise ValueError(f"{where}: metric {self.metric!r} is not one of {named} for {self.kpi}" if named
                             else f"{where}: {self.kpi} takes no metric")
        if (self.max is None) == (self.min is None):
            raise ValueError(f"{where}: give exactly one of max / min")
        bound = metrics[self.metric][1]
        if (self.max if bound == "min" else self.min) is not None:
            raise ValueError(f"{where}: {self.kpi}{'.' + self.metric if self.metric else ''} is bounded by {bound}")
        if self.milestone is not None and self.kpi != "event_latency":
            raise ValueError(f"{where}: milestone applies to event_latency only")
        if self.kpi == "event_latency" and self.milestone is None:
            raise ValueError(f"{where}: event_latency needs a milestone")
        if self.job is not None and self.kpi not in JOB_KPIS:
            raise ValueError(f"{where}: job applies to the event job KPIs only")
        if self.window_ms is not None and (self.kpi not in PEAK_KPIS or self.window_ms != TARGET_PEAK_WINDOW_MS):
            raise ValueError(f"{where}: window_ms applies to peak KPIs and must be {TARGET_PEAK_WINDOW_MS:g} "
                             "(the job evaluator's window)")
        return self

    def key(self) -> tuple[str, str | None, str | None, str | None]:
        """What a target judges; the metric defaults to the KPI's first one (frame_pacing: jank_pct)."""
        metric = self.metric or ("jank_pct" if self.kpi == "frame_pacing" else None)
        return self.kpi, metric, self.job, self.milestone


class JudgementContract(BaseScenarioModel):
    """What the Timing Budget judges for this scenario (D-02).

    ``sinks``: the output nodes whose interval is judged (instead of the node-name rule: DPU = preview,
    MFC / APV = video). A sink inactive in a variant is not judged there.
    ``stages``: node role -> timing stage, applied before the name rule (explicit option overrides win).
    ``kpis``: what the scenario requires; KPIs without a model are reported as such, never as passed.
    Undeclared scenarios keep the name rules unchanged.
    """

    sinks: list[JudgementSink] = Field(default_factory=list)
    stages: dict[str, JudgementStage] = Field(default_factory=dict)
    kpis: list[JudgementKpi] = Field(default_factory=lambda: ["interval"])
    # R-1: the judgement rate (None = design_conditions.fps, else 30); a request fps still wins
    rate: RateSpec | None = None
    # R-6: KPI targets (None = none: values only, report and hash unchanged)
    targets: list[KpiTarget] | None = None


def target_reference_errors(contract: JudgementContract | None, jobs: list[JobSpec]) -> list[str]:
    """R-6 target checks against the pipeline (shared by the model and the pipeline patch path): unique ids, a
    declared KPI (``judgement.kpis`` or a job's ``kpis``), known jobs and milestones."""
    targets = (contract.targets if contract else None) or []
    errors: list[str] = []
    ids = [t.id for t in targets]
    if len(ids) != len(set(ids)):
        errors.append(f"duplicate judgement target ids {sorted({i for i in ids if ids.count(i) > 1})}")
    by_id = {j.id: j for j in jobs}
    for t in targets:
        where = f"judgement.targets.{t.id}"
        if t.kpi not in JOB_KPIS:
            if contract is None or t.kpi not in contract.kpis:
                errors.append(f"{where}: kpi {t.kpi} is not declared in judgement.kpis")
            continue
        if t.job is not None and t.job not in by_id:
            errors.append(f"{where}: job '{t.job}' not found in pipeline.jobs")
            continue
        # a job KPI in judgement.kpis applies to every job (as the registry evaluates it)
        scenario_wide = contract is not None and t.kpi in contract.kpis
        declaring = [j for j in ([by_id[t.job]] if t.job else jobs) if scenario_wide or t.kpi in (j.kpis or [])]
        if not declaring:
            errors.append(f"{where}: no job{' ' + t.job if t.job else ''} declares kpi {t.kpi}")
        elif t.milestone is not None:
            missing = [j.id for j in declaring if t.milestone not in (j.milestones or {})]
            if missing:
                errors.append(f"{where}: milestone '{t.milestone}' not found in job(s) {missing}")
    return errors

def job_reference_errors(jobs: list[JobSpec], node_ids: set[str], buffers: set[str]) -> list[str]:
    """Pipeline-level job checks (shared by the model and the pipeline patch path): ids, nodes, session buffers."""
    errors: list[str] = []
    job_ids = [j.id for j in jobs]
    if len(job_ids) != len(set(job_ids)):
        errors.append(f"duplicate job ids {sorted({i for i in job_ids if job_ids.count(i) > 1})}")
    for job in jobs:
        clash = sorted(set(job.buffers or {}) & buffers)
        if clash:
            errors.append(f"job {job.id}: job buffers {clash} shadow pipeline buffers")
        if job.when_node_enabled is not None and job.when_node_enabled not in node_ids:
            errors.append(f"job {job.id}: when_node_enabled '{job.when_node_enabled}' not found in nodes")
        for stage in job.stages:
            if stage.when_node_enabled is not None and stage.when_node_enabled not in node_ids:
                errors.append(f"job {job.id}: stage {stage.id} when_node_enabled "
                              f"'{stage.when_node_enabled}' not found in nodes")
            for node in [*stage.nodes, *(stage.holds or [])]:
                if node not in node_ids:
                    errors.append(f"job {job.id}: stage {stage.id} node '{node}' not found in nodes")
            unknown = [b for b in (stage.reads or []) if b not in buffers]
            if unknown:
                errors.append(f"job {job.id}: stage {stage.id} reads {unknown}, which are not pipeline "
                              "(session) buffers; job buffers flow from the stage's predecessors")
    return errors


class Pipeline(BaseScenarioModel):
    nodes: list[PipelineNode] = Field(default_factory=list)
    edges: list[PipelineEdge] = Field(default_factory=list)
    buffers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    architecture_graph: dict[str, Any] = Field(default_factory=dict)
    task_graph: dict[str, Any] = Field(default_factory=dict)
    level1_graph: dict[str, Any] = Field(default_factory=dict)
    judgement: JudgementContract | None = None
    # R-3 event jobs on top of the steady frame DAG (None = none; see models/definition/job.py)
    jobs: list[JobSpec] | None = None

    @model_validator(mode="after")
    def _validate_edge_references(self) -> Pipeline:
        node_ids = {node.id for node in self.nodes}
        for node in self.nodes:
            unknown = sorted((node.subsystem.node_refs() if node.subsystem else set()) - node_ids)
            if unknown:
                raise ValueError(f"node {node.id}: subsystem names unknown nodes {unknown} (bind / when_node_enabled)")
        errors = job_reference_errors(self.jobs or [], node_ids, set(self.buffers))
        errors += target_reference_errors(self.judgement, self.jobs or [])
        if errors:
            raise ValueError(errors[0])
        for sink in (self.judgement.sinks if self.judgement else []):
            if sink.node not in node_ids:
                raise ValueError(f"judgement sink '{sink.node}' not found in nodes {node_ids}")
        rate = self.judgement.rate if self.judgement else None
        if rate is not None and rate.node is not None and rate.node not in node_ids:
            raise ValueError(f"judgement.rate node '{rate.node}' not found in nodes {node_ids}")
        for edge in self.edges:
            if edge.from_ not in node_ids:
                raise ValueError(
                    f"Edge source '{edge.from_}' not found in nodes {node_ids}"
                )
            if edge.to not in node_ids:
                raise ValueError(
                    f"Edge target '{edge.to}' not found in nodes {node_ids}"
                )
        return self


# ---------------------------------------------------------------------------
# Size / Axes
# ---------------------------------------------------------------------------

class SizeProfile(BaseScenarioModel):
    anchors: dict[str, str] = Field(default_factory=dict)


class DesignAxis(BaseScenarioModel):
    name: str
    enum: list[str | int | float]


# ---------------------------------------------------------------------------
# IP Requirements
# ---------------------------------------------------------------------------

class IpRequirementSpec(BaseModel):
    # extra="allow": per-IP fields are heterogeneous (isp/mfc/llc differ)
    # known limitation: typos pass silently → Phase 3 will refactor to Discriminated Union
    model_config = ConfigDict(extra="allow")
    required_throughput_mpps: float | None = None
    required_bitdepth: int | None = None
    required_features: list[str] = Field(default_factory=list)
    required_codec: str | None = None
    required_level: str | None = None
    required_allocations: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# SW Requirements
# ---------------------------------------------------------------------------

class ProfileConstraints(BaseScenarioModel):
    min_version: str | None = None
    baseline_family: list[str] = Field(default_factory=list)


class HalVersionConstraint(BaseScenarioModel):
    min_version: str | None = None
    required_capabilities: list[str] = Field(default_factory=list)


class SwRequirements(BaseScenarioModel):
    profile_constraints: ProfileConstraints | None = None
    # Each item is a single-key dict: [{"LLC_dynamic_allocation": "enabled"}, ...]
    required_features: list[dict[str, FeatureFlagValue]] = Field(default_factory=list)
    required_hal: dict[str, HalVersionConstraint] = Field(default_factory=dict)
    required_firmware: dict[str, dict[str, str]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Violation Policy
# ---------------------------------------------------------------------------

class PerRequirementPolicy(BaseScenarioModel):
    action: ViolationAction
    cap_source: str | None = None
    report_gap: bool | None = None
    emulation_strategy: str | None = None


class OverallPolicy(BaseScenarioModel):
    if_any_fail: Literal["abort_simulation", "continue_with_flag"]
    if_any_warn: Literal["abort_simulation", "continue_with_flag"] | None = None
    flag_label: str | None = None
    report_level: Literal["error", "warning", "info"] | None = None
    result_flag: str | None = None


class ViolationPolicy(BaseScenarioModel):
    classification: ViolationClassification
    # key: "default" or dotted path like "isp0.required_throughput_mpps"
    per_requirement: dict[str, PerRequirementPolicy] = Field(default_factory=dict)
    overall: OverallPolicy | None = None


# ---------------------------------------------------------------------------
# Variant
# ---------------------------------------------------------------------------

class Variant(BaseScenarioModel):
    id: str  # free-form: "UHD60-HDR10-H265" — not a DocumentId
    severity: Severity
    design_conditions: dict[str, str | int | float] = Field(default_factory=dict)
    size_overrides: dict[str, str] = Field(default_factory=dict)
    routing_switch: dict[str, Any] = Field(default_factory=dict)
    topology_patch: dict[str, Any] = Field(default_factory=dict)
    node_configs: dict[str, Any] = Field(default_factory=dict)
    buffer_overrides: dict[str, Any] = Field(default_factory=dict)
    ip_requirements: dict[str, IpRequirementSpec] = Field(default_factory=dict)
    sw_requirements: SwRequirements | None = None
    violation_policy: ViolationPolicy | None = None
    tags: list[str] = Field(default_factory=list)
    derived_from_variant: str | None = None
    design_conditions_override: dict[str, str | int | float] | None = None


# ---------------------------------------------------------------------------
# Usecase top-level pieces
# ---------------------------------------------------------------------------

class InheritancePolicy(BaseScenarioModel):
    max_depth: int = 3
    cycle_detection: Literal["required", "optional"] = "required"


class ParametricSweep(BaseScenarioModel):
    id: str
    applies_to: list[str] = Field(default_factory=list)
    axis: str
    values: list[str | int | float] = Field(default_factory=list)


class KnobExplore(BaseScenarioModel):
    """Marks an architecture knob as a power-saving option for combination exploration.

    Options are explored on top of a formal variant (never registered as variants):
    applicable when the node is enabled / design_conditions match.
    """
    when_node_enabled: str | None = None
    when: dict[str, Any] = Field(default_factory=dict)
    iq_eval: Literal["required", "not_required"] = "required"
    label: str | None = None
    note: str | None = None


class ArchKnob(BaseScenarioModel):
    condition_key: str | None = None
    default: str
    values: dict[str, dict[str, Any] | None]
    explore: KnobExplore | None = None
    description: str | None = None

    @model_validator(mode="after")
    def _default_is_a_value(self) -> ArchKnob:
        if self.default not in self.values:
            raise ValueError(f"knob default '{self.default}' not in values {sorted(self.values)}")
        return self


class KnobConstraint(Selector):
    """R-2: a valid-combination rule of the knob conditions. A variant whose effective ``design_conditions`` match
    ``when`` / ``when_node_enabled`` must also match every ``require`` key (a value or a list of values; null =
    the key is absent) - the knob ``_match`` rule. Checked by authoring compile, the strict ETL, the Write API
    and What-if."""

    id: str = Field(min_length=1)
    require: dict[str, Any] = Field(min_length=1)
    reason: str | None = None


class PowerOptionSpec(BaseScenarioModel):
    """Architecture knobs of a scenario (compiled from authoring knobs.yaml).

    Formal variants select a knob value with design_conditions.<condition_key>;
    knobs with ``explore`` are also tried as power options by combination exploration.
    """
    params: dict[str, float | int | str] = Field(default_factory=dict)
    param_rules: list[dict[str, Any]] = Field(default_factory=list)
    knobs: dict[str, ArchKnob] = Field(default_factory=dict)
    # R-2: valid combinations (None = none: export and hash unchanged)
    constraints: list[KnobConstraint] | None = None

    @model_validator(mode="after")
    def _unique_constraint_ids(self) -> PowerOptionSpec:
        ids = [c.id for c in self.constraints or []]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate power_options.constraints ids {sorted({i for i in ids if ids.count(i) > 1})}")
        return self


class UsecaseReferences(BaseScenarioModel):
    known_issues: list[DocumentId] = Field(default_factory=list)


class UsecaseMetadata(BaseScenarioModel):
    name: str
    category: list[str] = Field(default_factory=list)
    domain: list[str] = Field(default_factory=list)
    # Cross-project matching key. Scenario ids are global DB identities, so
    # projection/comparison across projects joins on this key + variant
    # design_conditions instead of the id string.
    canonical_usecase: str | None = None
    # D-06: what the scenario is for and what its review looks at, shown by the UI (Explorer, Matrix).
    # Data, not code: a scenario without them gets the UI's generic text.
    purpose: str | None = None
    review_focus: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Usecase (Definition Layer root)
# ---------------------------------------------------------------------------

class Usecase(BaseScenarioModel):
    provenance: dict[str, Any] = Field(default_factory=dict)
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["scenario.usecase"]
    project_ref: DocumentId
    metadata: UsecaseMetadata
    pipeline: Pipeline
    size_profile: SizeProfile | None = None
    design_axes: list[DesignAxis] = Field(default_factory=list)
    variants: list[Variant] = Field(default_factory=list)
    inheritance_policy: InheritancePolicy | None = None
    parametric_sweeps: list[ParametricSweep] = Field(default_factory=list)
    power_options: PowerOptionSpec | None = None
    references: UsecaseReferences | None = None

    @model_validator(mode="after")
    def _validate_no_inheritance_cycle(self) -> Usecase:
        parent_map = {
            v.id: v.derived_from_variant
            for v in self.variants
            if v.derived_from_variant is not None
        }
        for start in parent_map:
            visited: set[str] = set()
            current: str | None = start
            while current in parent_map:
                if current in visited:
                    raise ValueError(
                        f"Circular inheritance detected at variant '{current}'"
                    )
                visited.add(current)
                current = parent_map[current]
        return self

    @model_validator(mode="after")
    def _validate_job_parameters(self) -> Usecase:
        params = set((self.power_options.params if self.power_options else {}) or {})
        for i, rule in enumerate((self.power_options.param_rules if self.power_options else []) or []):
            rule_set = (rule or {}).get("set") if isinstance(rule, dict) else None
            if rule_set is not None and not (isinstance(rule_set, dict) and all(isinstance(k, str) for k in rule_set)):
                raise ValueError(f"power_options.param_rules[{i}].set must map parameter names to values")
            params |= set(rule_set or {})       # conditional params (knob param_rules)
        for job in self.pipeline.jobs or []:
            for path, value in job.numeric_fields():
                missing = sorted(expression_names(value, f"job {job.id}.{path}") - params)
                if missing:
                    raise ValueError(f"job {job.id}.{path}: unknown parameters {missing} "
                                     "(declare them in knobs.yaml params)")
            for path, name in job.param_refs():
                if name not in params:
                    raise ValueError(f"job {job.id}.{path}: unknown parameter '{name}' (declare it in knobs.yaml params)")
        return self

    @model_validator(mode="after")
    def _validate_violation_policy_node_refs(self) -> Usecase:
        node_ids = {node.id for node in self.pipeline.nodes}
        for variant in self.variants:
            if not variant.violation_policy:
                continue
            for key in variant.violation_policy.per_requirement:
                if key == "default":
                    continue
                node_ref = key.split(".")[0]
                if node_ref not in node_ids:
                    raise ValueError(
                        f"Variant '{variant.id}': violation_policy key '{key}' "
                        f"references unknown pipeline node '{node_ref}'"
                    )
        return self
