from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from sqlalchemy.orm import Session

from scenario_db.api.schemas.evidence import EvidenceResponse
from scenario_db.db.models.evidence import Evidence
from scenario_db.etl.loader import load_yaml_dir
from scenario_db.etl.mappers.evidence import upsert_measurement

ROOT = Path(__file__).resolve().parents[2]


def test_profiling_jsonb_roundtrip_and_revision_guard(engine):
    with engine.connect() as connection:
        tx = connection.begin()
        try:
            with Session(connection, join_transaction_mode='create_savepoint') as session:
                result = load_yaml_dir(ROOT/'db_fixtures_Exynos2600_S26Plus', session, strict=True, validate=True)
                assert result.ok
                source = next((ROOT/'db_fixtures_Exynos2600_S26Plus'/'03_evidence').glob('meas-*.yaml'))
                doc = yaml.safe_load(source.read_text(encoding='utf-8'))
                doc['id'] = 'meas-profiling-persistence'
                doc['provenance']['import_fingerprint'] = 'a'*64
                doc['hw_task_timing'] = [dict(task='isp', node_id='ISP', min_ms=1, mean_ms=2, max_ms=3, samples=10)]
                doc['sw_event_latency'] = [dict(edge_id='done', predecessor_task='isp', successor_task='eis',
                                              min_ms=0, mean_ms=1, max_ms=2, samples=10, pairing='flow')]
                doc['timeline_events'] = [dict(task_id='slice:1', start_ns=10**18, duration_ns=1)]
                upsert_measurement(doc, 'a'*64, session)
                session.commit(); session.expire_all()
                row = session.get(Evidence, doc['id'])
                response = EvidenceResponse.model_validate(row).model_dump()
                assert response['hw_task_timing'][0]['mean_ms'] == 2
                assert response['sw_event_latency'][0]['samples'] == 10
                assert response['timeline_events'][0]['start_ns'] == 10**18
                upsert_measurement(doc, 'a'*64, session)
                changed = deepcopy(doc); changed['hw_task_timing'][0]['mean_ms'] = 2.5
                with pytest.raises(ValueError, match='evidence'):
                    upsert_measurement(changed, 'b'*64, session)
        finally:
            tx.rollback()


def test_measured_profile_replay_and_exploration_api(engine, api_client):
    from scenario_db.api.deps import get_db
    from scenario_db.db.repositories.scenario_graph import load_canonical_graph
    from scenario_db.meas_import.assemble import assemble_evidence
    from scenario_db.meas_import.meta import MeasurementImportMeta
    from scenario_db.meas_import.timing_profile import build_profile
    from scenario_db.legacy_import.report import ImportReport
    from scenario_db.models.evidence.measurement import MeasurementEvidence
    with engine.connect() as connection:
        tx = connection.begin()
        previous = api_client.app.dependency_overrides[get_db]
        def test_db():
            with Session(connection, join_transaction_mode='create_savepoint') as session:
                yield session
        api_client.app.dependency_overrides[get_db] = test_db
        try:
            with Session(connection, join_transaction_mode='create_savepoint') as session:
                assert load_yaml_dir(ROOT/'db_fixtures_Exynos2600_S26Plus', session, strict=True, validate=True).ok
                meta = MeasurementImportMeta.model_validate(yaml.safe_load((ROOT/'examples/measurement-import/profiling/meta-summary.yaml').read_text(encoding='utf-8')))
                doc = assemble_evidence(meta, None, None, base_dir=ROOT, report=ImportReport())
                upsert_measurement(doc, 'b'*64, session); session.commit()
                graph = load_canonical_graph(session, meta.scenario_ref, meta.variant_ref)
                profile = build_profile(MeasurementEvidence.model_validate(doc), evidence_sha256='b'*64,
                    profile_id='capture', revision=1, design_conditions=graph.variant.design_conditions, task_mapping={'eis':'eis'})
                count = session.query(Evidence).count()
            request = dict(scenario_id=meta.scenario_ref, variant_id=meta.variant_ref,
                           execution_context={**doc['execution_context'],'method':'calculation'},
                           config={'timing_profile':profile.model_dump(mode='json')})
            response = api_client.post('/api/v1/simulation/run', json=request)
            assert response.status_code == 200, response.text
            result = response.json()
            assert result['evidence']['derived_from'] == [doc['id']]
            assert result['evidence']['run_info']['timing_profile']['revision'] == 1
            assert next(t for t in result['result']['sw_task_timing'] if t['task']=='eis')['mean_ms'] == 2
            request['config']['timing_profile']['evidence_sha256'] = 'c'*64
            assert api_client.post('/api/v1/simulation/run', json=request).status_code == 422
            preview = api_client.post('/api/v1/exploration/scenarios/preview', json=dict(
                scenario_id=meta.scenario_ref, variant_id=meta.variant_ref, project_ref=meta.project_ref,
                axes=[dict(target='sw_margin',values=[1.1])]))
            assert preview.status_code == 200, preview.text
            assert preview.json()['persisted'] is False
            assert len(preview.json()['cases']) == 2
            with Session(connection) as session:
                assert session.query(Evidence).count() == count
        finally:
            api_client.app.dependency_overrides[get_db] = previous
            tx.rollback()
