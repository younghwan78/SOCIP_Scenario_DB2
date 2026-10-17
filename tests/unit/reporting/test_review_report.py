"""Review reports retain frozen criteria, risk lifecycle and safe offline HTML."""
from copy import deepcopy

from scenario_db.reporting.arch_report import build_snapshot, render_html


def snapshot():
    snap = build_snapshot({'id': 'EXP-1', 'title': 'review', 'scenario_type': 'camera',
                           'project_ref': 'project', 'spec': {}, 'variants': [], 'summary': {}}, {}, {})
    snap['scope'] = {'kind': 'project', 'project_ref': 'project', 'runs': [
        {'id': 'EXP-1', 'title': 'source <capture>', 'created_at': '2026-10-17', 'current': 2, 'variants': 3}]}
    snap['basis'] = {'throughput_model': 'pipelined', 'policy_declared': True,
                     'dvfs_table_ref': 'dvfs-sample', 'sample_dvfs': True, 'engine_rev': 'engine-1'}
    snap['criteria'] = {'fps': {'ok': 2, 'total': 3, 'fail': ['cam-rec-failed'], 'basis': 'pipelined'},
                        'power': {'total': 3, 'ok': 1, 'similar': 0, 'over': 1, 'missing': ['no-prediction'],
                                  'sample': True, 'tolerance_pct': 5},
                        'thermal': {'items': [{'variant_id': 'cam-rec-hot', 'reach10': False, 'reach20': False}],
                                    'unassessed': 0}}
    snap['conclusion']['actions'] = [{'action': 'offload <task>', 'target': 'cam-rec-hot', 'delta_mw': -20,
                                      'delta_pct': -10, 'basis': 'model', 'check': 'IQ'}]
    snap['risk_register'] = []
    return snap


def risk(i, **overrides):
    return {'label': f'R-{i:02d}', 'title': f'risk-{i}', 'detail': 'evidence <capture>', 'category': 'SW',
            'severity': 'high', 'affected': ['cam-rec-a', 'cam-rec-b'], 'mitigation': 'offload',
            'owner': 'reviewer', 'note': 'verify <silicon>', 'status': 'open', 'trend': 'ongoing'} | overrides


def test_project_html_preserves_criteria_and_escapes_review_annotations():
    snap = snapshot()
    snap['risk_register'] = [risk(i) for i in range(1, 8)] + [
        risk(8, status='closed', title='closed-risk'),
        risk(9, status='accepted', title='accepted-risk'),
        risk(10, trend='resolve_candidate', title='resolved-risk')]
    before = deepcopy(snap)
    html = render_html('Review <script>alert(1)</script>', snap)
    assert snap == before
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert 'source &lt;capture&gt;' in html and 'verify &lt;silicon&gt;' in html
    assert 'offload &lt;task&gt;' in html and 'pipelined 기준' in html
    assert '미달 1건' in html and '예측 없음 1' in html
    assert '생략한 절' in html and 'SW margin 계산 결과 없음' in html
    top = html.split('Top risk</h3>')[1].split('</section>')[0]
    assert 'risk-1' in top and 'risk-5' in top and 'risk-6' not in top
    assert '외 2건' in top
    assert all(name not in top for name in ('closed-risk', 'accepted-risk', 'resolved-risk'))
    # Closed/accepted rows remain visible in the complete, frozen audit register.
    assert 'closed-risk' in html and 'accepted-risk' in html and '해소 후보' in html


def test_report_renders_model_bias_and_assessed_and_unassessed_thermal_targets():
    snap = snapshot()
    snap['model'] = {'coverage': {'compared': 3, 'origin': {'physical_capture': 2, 'synthetic': 1}},
                     'offsetting': 1, 'bias': {'bw': {'median': 40, 'same_sign_pct': 100,
                                                   'within10': 0, 'n': 3, 'label': '모델 공통 오차'}},
                     'flat_cpu': {'count': 3, 'n': 3, 'mw_at_base_fps': 120, 'base_fps': 30}}
    snap['thermal'] = {'items': [
        {'variant_id': 'cam-rec-hot', 'current_mw': 200, 'reference': {'delta_pct': 8, 'status': 'over'},
         'plans': [{'ask_pct': 10, 'need_mw': -20, 'saving_mw': -25, 'achieved': True, 'picked': ['option <A>']},
                   {'ask_pct': 20, 'need_mw': -40, 'saving_mw': -25, 'achieved': False, 'picked': []}]},
        {'variant_id': 'cam-rec-unknown', 'current_mw': None, 'plans': [], 'notes': ['no <prediction>']}]}
    html = render_html('Review', snap)
    assert 'silicon 2' in html and '합성 1' in html and '모델 공통 오차' in html
    assert 'SW 부하 미반영 flat 항' in html
    assert 'option &lt;A&gt;' in html and 'no &lt;prediction&gt;' in html
    assert '전과제 대비' in html and '−20%' in html


def test_report_explains_empty_risks_and_unassessed_criteria():
    snap = snapshot()
    snap['scope'] = {'kind': 'run'}
    snap['criteria']['fps']['fail'] = []
    snap['criteria']['power'].update(over=0, similar=0, missing=[])
    snap['criteria']['thermal'] = {'items': [], 'unassessed': 1}
    snap['thermal'] = {'items': [], 'reason': 'missing thermal policy'}
    snap['conclusion']['actions'][0]['delta_mw'] = None
    html = render_html('Review', snap)
    assert '열린 risk 없음' in html and '모든 평가 variant가 fps 만족' in html
    assert '미평가' in html and 'missing thermal policy' in html
    assert '과제 register에 반영되지 않은' in html


def test_portfolio_uses_frozen_criteria_and_excludes_closed_or_resolved_risks():
    from scenario_db.api.services.arch_exploration import _report_summary

    snap = snapshot()
    snap['risk_register'] = [risk(1), risk(2, status='accepted'), risk(3, auto_state='resolve_candidate')]
    before = deepcopy(snap)
    summary = _report_summary(snap)
    assert summary['risks'] == {'critical': 0, 'high': 1, 'medium': 0, 'info': 0}
    assert summary['fps'] == {'ok': 2, 'total': 3}
    assert summary['power']['missing'] == 1
    assert summary['thermal'] == {'items': 1, 'reach10': 0}
    assert summary['confidence'] == 'C' and snap == before
    assert _report_summary({}) is None  # legacy run reports remain readable
