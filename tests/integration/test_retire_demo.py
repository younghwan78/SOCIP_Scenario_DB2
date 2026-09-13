from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from scenario_db.db.models import Project, Scenario, SocPlatform, SwProfile
from scenario_db.etl.loader import load_yaml_dir
from scenario_db.etl.retire_demo import retire_demo


def test_retire_demo_preserves_runtime_and_is_idempotent(engine, tmp_path):
    # Roll back this test so the shared demo integration fixture stays unchanged.
    with engine.connect() as connection, connection.begin() as transaction:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            result = load_yaml_dir(Path("db_fixtures_Exynos2600_S26Plus"), db, validate=True, strict=True)
            assert result.ok
            camera = db.get(Scenario, "uc-camera-recording").pipeline
            counts = retire_demo(db)
            assert counts["soc_platforms"] == 1
            assert db.get(SocPlatform, "soc-exynos2500") is not None
            archive = tmp_path / "retired.json"
            assert retire_demo(db, backup=archive) == counts
            db.expire_all()
            assert db.get(SocPlatform, "soc-exynos2500") is None
            assert db.get(Project, "proj-sm-s947b") is not None
            assert db.get(Scenario, "uc-camera-recording").pipeline == camera
            assert db.get(SwProfile, "sw-vendor-v1.2.3") is not None
            assert archive.is_file()
            assert retire_demo(db) == {}
            with pytest.raises(FileExistsError):
                retire_demo(db, backup=archive)
            assert list(db.scalars(select(SocPlatform.id))) == ["soc-exynos2600"]
        transaction.rollback()


def test_retirement_refuses_cross_project_dependencies(engine):
    from scenario_db.db.models import Waiver
    with engine.connect() as connection, connection.begin() as transaction:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            load_yaml_dir(Path("db_fixtures_Exynos2600_S26Plus"), db, validate=True, strict=True)
            waiver = db.get(Waiver, "waiver-LLC-thrashing-UHD60-EVT0-20260417")
            waiver.scope = {"variant_scope": {"scenario_ref": "uc-camera-recording"}}
            db.flush()
            with pytest.raises(ValueError, match="Cross-project reference"):
                retire_demo(db)
            assert db.get(SocPlatform, "soc-exynos2500") is not None
        transaction.rollback()
