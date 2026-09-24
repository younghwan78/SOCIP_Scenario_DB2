"""Import producer-curated camera Markdown; summaries remain authoritative."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, model_validator

from scenario_db.models.common import BaseScenarioModel
from scenario_db.models.evidence.camera import (
    CameraPipeline,
    CameraPath,
    ProfilingMetadata,
    StageTiming,
)
from scenario_db.models.evidence.common import ExecutionContext
from scenario_db.models.evidence.measurement import MeasurementEvidence, SwTaskTiming
from scenario_db.models.evidence.profiling import HwTaskTiming, SwEventLatency


class UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        if any(not isinstance(key, str) for key in keys):
            raise ValueError("camera YAML keys must be strings")
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate YAML key")
        return super().construct_mapping(node, deep=deep)


class CameraStatistics(BaseScenarioModel):
    sw_task_timing: list[SwTaskTiming] = Field(default_factory=list)
    hw_task_timing: list[HwTaskTiming] = Field(default_factory=list)
    sw_event_latency: list[dict] = Field(default_factory=list)
    stage_timing: list[StageTiming] = Field(default_factory=list)


class CameraBundle(BaseScenarioModel):
    format_version: Literal["camera-profile-v1"]
    id: str
    project_ref: str
    scenario_ref: str
    variant_ref: str
    measured_at: str
    execution_context: ExecutionContext
    generator_version: str = Field(min_length=1)
    measurement_scope: str = Field(min_length=1)
    workload: dict
    execution_path: CameraPath
    pipeline_model: dict
    statistics: CameraStatistics
    semantic_trace: str | None = None
    supersedes_evidence_ref: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def measured_context(self):
        if datetime.fromisoformat(self.measured_at).utcoffset() is None:
            raise ValueError("measured_at requires timezone")
        if self.execution_context.method not in (None, "measurement"):
            raise ValueError("camera capture requires measurement context")
        return self


def _normalize(value):
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, dict):
        result = {k: _normalize(v) for k, v in value.items()}
        if "avg_ms" in result:
            avg = result.pop("avg_ms")
            if "mean_ms" in result and result["mean_ms"] != avg:
                raise ValueError("avg_ms and mean_ms disagree")
            result["mean_ms"] = avg
        return result
    return value


def parse_markdown(text: str) -> CameraBundle:
    if len(text.encode("utf-8")) > 1_000_000:
        raise ValueError("camera Markdown exceeds 1 MB")
    blocks = re.findall(r"^```yaml camera-profile-v1\s*\n(.*?)^```\s*$", text, re.M | re.S)
    if len(blocks) != 1:
        raise ValueError("expected exactly one yaml camera-profile-v1 block")
    # Producer format needs neither anchors nor aliases; disallow expansion/recursive data.
    try:
        tokens = list(yaml.scan(blocks[0]))
        if any(isinstance(t, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for t in tokens):
            raise ValueError("YAML aliases/anchors are unsupported")
        raw = yaml.load(blocks[0], Loader=UniqueLoader)
    except (yaml.YAMLError, RecursionError, TypeError) as exc:
        raise ValueError("invalid camera YAML") from exc
    if not isinstance(raw, dict):
        raise ValueError("camera block must be a mapping")
    return CameraBundle.model_validate(_normalize(raw))


def canonical_hash(evidence: MeasurementEvidence) -> str:
    raw = evidence.model_dump(mode="json", exclude_none=True)
    raw["provenance"].pop("import_fingerprint", None)
    return hashlib.sha256(
        json.dumps(raw, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def assemble_camera(bundle: CameraBundle) -> MeasurementEvidence:
    if "execution_path" in bundle.pipeline_model:
        raise ValueError("execution_path must only be declared at bundle root")
    pipeline = CameraPipeline.model_validate(
        {**bundle.pipeline_model, "execution_path": bundle.execution_path.model_dump()}
    )
    tasks = {t.task_id: t for t in pipeline.tasks}
    sw = []
    for stat in bundle.statistics.sw_task_timing:
        if stat.value_source not in (None, "measured"):
            raise ValueError("camera import requires measured SW values")
        task = tasks.get(stat.task)
        if task is None:
            raise ValueError(f"unknown SW task: {stat.task}")
        if stat.timing_scope is not None and stat.timing_scope != task.timing_scope:
            raise ValueError("conflicting SW timing scope")
        if stat.includes_task_ids and stat.includes_task_ids != task.includes_task_ids:
            raise ValueError("conflicting included tasks")
        sw.append(
            {
                **stat.model_dump(exclude_none=True),
                "timing_scope": task.timing_scope,
                "includes_task_ids": task.includes_task_ids,
                "value_source": "measured",
            }
        )
    edges = {e.edge_id: e for e in pipeline.edges}
    latencies = []
    for raw in bundle.statistics.sw_event_latency:
        edge = edges.get(raw.get("edge_id"))
        if edge is None:
            raise ValueError("unknown latency edge")
        expected = dict(
            predecessor_task=edge.source_task_id,
            successor_task=edge.target_task_id,
            source_anchor=edge.source_anchor,
            target_anchor=edge.target_anchor,
        )
        if any(k in raw and raw[k] != v for k, v in expected.items()):
            raise ValueError("latency endpoints/anchors disagree")
        latencies.append(
            SwEventLatency.model_validate({"pairing": "producer_defined", **raw, **expected})
        )
    context = bundle.execution_context.model_copy(update={"method": "measurement"})
    evidence = MeasurementEvidence.model_validate(
        dict(
            id=bundle.id,
            schema_version="2.2",
            kind="evidence.measurement",
            project_ref=bundle.project_ref,
            scenario_ref=bundle.scenario_ref,
            variant_ref=bundle.variant_ref,
            measured_at=bundle.measured_at,
            execution_context=context,
            execution_path_id=bundle.execution_path.id,
            pipeline_model=pipeline,
            profiling_metadata=ProfilingMetadata(
                generator_version=bundle.generator_version,
                measurement_scope=bundle.measurement_scope,
                workload=bundle.workload,
                notes=bundle.notes,
            ),
            provenance=dict(
                collection_method="semantic_camera",
                collection_tool_versions={"semantic_generator": bundle.generator_version},
            ),
            aggregation={"strategy": "producer_summary"},
            derived_from=[bundle.supersedes_evidence_ref] if bundle.supersedes_evidence_ref else [],
            sw_task_timing=sw,
            hw_task_timing=bundle.statistics.hw_task_timing,
            sw_event_latency=latencies,
            stage_timing=bundle.statistics.stage_timing,
        )
    )
    return stamp(evidence)


def stamp(evidence):
    evidence.provenance.import_fingerprint = canonical_hash(evidence)
    return evidence


def bind_graph(evidence, graph):
    from scenario_db.sim.measured_timing import baseline_fingerprint

    if (evidence.project_ref, evidence.scenario_ref, evidence.variant_ref) != (
        graph.scenario.project_ref,
        graph.scenario_id,
        graph.variant_id,
    ):
        raise ValueError("camera scope mismatch")
    model = evidence.pipeline_model
    nodes = {str(n["id"]): n for n in graph.pipeline_nodes}
    for task in model.tasks:
        if task.task_id not in model.execution_path.enabled_task_ids:
            continue
        if task.observation_only:
            continue
        if not task.node_refs or set(task.node_refs) - nodes.keys():
            raise ValueError(f"{task.task_id}: missing/unknown active node_refs")
        for ref in task.node_refs:
            is_sw = nodes[ref].get("role") == "sw_task"
            if task.kind == "sw" and not is_sw or task.kind == "hw" and is_sw:
                raise ValueError(f"{task.task_id}: canonical node kind mismatch")
        if set(task.includes_task_ids) - (nodes.keys() | {t.task_id for t in model.tasks}):
            raise ValueError("unknown included task")
    declared = {t.task_id: t for t in model.tasks}
    base_ids = {str(n["id"]) for n in (graph.scenario.pipeline or {}).get("nodes", [])}
    for disabled in model.execution_path.disabled_tasks:
        task = declared.get(disabled.task_id)
        refs = set(task.node_refs) if task else {disabled.task_id}
        if refs & nodes.keys():
            raise ValueError(
                "disabled semantic task is active in canonical variant; select the correct path variant"
            )
        if refs - base_ids:
            raise ValueError("unknown disabled task; provide canonical mapping")
    for key, value in evidence.profiling_metadata.workload.items():
        actual = (graph.variant.design_conditions or {}).get(key)
        if actual is None or actual != value:
            raise ValueError(f"workload differs from resolved design_conditions: {key}")
    binding = {"sha256": baseline_fingerprint(graph), "bound_at": "import"}
    if model.model_binding and model.model_binding != binding:
        raise ValueError("model binding mismatch")
    model.model_binding = binding
    return stamp(evidence)


def commit_camera(db, evidence, expected_hash):
    from scenario_db.db.models.evidence import Evidence
    from scenario_db.db.models.capability import SwProfile
    from scenario_db.db.repositories.scenario_graph import load_canonical_graph
    from scenario_db.etl.mappers.evidence import upsert_measurement

    evidence = evidence.model_copy(deep=True)
    bind_graph(evidence, load_canonical_graph(db, evidence.scenario_ref, evidence.variant_ref))
    digest = canonical_hash(evidence)
    if digest != expected_hash:
        raise ValueError("preview hash changed; preview again")
    if db.get(SwProfile, str(evidence.execution_context.sw_baseline_ref)) is None:
        raise ValueError("SW baseline must be registered")
    for ref in evidence.derived_from:
        parent = db.get(Evidence, str(ref))
        if parent is None or (parent.project_ref, parent.scenario_ref, parent.variant_ref) != (
            evidence.project_ref,
            evidence.scenario_ref,
            evidence.variant_ref,
        ):
            raise ValueError("superseded evidence scope mismatch")
    existing = db.get(Evidence, str(evidence.id))
    if existing:
        if existing.yaml_sha256 != digest:
            raise ValueError("evidence id conflict; use a new id")
        return {"id": str(evidence.id), "status": "unchanged", "sha256": digest}
    upsert_measurement(evidence.model_dump(mode="json"), digest, db)
    db.flush()
    return {"id": str(evidence.id), "status": "created", "sha256": digest}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument(
        "--out", type=Path, help="Optional YAML output with --commit; required otherwise"
    )
    parser.add_argument(
        "--commit", action="store_true", help="Preview and persist through the authenticated API"
    )
    parser.add_argument(
        "--api-base",
        default=os.environ.get("SCENARIODB_API_BASE", "http://127.0.0.1:18000/api/v1"),
        help="API root for --commit (default: SCENARIODB_API_BASE or local API)",
    )
    parser.add_argument("--trace-window-start-ms", type=float, default=0)
    parser.add_argument("--trace-window-ms", type=float, default=100)
    args = parser.parse_args(argv)
    if not args.commit and args.out is None:
        parser.error("--out is required unless --commit is selected")
    bundle = parse_markdown(args.markdown.read_text(encoding="utf-8-sig"))
    evidence = assemble_camera(bundle)
    if bundle.semantic_trace:
        from scenario_db.meas_import.camera_trace import attach_trace

        base = args.markdown.parent.resolve()
        trace = (base / bundle.semantic_trace).resolve()
        if not trace.is_relative_to(base):
            raise ValueError("semantic trace must stay inside bundle directory")
        attach_trace(
            evidence, trace, start_ms=args.trace_window_start_ms, window_ms=args.trace_window_ms
        )
    output = yaml.safe_dump(evidence.model_dump(mode="json", exclude_none=True), sort_keys=False)
    if args.out is not None:
        if args.out.exists() and args.out.read_text(encoding="utf-8") != output:
            raise ValueError("output exists with different content")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
    result = {"id": str(evidence.id), "sha256": canonical_hash(evidence), "persisted": False}
    if args.commit:
        from scenario_db.meas_import.camera_api import commit_via_api

        try:
            result = commit_via_api(evidence, args.api_base)
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
