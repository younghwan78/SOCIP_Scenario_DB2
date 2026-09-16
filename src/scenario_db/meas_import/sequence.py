"""Flow-linked HW/SW events; timestamp order alone is never causality."""
from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from scenario_db.meas_import.perfetto_digest import _match_slice
from scenario_db.models.evidence.profiling import TimingStatistics

if TYPE_CHECKING:
    from scenario_db.meas_import.meta import PerfettoSpec
    from scenario_db.meas_import.perfetto_digest import PerfettoDigest, TraceQuery

SQL_SLICES = """
SELECT s.id AS slice_id, s.ts AS ts_ns, s.dur AS dur_ns,
       s.track_id, s.name AS slice_name, tr.name AS track_name,
       t.name AS thread_name, p.name AS process_name
FROM slice s
JOIN track tr ON tr.id = s.track_id
LEFT JOIN thread_track tt ON tt.id = s.track_id
LEFT JOIN thread t ON t.utid = tt.utid
LEFT JOIN process p ON p.upid = t.upid
WHERE s.dur >= 0
ORDER BY s.ts, s.id
"""
SQL_FLOWS = "SELECT slice_out, slice_in FROM flow"


def statistics(values: list[float]) -> dict:
    return TimingStatistics(min_ms=min(values), mean_ms=sum(values) / len(values),
                            max_ms=max(values), samples=len(values)).model_dump()


def extract_sequence(tp: TraceQuery, spec: PerfettoSpec, digest: PerfettoDigest) -> None:
    events: dict[int, dict] = {}
    runtimes: dict[str, list[float]] = defaultdict(list)
    nodes: dict[str, str] = {}
    rows = tp.query(SQL_SLICES)
    from scenario_db.meas_import.perfetto_digest import extract_sw_task_timing
    digest.sw_task_timing = extract_sw_task_timing(rows, spec, digest.frame_count)
    for row in rows:
        matches = [m for m in spec.task_mapping if _match_slice(row, m.match)]
        if len(matches) > 1:
            raise ValueError(f"ambiguous task mapping for slice {row['slice_id']}")
        if not matches:
            continue
        mapping = matches[0]
        sid = int(row['slice_id'])
        start, duration = int(row['ts_ns']), int(row['dur_ns'])
        if duration < 0:
            continue
        node = mapping.node_id or mapping.task
        events[sid] = dict(event_id=f"slice:{sid}", task_id=f"slice:{sid}",
                           logical_task_id=mapping.task, node_id=node,
                           task_type=mapping.execution_kind, resource_id=str(row['track_id']),
                           track_id=int(row['track_id']), start_ns=start, duration_ns=duration,
                           predecessors=[])
        if mapping.execution_kind == 'hw':
            runtimes[mapping.task].append(duration / 1_000_000)
            nodes[mapping.task] = node
    for task, values in runtimes.items():
        digest.hw_task_timing.append(dict(task=task, node_id=nodes[task],
                                         runtime_basis='wall', value_source='measured', **statistics(values)))
    if not events:
        if spec.required:
            raise ValueError('required profiling has no matched events')
        return
    origin = min(e['start_ns'] for e in events.values())
    for event in events.values():
        event['start_ms'] = (event['start_ns'] - origin) / 1_000_000
        event['duration_ms'] = event['duration_ns'] / 1_000_000
        event['end_ms'] = event['start_ms'] + event['duration_ms']
        event['time_origin_ns'] = origin
        event['value_source'] = 'measured'
    flows = {(int(r['slice_out']), int(r['slice_in'])) for r in tp.query(SQL_FLOWS)}
    for source, target in sorted(flows):
        if source in events and target in events:
            events[target]['predecessors'].append(events[source]['event_id'])
    for mapping in spec.event_latency_mapping:
        pairs = [(events[a], events[b]) for a, b in sorted(flows)
                 if a in events and b in events
                 and events[a]['logical_task_id'] == mapping.predecessor_task
                 and events[b]['logical_task_id'] == mapping.successor_task]
        values = []
        for source, target in pairs:
            anchor = source['start_ns'] + (source['duration_ns'] if mapping.source_anchor == 'end' else 0)
            delta = target['start_ns'] - anchor
            if delta < 0:
                raise ValueError(f"negative latency for {mapping.edge_id}; check anchor/overlap")
            values.append(delta / 1_000_000)
        if values:
            digest.sw_event_latency.append(dict(**mapping.model_dump(), target_anchor='start',
                                               pairing='flow', value_source='measured', **statistics(values)))
        elif spec.required:
            raise ValueError(f"no flow pairs for required latency {mapping.edge_id}")
    if spec.include_sequence:
        digest.timeline_events = list(events.values())
