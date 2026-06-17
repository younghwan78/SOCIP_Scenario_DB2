from __future__ import annotations

from pathlib import Path

from scripts import import_sim_modes
from scenario_db.etl.loader import LoaderValidationError, LoadResult
from scenario_db.etl.validate_loaded import ValidationReport


class _SessionContext:
    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, tb):
        return False


def test_reload_db_requires_database_url_before_engine_creation(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text("source_csv: dummy.csv\ncatalog_root: .\n", encoding="utf-8")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SCENARIO_DB_DATABASE_URL", raising=False)
    monkeypatch.setattr(import_sim_modes, "_load_env_file", lambda path: None)
    monkeypatch.setattr(import_sim_modes, "apply_sim_import_mapping", lambda *args, **kwargs: [])

    def fail_make_engine(*args, **kwargs):
        raise AssertionError("make_engine should not be called without a DB URL")

    monkeypatch.setattr(import_sim_modes, "make_engine", fail_make_engine)

    rc = import_sim_modes.main([str(mapping), "--reload-db"])

    assert rc == 1
    assert "SCENARIO_DB_DATABASE_URL or DATABASE_URL is required" in capsys.readouterr().err


def test_reload_db_reports_loader_validation_without_traceback(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text("source_csv: dummy.csv\ncatalog_root: .\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///scenario.db")
    monkeypatch.setattr(import_sim_modes, "_load_env_file", lambda path: None)
    monkeypatch.setattr(import_sim_modes, "apply_sim_import_mapping", lambda *args, **kwargs: [])
    monkeypatch.setattr(import_sim_modes, "make_engine", lambda *args, **kwargs: object())
    monkeypatch.setattr(import_sim_modes, "get_session", lambda engine: _SessionContext())

    def fail_load(*args, **kwargs):
        raise LoaderValidationError(
            LoadResult(validation=ValidationReport(errors=["variant overlay is invalid"]))
        )

    monkeypatch.setattr(import_sim_modes, "load_yaml_dir", fail_load)

    rc = import_sim_modes.main([str(mapping), "--reload-db"])

    assert rc == 1
    assert "variant overlay is invalid" in capsys.readouterr().err
