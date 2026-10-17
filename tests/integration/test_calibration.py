from datetime import datetime, timezone
from uuid import uuid4

import pytest

from sqlalchemy import event
from sqlalchemy.orm import Session

from scenario_db.api.services import calibration as cal
from scenario_db.api.services import library
from scenario_db.db.models.capability import SimConfigProfile
from scenario_db.db.models.definition import Scenario, ScenarioVariant
from scenario_db.db.models.evidence import Evidence


def test_calibration_scope_recency_and_constant_query_count(engine):
    with Session(engine) as db:
        sid = 'review-cal-' + uuid4().hex
        project = db.query(Scenario.project_ref).first()[0]
        db.add(Scenario(id=sid, project_ref=project, schema_version='1.0.0',
                        metadata_={}, pipeline={}, yaml_sha256='test'))
        db.flush()
        db.add(ScenarioVariant(scenario_id=sid, id='v', design_conditions={}, node_configs={
            'sw': {'sw_timing': {'min_ms': 1, 'mean_ms': 2, 'max_ms': 3, 'value_source': 'assumed'}}}))
        profile = SimConfigProfile(id=sid, project_ref=project, schema_version='1.0.0', version=9999,
                                   status='approved', run_config={}, rail_domain_map={'ODD': 'CPU'}, yaml_sha256='test')
        db.add(profile)
        for suffix, kind, year in [('z-old', 'simulation', 2024), ('a-new', 'simulation', 2026),
                                   ('measurement1', 'measurement', 2026), ('measurement2', 'measurement', 2026)]:
            db.add(Evidence(id=f'{sid}-{suffix}', scenario_ref=sid, variant_ref='v', schema_version='1.0.0',
                            kind=f'evidence.{kind}', measured_at=datetime(year, 1, 1, tzinfo=timezone.utc) if kind == 'measurement' else None,
                            run_info={'timestamp': f'{year}-01-01T00:00:00Z'} if kind == 'simulation' else None,
                            execution_context={}, aggregation={}, kpi={'total_power_mw': 10},
                            vdd_power={'ODD': {'power_mw': 10}}, yaml_sha256='test',
                            sw_task_timing=[{'task': 'sw', 'mean_ms': 2}]))
        db.flush()
        synthetic = db.get(Evidence, f'{sid}-measurement2')
        synthetic.provenance = {'collection_method': 'synthetic_fixture', 'device_id': 'SYNTHETIC'}
        # a silicon capture records how and on which device it was taken; without it the origin is unknown
        db.get(Evidence, f'{sid}-measurement1').provenance = {'collection_method': 'power_monitor', 'device_id': 'EVT1-01'}
        db.flush()
        cov = cal.coverage(db, sid)['v']
        assert {k: cov[k] for k in ('simulation', 'measurement', 'synthetic', 'unknown', 'current_prediction')} == {
            'simulation': 2, 'measurement': 1, 'synthetic': 1, 'unknown': 0, 'current_prediction': None}
        # registration detail for the Scenario page tooltips: newest first, representative = newest real measurement
        assert [x['id'] for x in cov['simulations']] == [f'{sid}-a-new', f'{sid}-z-old']
        assert cov['simulations'][0]['shown'] and cov['simulations'][0]['at'].startswith('2026')
        assert [(x['id'], x['synthetic'], x['shown']) for x in cov['measurements']] == [
            (f'{sid}-measurement1', False, True), (f'{sid}-measurement2', True, False)]
        assert cal.coverage_summary(db)[sid] == {
            'simulation': 1, 'measurement': 1, 'synthetic': 1, 'unknown': 0, 'current_prediction': 0}
        queries = []
        def counted(*args):
            queries.append(args[2])
        event.listen(engine, 'before_cursor_execute', counted)
        try:
            rows = cal.list_measurements(db, scenario_id=sid)
        finally:
            event.remove(engine, 'before_cursor_execute', counted)
        assert len(rows) == 2
        # measurements · predictions · simulations + scenario→project · rail maps (category fit): constant, no N+1
        assert len(queries) == 5
        assert rows[0]['simulation']['category'] is None  # no CPU/IP/BW split in this fixture
        assert rows[0]['simulation']['id'] == f'{sid}-a-new'
        detail = cal.measurement_detail(db, f'{sid}-measurement1')
        assert detail['rail_domain_map_ref'] == sid
        assert detail['measured']['categories']['cpu'] == 10
        assert [p['id'] for p in detail['predictions']] == [f'{sid}-z-old', f'{sid}-a-new']
        # batched details (report generation) == one-by-one detail, in a constant number of queries
        ids = [f'{sid}-measurement1', f'{sid}-measurement2']
        queries.clear()
        event.listen(engine, 'before_cursor_execute', counted)
        try:
            batch = cal.measurement_details(db, ids)
        finally:
            event.remove(engine, 'before_cursor_execute', counted)
        assert len(queries) <= 5
        for mid in ids:
            assert batch[mid] == cal.measurement_detail(db, mid)
        # Distinct capture-time profiles are fetched once, independent of the measurement count.
        for index, mid in enumerate(ids):
            pin = f"{sid}-pin-{index}"
            db.add(SimConfigProfile(id=pin, project_ref=project, schema_version='1.0.0', version=index + 1,
                                   status='approved', run_config={}, rail_domain_map={'ODD': 'CPU'}, yaml_sha256='test'))
            evidence = db.get(Evidence, mid)
            evidence.provenance = dict(evidence.provenance or {}) | {'rail_domain_map_ref': pin}
        db.flush()
        for read in (lambda: cal.list_measurements(db, scenario_id=sid), lambda: cal.measurement_details(db, ids)):
            queries.clear()
            event.listen(engine, 'before_cursor_execute', counted)
            try:
                pinned = read()
            finally:
                event.remove(engine, 'before_cursor_execute', counted)
            rows = list(pinned.values()) if isinstance(pinned, dict) else pinned
            assert len(queries) <= 6 and all(r['rail_map_basis'] == 'pinned' for r in rows)
        assert cal._rail_map(db, None) == ({}, None)
        assert cal._rail_map(db, 'unrelated') == ({}, None)
        sw = library.sw_timing(db, scenario_id=sid)
        assert sw['tasks'][0]['mean_ms'] == [2, 2]
        assert len(sw['measured']) == 2
        assert sum(t['synthetic'] for t in sw['measured']) == 1
        db.rollback()


def test_ip_bandwidth_joins_measured_ip_scope_on_node_or_hw_name(engine):
    with Session(engine) as db:
        sid = 'review-ipbw-' + uuid4().hex
        project = db.query(Scenario.project_ref).first()[0]
        db.add(Scenario(id=sid, project_ref=project, schema_version='1.0.0', metadata_={}, pipeline={}, yaml_sha256='test'))
        db.flush()
        db.add(ScenarioVariant(scenario_id=sid, id='v', design_conditions={}, node_configs={}))
        dma = [{'node_id': 'mtnr', 'hw_name': 'MTNR', 'port': 'R0', 'direction': 'read', 'bw_mbs': 100.0},
               {'node_id': 'mtnr', 'hw_name': 'MTNR', 'port': 'R1', 'direction': 'read', 'bw_mbs': 50.0},
               {'node_id': 'mtnr', 'hw_name': 'MTNR', 'port': 'W0', 'direction': 'write', 'bw_mbs': 80.0},
               {'node_id': 'mfc_enc', 'hw_name': 'MFC', 'port': 'R', 'direction': 'read', 'bw_mbs': 40.0},
               {'node_id': 'dpu', 'hw_name': 'DPU', 'port': 'R', 'direction': 'read', 'bw_mbs': 20.0}]
        db.add(Evidence(id=f'{sid}-sim', scenario_ref=sid, variant_ref='v', schema_version='1.0.0', kind='evidence.simulation',
                        run_info={'timestamp': '2026-10-01T00:00:00Z', 'tool_version': '0.1.0'}, execution_context={}, aggregation={},
                        kpi={}, dma_breakdown=dma, yaml_sha256='test'))
        obs = lambda m, ref, v: {'metric_id': m, 'scope': {'kind': 'ip', 'ref': ref}, 'unit': 'MB/s', 'stats': {'mean': v, 'p95': v * 1.1}}  # noqa: E731
        db.add(Evidence(id=f'{sid}-meas', scenario_ref=sid, variant_ref='v', schema_version='1.0.0', kind='evidence.measurement',
                        measured_at=datetime(2026, 10, 2, tzinfo=timezone.utc), execution_context={'silicon_rev': 'EVT1'}, aggregation={}, kpi={},
                        provenance={'collection_method': 'synthetic_fixture', 'device_id': 'SYNTHETIC'}, yaml_sha256='test',
                        metric_observations=[obs('bandwidth.read', 'MTNR', 120.0), obs('bandwidth.write', 'MTNR', 100.0),
                                             obs('bandwidth.read', 'MFC', 50.0), obs('bandwidth.read', 'DPU', 25.0), obs('bandwidth.read', 'GPU', 9.0)]))
        db.flush()
        out = cal.ip_bandwidth(db, sid, 'v')
        rows = {r['node']: r for r in out['rows']}
        assert rows['mtnr']['pred'] == {'read': 150.0, 'write': 80.0, 'total': 230.0} and rows['mtnr']['ports'] == 3
        assert rows['mtnr']['meas']['read'] == 120.0 and rows['mtnr']['delta_pct']['read'] == 25.0
        assert rows['mtnr']['delta_pct']['total'] == round(100 * (230 - 220) / 220, 2)
        assert rows['mfc_enc']['measured_ref'] == 'MFC'           # joined on hw_name when the node id differs
        assert rows['dpu']['meas']['total'] == 25.0                 # write not measured, model has no write either
        assert out['unmatched'] == [{'ref': 'GPU', 'read': 9.0}]
        assert out['measurement']['id'] == f'{sid}-meas' and out['measurement']['synthetic'] is True
        assert out['simulation']['id'] == f'{sid}-sim'
        comp = out['comparability']                                # PIPE-05: synthetic is a reference comparison only
        assert comp['equivalent'] is False and any('합성' in r for r in comp['reasons']) and comp['statistic'] == 'mean'
        for suffix, origin, year in [('physical', 'physical_capture', 2024), ('unknown', 'unknown', 2026)]:
            db.add(Evidence(id=f'{sid}-{suffix}', scenario_ref=sid, variant_ref='v', schema_version='1.0.0',
                            kind='evidence.measurement', measured_at=datetime(year, 1, 1, tzinfo=timezone.utc),
                            provenance={'data_origin': origin}, execution_context={}, aggregation={},
                            kpi={'total_power_mw': 10}, yaml_sha256='test',
                            metric_observations=[obs('bandwidth.read', 'MTNR', 120.0)]))
        db.flush()
        # Unknown provenance must not displace an older physical capture.
        assert cal.ip_bandwidth(db, sid, 'v')['measurement']['id'] == f'{sid}-physical'
        assert next(m for m in cal.coverage(db, sid)['v']['measurements'] if m['shown'])['id'] == f'{sid}-physical'


def test_calibration_summary_representative_capture_and_bias(engine):
    from scenario_db.db.models.exploration import ArchExplorationRun, Prediction

    with Session(engine) as db:
        sid = 'review-sum-' + uuid4().hex
        project = db.query(Scenario.project_ref).first()[0]
        db.add(Scenario(id=sid, project_ref=project, schema_version='1.0.0', metadata_={}, pipeline={}, yaml_sha256='test'))
        db.flush()
        for v in ('v1', 'v2', 'v3'):
            db.add(ScenarioVariant(scenario_id=sid, id=v, design_conditions={}))
        rails = {'B2S2_VDD_CPUCL1_MID_LF0_L': {'power_mw': 260}, 'B5_6S1_VDD_CAM_L': {'power_mw': 200},
                 'B5S4_VDDMIF_AP_L': {'power_mw': 150}, 'B6S2_VDD_SRAM_L': {'power_mw': 60}}
        caps = [('v1', 'silicon', 2025, {'collection_method': 'power_monitor', 'device_id': 'EVT1-01'}),
                ('v1', 'synth-newer', 2026, {'collection_method': 'synthetic_fixture', 'device_id': 'SYNTHETIC'}),
                ('v2', 'synth', 2026, {'collection_method': 'synthetic_fixture', 'device_id': 'SYNTHETIC'}),
                ('v3', 'no-total', 2026, {'collection_method': 'synthetic_fixture', 'device_id': 'SYNTHETIC'})]
        for v, tag, year, prov in caps:
            db.add(Evidence(id=f'{sid}-{v}-{tag}', scenario_ref=sid, variant_ref=v, schema_version='1.0.0',
                            kind='evidence.measurement', measured_at=datetime(year, 1, 1, tzinfo=timezone.utc),
                            execution_context={}, aggregation={}, provenance=prov, yaml_sha256='test',
                            kpi={'total_power_mw': 670, 'fps_effective': 30} if tag != 'no-total' else {},
                            vdd_power=rails))
        db.add(ArchExplorationRun(id=f'run-{sid}', title='t', scenario_type='test', project_ref=project, spec={},
                                  variants=[], errors=[], summary={}, engine_rev='test', input_hash='test'))
        db.flush()
        for v in ('v1', 'v2'):
            db.add(Prediction(id=f'pred-{sid}-{v}', scenario_ref=sid, variant_ref=v, project_ref=project, status='current',
                              exploration_run_ref=f'run-{sid}', case_key='base', selection_rule='auto:min-power',
                              selected_by='auto', input_hash='test',
                              metrics={'power': {'total_mw': 550, 'cpu_mw': 110, 'hw_mw': 165, 'bw_mw': 275}}))
        db.flush()
        s = cal.calibration_summary(db, scenario_id=sid)
        assert s['coverage']['variants'] == 3 and s['coverage']['with_prediction'] == 2
        assert s['coverage']['compared'] == 2 and s['coverage']['captures'] == 4
        rows = {r['variant_id']: r for r in s['rows']}
        # silicon beats a newer synthetic capture; a capture without total is not representative
        assert rows['v1']['measurement_id'] == f'{sid}-v1-silicon' and rows['v1']['captures'] == 2
        assert rows['v1']['origin'] == 'physical_capture' and 'v3' not in rows
        d = rows['v1']['delta_pct']
        assert round(d['cpu'], 1) == -57.7 and round(d['bw'], 1) == 83.3 and round(d['total'], 1) == -17.9
        assert s['bias']['cpu']['median'] == -57.69 and s['bias']['bw']['sign'] == 1
        assert s['confidence']['real'] == 1 and s['confidence']['grade'] == 'B'
        assert [p['label'] for p in s['correction']['previews']][0] == '현재'
        # CAL-09 / CAL-11: rail groups per compared variant and their bias (no IP node split → one IP group)
        assert {g['category'] for g in rows['v1']['rail_groups']} >= {'cpu', 'bw'}
        assert {b['key'] for b in s['rail_bias']} >= {'cpu', 'bw'} and 'latency_bias' in s
        only_real = cal.calibration_summary(db, scenario_id=sid, include_synthetic=False)
        assert only_real['coverage']['compared'] == 1
        from scenario_db.exceptions import NotFoundError
        with pytest.raises(NotFoundError):
            cal.calibration_summary(db, scenario_id=sid, project_ref='another-project')
        assert cal.list_measurements(db, scenario_id=sid, project_ref='another-project') == []


def test_sw_drilldown_uses_frozen_prediction_timing_and_growth(engine):
    from scenario_db.db.models.exploration import ArchExplorationRun, Prediction

    with Session(engine) as db:
        sid = 'frozen-sw-' + uuid4().hex
        project = db.query(Scenario.project_ref).first()[0]
        db.add(Scenario(id=sid, project_ref=project, schema_version='1.0', metadata_={}, pipeline={}, yaml_sha256='test'))
        db.flush()
        db.add(ScenarioVariant(scenario_id=sid, id='v', design_conditions={},
                               node_configs={'sw': {'sw_timing': {'mean_ms': 99}}}))
        db.add(Evidence(id=sid, scenario_ref=sid, variant_ref='v', kind='evidence.measurement', schema_version='1.0',
                        execution_context={}, aggregation={}, kpi={'total_power_mw': 10}, yaml_sha256='test',
                        sw_task_timing=[{'task': 'sw', 'mean_ms': 2, 'p95_ms': 3}]))
        run = ArchExplorationRun(id=sid, title='frozen', scenario_type='test', project_ref=project,
                                 variants=[{'scenario_id': sid, 'variant_id': 'v', 'input_sections': {'variant_doc': 'frozen'}}],
                                 spec={'manifest': {'blobs': {'frozen': {'node_configs': {'sw': {'sw_timing': {'mean_ms': 1}}}}}}},
                                 errors=[], summary={}, engine_rev='test', input_hash='test')
        db.add(run)
        db.flush()
        db.add(Prediction(id=sid, scenario_ref=sid, variant_ref='v', project_ref=project, status='current',
                          exploration_run_ref=sid, case_key='base', selection_rule='auto:min-power', selected_by='auto',
                          input_hash='test', metrics={'statistic': 'mean', 'runtime_scale': 2, 'power': {'total_mw': 10}}))
        db.flush()
        sw = cal.measurement_detail_view(db, sid)['drilldown']['sw']
        assert sw['rows'][0]['assumed_ms'] == 2 and sw['rows'][0]['delta_ms'] == 1
        # A historical run without frozen inputs cannot claim today's definition was its assumption.
        run.spec = {}
        db.flush()
        sw = cal.measurement_detail_view(db, sid)['drilldown']['sw']
        assert sw['rows'][0]['assumed_ms'] is None and sw['rows'][0]['status'] == 'measured_only'
