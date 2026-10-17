"""Legacy revision normalization must be bounded to verified collaboration schemas."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from scenario_db.db import migration_compat as compat

CANONICAL = "0024_prediction_collaboration"
TABLES = {"prediction_notes", "prediction_comments", "whatif_experiments"}


@pytest.fixture
def migration_db(monkeypatch):
    db = MagicMock()
    inspector = MagicMock()
    inspector.has_table.return_value = True
    inspector.get_table_names.return_value = TABLES
    monkeypatch.setattr(compat, "inspect", lambda connection: inspector)
    cfg = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
    return db, inspector, ScriptDirectory.from_config(cfg)


def test_empty_database_and_current_revision_do_not_write(migration_db):
    db, inspector, scripts = migration_db
    inspector.has_table.return_value = False
    compat.normalize_legacy_revision(db, scripts)
    db.execute.assert_not_called()
    inspector.has_table.return_value = True
    db.execute.return_value.scalars.return_value = ["0027"]
    compat.normalize_legacy_revision(db, scripts)
    assert db.execute.call_count == 1  # revision read only
    inspector.get_table_names.assert_not_called()


def test_single_legacy_label_is_normalized_without_replaying_tables(migration_db):
    db, _, scripts = migration_db
    db.execute.return_value.scalars.return_value = ["0024"]
    compat.normalize_legacy_revision(db, scripts)
    statement, params = db.execute.call_args.args
    assert str(statement).startswith("UPDATE alembic_version")
    assert params == {"revision": CANONICAL}


@pytest.mark.parametrize("head", [CANONICAL, "0025", "0026", "0027", "0028", "0029"])
def test_verified_descendant_preserves_its_head_and_removes_only_old_label(migration_db, head):
    db, _, scripts = migration_db
    db.execute.return_value.scalars.return_value = ["0024", head]
    compat.normalize_legacy_revision(db, scripts)
    assert str(db.execute.call_args.args[0]) == "DELETE FROM alembic_version WHERE version_num = '0024'"


@pytest.mark.parametrize("missing", sorted(TABLES))
def test_incomplete_schema_cannot_be_restamped(migration_db, missing):
    db, inspector, scripts = migration_db
    db.execute.return_value.scalars.return_value = ["0024"]
    inspector.get_table_names.return_value = TABLES - {missing}
    with pytest.raises(RuntimeError, match="incomplete"):
        compat.normalize_legacy_revision(db, scripts)
    assert db.execute.call_count == 1  # no revision update/delete


def test_unrelated_head_cannot_be_deleted_or_restamped(migration_db):
    db, _, scripts = migration_db
    db.execute.return_value.scalars.return_value = ["0024", "unrelated"]
    with pytest.raises(RuntimeError, match="unrelated"):
        compat.normalize_legacy_revision(db, scripts)
    assert db.execute.call_count == 1
