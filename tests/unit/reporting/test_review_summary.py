"""Frozen management summaries keep evidence, qualifications and safe export values."""
from copy import deepcopy

import pytest

from scenario_db.reporting.review_summary import drivers_table, ladder_table, tier0, verdict_table
from scenario_db.reporting.review_verdict import kpi_list, power_verdicts
from scenario_db.reporting.risk_rules import build_risks
from tests.unit.reporting.test_review_verdict import cal, row, snap


def test_summary_renders_evidence_qualifications_iq_and_coverage_without_mutation():
    s = snap(scenarios=[row('over', sw_margin_pct=-5), row('conditional', 560), row('plain')],
             references={'over': {'mw': 600, 'source': 'measurement'},
                         'conditional': {'mw': 600, 'source': 'explicit'}, 'missing': {'mw': 700}},
             calibration=[cal('over', 650), cal('conditional', 680, 'synthetic')],
             model={'bias': {'total': {'n': 8, 'median': -10, 'verdict': 'bias'},
                             'ip': {'n': 8, 'median': -40, 'verdict': 'model_common'}}},
             domains=[{'scenario_id': 'uc', 'variant_id': 'plain', 'domain': 'CAM', 'raise_mw': 20}],
             cpu=[{'variant_id': 'plain', 'summary': {'best_at_start': {'delta_mw': -5, 'moved': ['a']}}}],
             power_options=[{'scenario_id': 'uc', 'variant_id': 'conditional', 'best': {
                 'labels': ['mode <skip>'], 'delta_mw': -60, 'iq_eval': 'required', 'review_status': 'rejected'}}],
             review_context={'policy': {'throughput_model': 'pipelined', 'kpi': [
                 {'variant_ref': 'over', 'label': 'Over <KPI>'}, {'variant_ref': 'conditional'},
                 {'variant_ref': 'missing'}, {'variant_ref': 'plain'}]}},
             spec_summary={'explored': 3, 'spec_ok': 3, 'failed': []})
    s['scenarios'][1]['distribution']['total_mw']['max'] = 700
    s['project_conditions'] = {'soc_name': 'Exynos2600', 'board_name': 'board <EVT>', 'sw_timing_source': {'assumed': 2},
                                'sw_growth': 1.1, 'sw_growth_budget': 1.2, 'sample_dvfs': True,
                                'reference': {'project_ref': 'previous', 'sources': {'measurement': 1}, 'tolerance_pct': 3}}
    s['coverage'] = {'rows': [{'name': 'Recording', 'explored': 3, 'registered': 2, 'variants': 4},
                             {'name': 'Uncovered', 'explored': 0, 'registered': 0, 'variants': 1}],
                     'total': {'variants': 5, 'explored': 3, 'registered': 2, 'measured': 2,
                               'measured_physical': 1, 'measured_no_prediction': 1, 'derived': 2}}
    s['conclusion'] = {'confidence': {'grade': 'C', 'meaning': 'verify <capture>', 'reasons': ['sample <table>']}}
    s['risk_register'] = [r | {'label': f'R-{i:02}', 'status': 'open', 'owner': '<reviewer>'}
                          for i, r in enumerate(build_risks(s), 1)]
    before = deepcopy(s)
    html = tier0(s) + verdict_table(s) + ladder_table(s) + drivers_table(s)
    assert s == before
    assert '불일치' in html and '조건부' in html and '합성 실측' in html and '보정' in html
    assert 'IQ 반려' in html and '미커버' in html and '전력 절감 검토 순서' in html
    assert 'board &lt;EVT&gt;' in html and 'Over &lt;KPI&gt;' in html and '&lt;reviewer&gt;' in html
    assert 'mode &lt;skip&gt;' in html and 'sample &lt;table&gt;' in html
    assert '파생 sub-variant 2 제외' in html and 'silicon 1' in html


@pytest.mark.parametrize('power,expected', [(600, 'ok'), (612, 'similar'), (650, 'over'), (None, 'na')])
def test_power_verdict_boundary_and_missing_prediction(power, expected):
    r = row('v', power={'total_mw': power}, distribution={})
    v = power_verdicts(snap(scenarios=[r], references={'v': {'mw': 600}}))[0]
    assert v['state'] == expected


def test_default_kpis_preserve_thermal_scenario_scope_and_do_not_duplicate_references():
    s = snap(references={'shared': {'mw': 500}, 'other': {'mw': 600}}, review_context={'policy': {'thermal_watch': [
        {'scenario_ref': 'a', 'variant_ref': 'shared'}, {'scenario_ref': 'b', 'variant_ref': 'shared'}]}})
    kpis = kpi_list(s)
    assert [(k['scenario_ref'], k['variant_ref']) for k in kpis] == [('a', 'shared'), ('b', 'shared'), (None, 'other')]


def test_report_renders_custom_comparison_and_sw_growth_evidence():
    from scenario_db.reporting.arch_report import _conditions, _sw_detail
    from scenario_db.reporting.review_summary import decomp_table, dq_table, sw_table

    r = row('v', conditions=_conditions({'fps': 30, 'resolution': 'UHD', 'sensor_mode': '<new>'}),
            sw_margin_pct=5, power={'total_mw': 500, 'cpu_mw': 100, 'hw_mw': 200, 'bw_mw': 200})
    r['sw'] = _sw_detail({'fps': 30, 'sw_margin': {'worst': {'stage': 'nrt', 'hw_ms': 10, 'sw_ms': 25, 'bottleneck_ms': 15},
                                                  'growth_tolerance': 1.1, 'growth_tested_max': 1.4},
                         'slices': [{'statistic': stat, 'runtime_scale': g, 'power': {'total_mw': power},
                                     'verdict': {'status': status}} for stat, g, power, status in [
                                         ('max', 1.4, 670, 'fail'), ('mean', 1, 400, 'ok'), ('max', 1, 500, 'ok')]]}, 'max')
    assert r['sw']['in_flight'] == 2 and [g['scale'] for g in r['sw']['growth']] == [1, 1.4]
    s = snap(scenarios=[r], references={'v': {'mw': 600, 'prev_variant': 'old-v',
                'conditions': {'fps': 30, 'resolution': 'FHD', 'sensor_mode': 'old'},
                'split': {'cpu_mw': 100, 'ip_mw': 180, 'bw_mw': 170}, 'latency_frames': 1}},
             review_context={'policy': {'kpi': [{'variant_ref': 'v'}], 'sw_growth_budget': 1.2}})
    r['latency'] = {'video_frames': 2}
    html = decomp_table(s) + sw_table(s) + dq_table(s)
    assert 'old-v' in html and 'sensor_mode old→&lt;new&gt;' in html and '해상도 FHD→UHD' in html
    assert '+20.0' in html and '+30.0' in html and '-150.0' in html and '+1.00' in html
    # growth slices are shown as the increase over the x1.0 slice (670 - 500), never the mean statistic (400)
    assert '10.0 + 25.0' in html and '×1.10' in html and '+170' in html and '×1.4 ΔmW' in html and '400' not in html
    assert '입력 데이터 확인 항목 없음' in html
