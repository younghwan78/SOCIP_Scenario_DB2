"""CPU review snapshots replace atomically and retain server-computed evidence."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from scenario_db.api.schemas.cpu import CpuRebalanceSweepRequest
from scenario_db.api.services import cpu, review_cpu
from scenario_db.db.models.definition import Project, Scenario
from scenario_db.db.models.evidence import Evidence
from scenario_db.db.models.exploration import ReviewCpuSnapshot
from scenario_db.exceptions import UnprocessableError


def test_concurrent_snapshot_replacement_keeps_one_active_result(engine, monkeypatch):
    token = uuid4().hex
    pid, sid, mid = (f'{prefix}-{token}' for prefix in ('project', 'scenario', 'measurement'))
    with Session(engine) as db:
        db.add(Project(id=pid, schema_version='1.0', metadata_={}, yaml_sha256='test'))
        db.flush()
        db.add(Scenario(id=sid, project_ref=pid, schema_version='1.0', metadata_={}, pipeline={}, yaml_sha256='test'))
        db.flush()
        db.add(Evidence(id=mid, scenario_ref=sid, variant_ref='v', kind='evidence.measurement', schema_version='1.0',
                        execution_context={}, aggregation={}, kpi={}, yaml_sha256='test'))
        db.commit()
    barrier = Barrier(2)

    def sweep(db, request):
        barrier.wait(timeout=15)
        return {'points': [{'growth': g, 'reference': {'total_mw': 100 * g},
                             'best': {'total_mw': 90 * g, 'moved': ['task-a']}} for g in (1, 1.5)],
                'limits': {'tolerance': 1.1, 'binding': 'opp'}}

    monkeypatch.setattr(cpu, 'run_cpu_rebalance_sweep', sweep)
    request = CpuRebalanceSweepRequest(cpu_profile_ref=mid, power_params_ref='test-topology', growths=[1, 1.5])

    def record(user):
        with Session(engine) as db:
            return review_cpu.record_cpu_snapshot(db, project_ref=pid, request=request, note=user, user=user)

    try:
        with Session(engine) as db, pytest.raises(UnprocessableError, match='not a measurement of project'):
            other = db.query(Project).filter(Project.id != pid).first()
            review_cpu.record_cpu_snapshot(db, project_ref=other.id, request=request, note=None, user=None)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(record, ['a', 'b']))
        assert len({r['id'] for r in results}) == 2
        with Session(engine) as db:
            active = review_cpu.list_cpu_snapshots(db, pid)
            history = review_cpu.list_cpu_snapshots(db, pid, include_inactive=True)
            assert len(active) == 1 and sorted(r['status'] for r in history) == ['active', 'superseded']
            assert active[0]['summary']['best_at_start']['delta_mw'] == -10
            assert active[0]['request']['cpu_profile_ref'] == mid
            review_cpu.withdraw_cpu_snapshot(db, active[0]['id'])
            assert review_cpu.list_cpu_snapshots(db, pid) == []
    finally:
        with Session(engine) as db:
            db.query(ReviewCpuSnapshot).filter_by(project_ref=pid).delete()
            db.query(Evidence).filter_by(id=mid).delete()
            db.query(Scenario).filter_by(id=sid).delete()
            db.query(Project).filter_by(id=pid).delete()
            db.commit()
