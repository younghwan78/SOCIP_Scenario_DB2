from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from scenario_db.meas_import.meta import PerfettoSpec
from scenario_db.meas_import.perfetto_digest import PerfettoDigest
from scenario_db.meas_import.sequence import SQL_SLICES, extract_sequence
from scenario_db.models.evidence.profiling import MeasuredTimingProfile, TimingStatistics
from scenario_db.sim.measured_timing import apply_measured_timing


class Trace:
    def __init__(self, rows, flows):
        self.rows, self.flows = rows, flows
    def query(self, sql):
        return self.rows if sql == SQL_SLICES else self.flows


def spec():
    return PerfettoSpec(trace='capture.pftrace', include_sequence=True, required=True,
        task_mapping=[dict(task='hw', node_id='ISP', execution_kind='hw', match=dict(track='ISP')),
                      dict(task='sw', node_id='CPU', match=dict(thread='worker'))],
        event_latency_mapping=[dict(edge_id='done', predecessor_task='hw', successor_task='sw')])


def trace():
    # Two invocations; enormous absolute timestamps preserve nanosecond subtraction.
    origin = 10**18
    rows = [dict(slice_id=1, ts_ns=origin, dur_ns=2_000_000, track_id=1, track_name='ISP'),
            dict(slice_id=2, ts_ns=origin+3_000_000, dur_ns=1_000_000, track_id=2, thread_name='worker'),
            dict(slice_id=3, ts_ns=origin+10_000_000, dur_ns=4_000_000, track_id=1, track_name='ISP'),
            dict(slice_id=4, ts_ns=origin+16_000_000, dur_ns=1_000_000, track_id=2, thread_name='worker')]
    return Trace(rows, [dict(slice_out=1, slice_in=2), dict(slice_out=3, slice_in=4)])


def test_hw_tracks_sequence_and_causal_latency():
    digest = PerfettoDigest()
    extract_sequence(trace(), spec(), digest)
    hw = digest.hw_task_timing[0]
    assert (hw['min_ms'], hw['mean_ms'], hw['max_ms'], hw['samples']) == (2, 3, 4, 2)
    latency = digest.sw_event_latency[0]
    assert (latency['min_ms'], latency['mean_ms'], latency['max_ms']) == (1, 1.5, 2)
    assert len({e['task_id'] for e in digest.timeline_events}) == 4
    assert digest.timeline_events[1]['predecessors'] == ['slice:1']
    assert digest.timeline_events[-1]['start_ms'] == 16


def test_timestamp_order_is_not_a_dependency():
    tp = trace(); tp.flows = []
    with pytest.raises(ValueError, match='no flow pairs'):
        extract_sequence(tp, spec(), PerfettoDigest())


def test_ambiguous_mapping_and_negative_latency_fail():
    mapping = spec(); mapping.task_mapping.append(mapping.task_mapping[0])
    with pytest.raises(ValueError, match='ambiguous'):
        extract_sequence(trace(), mapping, PerfettoDigest())
    tp = trace(); tp.rows[1]['ts_ns'] = tp.rows[0]['ts_ns']+1
    with pytest.raises(ValueError, match='negative latency'):
        extract_sequence(tp, spec(), PerfettoDigest())


@pytest.mark.parametrize('values', [(2,1,3,2), (0,float('nan'),2,2), (0,1,float('inf'),2), (0,1,2,0)])
def test_invalid_statistics(values):
    with pytest.raises(ValidationError):
        TimingStatistics(min_ms=values[0], mean_ms=values[1], max_ms=values[2], samples=values[3])


def test_profile_is_scoped_and_does_not_mutate_baseline():
    graph = SimpleNamespace(scenario=SimpleNamespace(project_ref='proj-test'), scenario_id='uc-test',
                            variant_id='v', variant=SimpleNamespace(design_conditions={'fps':30}))
    profile = MeasuredTimingProfile(profile_id='capture-r1', revision=1, evidence_ref='meas-test',
        evidence_sha256='a'*64, project_ref='proj-test', scenario_ref='uc-test', variant_ref='v',
        design_conditions={'fps':30}, task_runtime={'ISP':dict(min_ms=2,mean_ms=3,max_ms=4,samples=2)})
    tasks = [dict(id='ISP',duration_ms=10)]
    original = deepcopy(tasks)
    changed, _ = apply_measured_timing(graph, profile, tasks, [])
    assert tasks == original and changed[0]['duration_ms'] == 3
    graph.variant.design_conditions['fps'] = 60
    with pytest.raises(ValueError, match='conditions mismatch'):
        apply_measured_timing(graph, profile, tasks, [])


def test_profile_latency_replaces_only_named_edge():
    graph = SimpleNamespace(scenario=SimpleNamespace(project_ref='proj-test'), scenario_id='uc-test',
                            variant_id='v', variant=SimpleNamespace(design_conditions={}))
    profile = MeasuredTimingProfile(profile_id='capture',revision=1,evidence_ref='meas-test',
        evidence_sha256='a'*64,project_ref='proj-test',scenario_ref='uc-test',variant_ref='v',
        design_conditions={},statistic='max',event_latency=[dict(edge_id='a-b',predecessor_task='a',
        successor_task='b',min_ms=1,mean_ms=2,max_ms=3,samples=2,pairing='flow')])
    edges = [{'from':'a','to':'b','latency_ms':99}, {'from':'c','to':'b'}]
    _, changed = apply_measured_timing(graph, profile, [], edges)
    assert changed[0]['latency_ms'] == 3 and 'latency_ms' not in changed[1]
    assert edges[0]['latency_ms'] == 99


def test_summary_import_has_no_fabricated_timeline(tmp_path):
    from pathlib import Path
    import yaml
    from scenario_db.meas_import.cli import main
    meta = Path(__file__).resolve().parents[3]/'examples/measurement-import/profiling/meta-summary.yaml'
    assert main(['--meta',str(meta),'--out',str(tmp_path),'--strict']) == 0
    evidence = yaml.safe_load(next((tmp_path/'03_evidence').glob('*.yaml')).read_text(encoding='utf-8'))
    assert 'timeline_events' not in evidence
    assert 'p95_ms' not in evidence['sw_task_timing'][0]
    assert evidence['hw_task_timing'][0]['samples'] == 100
    assert main(['--meta',str(meta),'--out',str(tmp_path),'--strict']) == 0
    changed = yaml.safe_load(meta.read_text(encoding='utf-8'))
    changed['sw_task_timing'][0]['mean_ms'] = 2.5
    local = tmp_path/'meta.yaml'; local.write_text(yaml.safe_dump(changed),encoding='utf-8')
    assert main(['--meta',str(local),'--out',str(tmp_path),'--strict']) == 1


def test_latency_only_profile_keeps_explicit_pair_mapping():
    from scenario_db.models.evidence.measurement import MeasurementEvidence
    from scenario_db.meas_import.timing_profile import build_profile
    evidence = MeasurementEvidence(id='meas-latency',schema_version='2.2',kind='evidence.measurement',
        scenario_ref='uc-test',variant_ref='v',project_ref='proj-test',provenance={},
        execution_context=dict(silicon_rev='EVT1',sw_baseline_ref='sw-test',thermal='room'),
        aggregation=dict(strategy='mean'),sw_event_latency=[dict(edge_id='a-b',predecessor_task='a',
        successor_task='b',min_ms=1,mean_ms=2,max_ms=3,samples=10,pairing='flow')])
    profile = build_profile(evidence,evidence_sha256='a'*64,profile_id='latency',revision=1,
                            design_conditions={},task_mapping={'a':'node-a','b':'node-b'})
    assert profile.task_runtime == {}
    assert profile.event_latency[0].predecessor_task == 'node-a'
