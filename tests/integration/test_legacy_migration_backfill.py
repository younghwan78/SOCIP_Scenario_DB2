"""Exercise legacy and current migration paths on isolated PostgreSQL schemas."""
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


@pytest.fixture
def legacy_db(pg):
    schema = f"migration_test_{uuid4().hex}"
    url = make_url(pg.get_connection_url())
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped_url = url.update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(scoped_url)
    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", scoped_url.render_as_string(hide_password=False).replace("%", "%%"))
    yield engine, cfg
    engine.dispose()
    with admin.begin() as conn:
        conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
    admin.dispose()


@pytest.mark.parametrize("revision", ["0025", "0024"])
def test_legacy_missing_columns_and_short_revision_upgrade(legacy_db, revision):
    engine, cfg = legacy_db
    command.upgrade(cfg, "0025" if revision == "0025" else "0024_prediction_collaboration")
    with engine.begin() as conn:
        if revision == "0025":
            conn.exec_driver_sql("ALTER TABLE model_bases DROP COLUMN input_stamp, DROP COLUMN trial")
        else:
            conn.execute(text("UPDATE alembic_version SET version_num = '0024'"))
        conn.exec_driver_sql("ALTER TABLE prediction_comments DROP COLUMN sequence")
        conn.exec_driver_sql("CREATE INDEX idx_prediction_comment_order ON prediction_comments (prediction_ref, created_at, id)")
        conn.exec_driver_sql("INSERT INTO projects (id, schema_version, metadata, yaml_sha256) VALUES ('p', '1', '{}', 'test')")
        conn.exec_driver_sql("INSERT INTO scenarios (id, schema_version, project_ref, metadata, pipeline, yaml_sha256) VALUES ('s', '1', 'p', '{}', '{}', 'test')")
        conn.exec_driver_sql("INSERT INTO arch_exploration_runs (id, title, scenario_type, spec, variants, errors, summary, engine_rev, input_hash) VALUES ('r', 'test', 'test', '{}', '[]', '[]', '{}', 'test', 'test')")
        conn.exec_driver_sql("INSERT INTO predictions (id, scenario_ref, variant_ref, status, exploration_run_ref, case_key, selection_rule, selected_by, metrics, input_hash) VALUES ('pred', 's', 'v', 'current', 'r', 'base', 'auto:min-power', 'auto', '{}', 'test')")
        conn.exec_driver_sql("INSERT INTO prediction_comments (id, prediction_ref, body, created_by, created_at) VALUES ('z', 'pred', 'earlier', 'writer', '2026-01-01'), ('b', 'pred', 'tie-b', 'writer', '2026-01-02'), ('a', 'pred', 'tie-a', 'writer', '2026-01-02')")
    command.upgrade(cfg, "head")
    with engine.begin() as conn:
        cols = {c["name"] for c in inspect(conn).get_columns("model_bases")}
        assert {"input_stamp", "trial"} <= cols
        assert conn.exec_driver_sql("SELECT id FROM prediction_comments ORDER BY sequence").scalars().all() == ["z", "a", "b"]
        sequence = conn.exec_driver_sql("INSERT INTO prediction_comments (id, prediction_ref, body, created_by) VALUES ('new', 'pred', 'new', 'writer') RETURNING sequence").scalar_one()
        assert sequence == 4
        indexes = inspect(conn).get_indexes("prediction_comments")
        assert next(i for i in indexes if i["name"] == "idx_prediction_comment_order")["column_names"] == ["prediction_ref", "sequence"]
    command.upgrade(cfg, "head")  # repeated startup preserves comments and numbering
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM prediction_comments").scalar_one() == 4


def test_existing_duplicate_legacy_head_is_repaired_only_by_upgrade(legacy_db):
    engine, cfg = legacy_db
    command.upgrade(cfg, "head")
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO alembic_version (version_num) VALUES ('0024')")
    command.current(cfg)
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM alembic_version").scalar_one() == 2
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalars().all() == ["0029"]


def test_schema_drift_startup_check_fails_on_missing_orm_column(legacy_db, monkeypatch, capsys):
    from scripts import check_schema_drift

    engine, cfg = legacy_db
    command.upgrade(cfg, "head")
    monkeypatch.setattr(check_schema_drift, "_db_url", lambda: engine.url.render_as_string(hide_password=False))
    assert check_schema_drift.main() == 0
    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE model_bases DROP COLUMN input_stamp")
    assert check_schema_drift.main() == 1
    output = capsys.readouterr().out
    assert "[FAIL] add_column" in output and "model_bases.input_stamp" in output
