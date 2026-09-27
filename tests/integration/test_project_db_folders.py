"""Project DB folders coexist without replacing parent sensor/SW definitions."""
from copy import deepcopy
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from scenario_db.db.models.evidence import Evidence
from scenario_db.db.models.sensor import SensorCatalog
from scenario_db.etl.loader import load_yaml_dir

ROOT = Path(__file__).resolve().parents[2]


def test_project_db_folders_strict_load_and_preserve_parent(engine):
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(connection, join_transaction_mode='create_savepoint') as session:
                assert load_yaml_dir(ROOT / 'db_Exynos2600_SM-S947B', session,
                                     strict=True, validate=True).ok
                parent = session.get(SensorCatalog, 'sensor-gng-m2s')
                before = deepcopy(parent.document)
                child_db = ROOT / 'db_Exynos2700_SM-S957B'
                assert load_yaml_dir(child_db, session, strict=True, validate=True).ok
                session.expire_all()
                assert session.get(SensorCatalog, 'sensor-gng-m2s').document == before
                assert session.get(SensorCatalog, 'sensor-gng-m2s-s5e9975') is not None
                evidence = session.scalars(select(Evidence).where(
                    Evidence.scenario_ref == 'uc-cam-recording-e2700')).all()
                assert len(evidence) == 35
                assert all(e.project_ref == 'proj-sm-s957b' for e in evidence)
                assert all(e.sw_baseline_ref == 'sw-vendor-v1.2.3-s5e9975' for e in evidence)
                assert load_yaml_dir(child_db, session, strict=True, validate=True).ok
        finally:
            transaction.rollback()
