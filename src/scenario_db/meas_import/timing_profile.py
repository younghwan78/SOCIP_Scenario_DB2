"""Build a pinned timing profile from one immutable measurement capture."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import yaml

from scenario_db.models.evidence.measurement import MeasurementEvidence
from scenario_db.models.evidence.profiling import MeasuredTimingProfile, TimingStatistics


def build_profile(evidence: MeasurementEvidence, *, evidence_sha256: str, profile_id: str,
                  revision: int, design_conditions: dict, task_mapping: dict[str, str],
                  statistic: str = "mean", baseline_sha256: str | None = None) -> MeasuredTimingProfile:
    if not evidence.project_ref:
        raise ValueError("timing profile requires project_ref")
    known = {item.task for item in [*evidence.hw_task_timing, *evidence.sw_task_timing]}
    known.update(task for edge in evidence.sw_event_latency for task in (edge.predecessor_task, edge.successor_task))
    if set(task_mapping) - known:
        raise ValueError('task mapping contains unknown measurement tasks')
    runtime = {}
    for item in [*evidence.hw_task_timing, *evidence.sw_task_timing]:
        if item.task not in task_mapping:
            continue
        if getattr(item, 'value_source', None) not in (None, 'measured'):
            raise ValueError('timing profile requires measured values')
        if getattr(item, 'runtime_basis', 'wall') != 'wall':
            raise ValueError('active runtime cannot replace wall duration')
        missing = [key for key in ('min_ms', 'mean_ms', 'max_ms', 'samples') if getattr(item, key) is None]
        if missing:
            raise ValueError(f"{item.task}: measurement is missing {', '.join(missing)}; import a complete capture revision")
        node = task_mapping[item.task]
        if node in runtime:
            raise ValueError(f"multiple runtime measurements mapped to {node}; use separate task nodes")
        runtime[node] = TimingStatistics.model_validate({k: getattr(item, k) for k in
                                                        ('min_ms', 'mean_ms', 'max_ms', 'samples')})
    latencies = []
    for item in evidence.sw_event_latency:
        if item.predecessor_task in task_mapping and item.successor_task in task_mapping:
            latencies.append(item.model_copy(update=dict(predecessor_task=task_mapping[item.predecessor_task],
                                                        successor_task=task_mapping[item.successor_task])))
    if not runtime and not latencies:
        raise ValueError('profile has no mapped measured values')
    return MeasuredTimingProfile.model_validate(dict(
        profile_id=profile_id, revision=revision, evidence_ref=str(evidence.id),
        evidence_sha256=evidence_sha256, project_ref=str(evidence.project_ref),
        scenario_ref=str(evidence.scenario_ref), variant_ref=evidence.variant_ref,
        design_conditions=design_conditions, capture_context=evidence.execution_context.model_dump(mode="json", exclude_none=True),
        statistic=statistic, baseline_sha256=baseline_sha256, source_task_mapping=task_mapping, task_runtime=runtime,
        event_latency=latencies))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--selection', type=Path, required=True, help='profile_id, revision, design_conditions, task_mapping, statistic')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    raw = args.evidence.read_bytes()
    evidence = MeasurementEvidence.model_validate(yaml.safe_load(raw))
    selection = yaml.safe_load(args.selection.read_text(encoding='utf-8'))
    profile = build_profile(evidence, evidence_sha256=hashlib.sha256(raw).hexdigest(), **selection)
    content = yaml.safe_dump(profile.model_dump(mode='json'), sort_keys=False)
    if args.out.exists() and args.out.read_text(encoding='utf-8') != content:
        raise ValueError('profile revision exists with different content; select a new output/revision')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(content, encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
