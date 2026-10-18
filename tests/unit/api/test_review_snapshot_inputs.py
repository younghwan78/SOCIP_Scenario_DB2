"""Project report assembly freezes scope, provenance and human IQ decisions."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from scenario_db.api.services import arch_exploration as service
from scenario_db.reporting.arch_report import build_snapshot


def query(rows):
    q = MagicMock()
    q.filter.return_value = q
    q.order_by.return_value = q
    q.all.return_value = rows
    return q


def test_coverage_counts_product_variants_and_keeps_physical_capture_precedence():
    db = MagicMock()
    db.query.side_effect = [query([('a', {'name': 'Camera'}), ('b', {})]),
                            query([('a', 'base', None), ('a', 'derived', 'base'), ('b', 'unexplored', None)]),
                            query([('a', 'base', {'data_origin': 'physical_capture'}),
                                   ('a', 'base', {'data_origin': 'synthetic'}), ('b', 'unexplored', {})])]
    report = {'scenarios': [{'scenario_id': 'a', 'variant_id': 'base'}]}
    cov = service._coverage(db, 'project', report, {('a', 'base'): {}}, {'references': {'base': {'mw': 500}}})
    assert cov['total'] == {'variants': 2, 'derived': 1, 'explored': 1, 'registered': 1, 'measured': 2,
                            'measured_physical': 1, 'measured_no_prediction': 1, 'reference': 1}
    assert cov['rows'][1]['explored'] == 0 and cov['rows'][0]['name'] == 'Camera'


def test_report_assembly_freezes_reference_identity_and_distinguishes_verdict_from_prediction(monkeypatch):
    from scenario_db.api.services import calibration, review, review_cpu

    db = MagicMock()
    db.get.return_value = SimpleNamespace(metadata_={'soc_ref': 'soc-exynos2600', 'board_name': 'EVT'},
                                          globals_={'default_sw_profile_ref': 'sw'})
    db.query.return_value = query([])
    snapshot = build_snapshot({'id': 'run', 'title': 'review', 'scenario_type': 'camera', 'spec': {}, 'variants': [], 'summary': {}}, {}, {})
    snapshot['scenarios'] = [{'scenario_id': 's', 'variant_id': 'v', 'fps': 30, 'spec_ok': True, 'prediction_id': 'pred',
                              'power': {'total_mw': 500}, 'inputs': {'sw_timing_source': 'assumed'}}]
    snapshot['spec_summary'].update(explored=1, spec_ok=1)
    snapshot['review_context'] = {'policy': {'sw_growth_budget': 1.2}, 'rows': [], 'battery': {'vbat': 4}}
    snapshot['calibration'] = [{'scenario_id': 's', 'variant_id': 'v', 'measured_mw': 650, 'origin': 'physical_capture',
                                'synthetic': False, 'fit': {'offsetting': False, 'worst_delta_pct': 20}}]
    refs = {'references': {'v': {'mw': 600, 'source': 'measurement', 'id': 'previous-capture', 'project_ref': 'previous'}},
            'tolerance_pct': 3, 'source_priority': ['measurement', 'prediction']}
    monkeypatch.setattr(review, 'power_references', lambda *_: refs)
    monkeypatch.setattr(review, 'thermal_watch', lambda *_: {'items': [
        {'scenario_id': 's', 'variant_id': 'v', 'current_mw': 500, 'prediction_id': 'pred',
         'plans': [{'ask_pct': 10, 'need_mw': -50, 'saving_mw': -60, 'achieved': True, 'picked': ['pending'], 'iq_pending': True}],
         'approved_plans': [{'ask_pct': 10, 'need_mw': -50, 'saving_mw': -20, 'achieved': False, 'picked': []}]}]})
    monkeypatch.setattr(calibration, 'calibration_summary', lambda *_a, **_kw: {
        'coverage': {'origin': {'physical_capture': 1}}, 'offsetting': 0, 'flat_cpu': None, 'confidence': {'grade': 'A'}, 'bias': {}})
    monkeypatch.setattr(review_cpu, 'list_cpu_snapshots', lambda *_: [])
    service._review_extras(db, snapshot, 'project', None, {('s', 'v'): {}}, {'kind': 'project'})
    assert snapshot['references']['v']['id'] == 'previous-capture'
    assert snapshot['criteria']['power']['over'] == 1 and snapshot['criteria']['power']['flip'] == ['v']
    assert snapshot['thermal']['items'][0]['approved_plans'][0]['achieved'] is False
    assert snapshot['project_conditions']['soc_name'] == 'Exynos2600' and snapshot['project_conditions']['sw_growth_budget'] == 1.2
    refs['references']['v']['mw'] = 1
    assert snapshot['references']['v']['mw'] == 600


def test_option_reviews_freeze_mixed_approval_and_rejection_per_scenario():
    db = MagicMock()
    db.query.return_value = query([SimpleNamespace(scenario_ref='a', variant_ref='shared', option_key='one', status='adopted',
                                                  note=None, updated_by=None, updated_at=None),
                                  SimpleNamespace(scenario_ref='b', variant_ref='shared', option_key='one', status='rejected',
                                                  note=None, updated_by=None, updated_at=None)])
    snap = {'power_options': [{'scenario_id': s, 'variant_id': 'shared',
                               'best': {'key': 'one'}, 'singles': [{'key': 'one'}]} for s in ('a', 'b')]}
    service._option_reviews(db, snap)
    assert [r['best']['review_status'] for r in snap['power_options']] == ['adopted', 'rejected']
    assert [r['singles'][0]['review_status'] for r in snap['power_options']] == ['adopted', 'rejected']
