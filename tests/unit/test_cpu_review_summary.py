"""Review records and CPU BW power retain missing values and evidence provenance."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scenario_db.api.services import cpu, review_cpu


def test_review_summary_keeps_feasibility_moves_and_bw_provenance():
    sweep = {'points': [
        {'growth': 1, 'reference': {'total_mw': 100, 'feasible': True},
         'best': {'total_mw': 90, 'moved': ['sw-a'], 'mhz': {'MID': 400}}, 'bw_mw': 8, 'cpu_bw_mbs': 100},
        {'growth': 2, 'reference': {'total_mw': 200, 'feasible': False}, 'best': None, 'bw_mw': None}],
        'limits': {'tolerance': 1.1, 'binding': 'opp'}, 'bw_power': {'source': 'prediction', 'prediction_ref': 'pred'}}
    summary = review_cpu.sweep_summary(sweep)
    assert summary['growth_range'] == [1, 2]
    assert summary['best_at_start']['delta_mw'] == -10 and summary['best_at_start']['moved'] == ['sw-a']
    assert summary['points'][1]['ref_feasible'] is False and summary['points'][1]['best_mw'] is None
    assert summary['points'][1]['bw_mw'] is None
    assert summary['bw_power']['prediction_ref'] == 'pred'
    empty = review_cpu.sweep_summary({})
    assert empty['growth_range'] is None and empty['best_at_start']['delta_mw'] is None


@pytest.mark.parametrize('mbs,ip_mw,expected', [(1000, 40, 0.04), (0, 40, 0.08), (1000, None, 0.08), (1000, 0, 0)])
def test_bw_uses_registered_coefficient_including_zero_and_falls_back_only_when_missing(mbs, ip_mw, expected, monkeypatch):
    monkeypatch.setattr(cpu, 'get_evidence', lambda *_: SimpleNamespace(scenario_ref='s', variant_ref='v'))
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = SimpleNamespace(
        id='pred', metrics={'bw_ip_mbs': mbs, 'power': {'bw_ip_mw': ip_mw}, 'model_lineage': {'bw_power_model': 'fit'}})
    coeff = cpu.bw_coefficient(db, 'measurement')
    assert coeff['mw_per_mbs'] == expected
    result = cpu.with_bw_power({'cpu_bw_mbs': 500, 'reference': {'total_mw': 100}, 'best': None}, coeff)
    assert result['bw_power']['reference_total_mw'] == 100 + 500 * expected
    assert result['bw_power']['best_total_mw'] is None
    assert cpu.with_bw_power({}, coeff)['bw_power']['bw_mw'] is None


def test_sweep_worker_failure_falls_back_without_changing_point_order(monkeypatch):
    pool = MagicMock()
    pool.submit.return_value.result.side_effect = RuntimeError('worker process unavailable')
    monkeypatch.setattr(cpu, '_POOL', pool)
    monkeypatch.setattr(cpu, '_pool', lambda _: pool)
    monkeypatch.setattr(cpu, '_sweep_workers', lambda _: 3)
    monkeypatch.setattr(cpu, '_rebalance_compute', lambda g, *_: {'growth': g})
    values, workers = cpu._compute_points([(g, None, None, 30, cpu.RebalanceSpec()) for g in (1, 1.5, 2)])
    assert values == [{'growth': 1}, {'growth': 1.5}, {'growth': 2}] and workers == 1
    pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
