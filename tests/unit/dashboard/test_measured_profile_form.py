from copy import deepcopy

import pytest
from dashboard.components.measured_profile_form import profile_payload, default_task_mapping


def profile():
    return dict(profile_id='p', revision=1, evidence_ref='meas-test', evidence_sha256='a'*64,
                project_ref='proj-test',scenario_ref='uc-test',variant_ref='v',design_conditions={'fps':30},
                capture_context=dict(silicon_rev='EVT1',sw_baseline_ref='sw-test',thermal='room'),
                task_runtime={'eis':dict(min_ms=1,mean_ms=2,max_ms=3,samples=20)})


def test_replay_uses_capture_context_and_no_inline_dvfs():
    raw = profile(); before = deepcopy(raw)
    payload = profile_payload(raw,scenario_id='uc-test',variant_id='v')
    assert payload['execution_context']['thermal'] == 'room'
    assert payload['execution_context']['method'] == 'calculation'
    assert payload['dvfs_tables'] == {} and not payload['persist']
    assert 'fps' not in payload['config']
    assert raw == before


def test_replay_rejects_wrong_scope_and_missing_context():
    with pytest.raises(ValueError,match='scenario/variant'):
        profile_payload(profile(),scenario_id='uc-other',variant_id='v')
    raw = profile(); raw['capture_context'] = {}
    with pytest.raises(ValueError,match='incomplete'):
        profile_payload(raw,scenario_id='uc-test',variant_id='v')


def test_mapping_keeps_hardware_node_identity():
    assert default_task_mapping({'hw_task_timing':[{'task':'encode','node_id':'mfc'}],
                                 'sw_task_timing':[{'task':'eis'}]}) == {'encode':'mfc','eis':'eis'}
