from datetime import datetime, timezone
from uuid import uuid4

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
        queries = []
        def counted(*args):
            queries.append(args[2])
        event.listen(engine, 'before_cursor_execute', counted)
        try:
            rows = cal.list_measurements(db, scenario_id=sid)
        finally:
            event.remove(engine, 'before_cursor_execute', counted)
        assert len(rows) == 2
        assert len(queries) == 3
        assert rows[0]['simulation']['id'] == f'{sid}-a-new'
        detail = cal.measurement_detail(db, f'{sid}-measurement1')
        assert detail['rail_domain_map_ref'] == sid
        assert detail['measured']['categories']['cpu'] == 10
        assert [p['id'] for p in detail['predictions']] == [f'{sid}-z-old', f'{sid}-a-new']
        assert cal._rail_map(db, None) == ({}, None)
        assert cal._rail_map(db, 'unrelated') == ({}, None)
        sw = library.sw_timing(db, scenario_id=sid)
        assert sw['tasks'][0]['mean_ms'] == [2, 2]
        assert len(sw['measured']) == 2
        db.rollback()
