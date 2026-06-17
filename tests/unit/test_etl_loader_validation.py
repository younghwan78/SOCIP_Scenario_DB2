from __future__ import annotations

import pytest

from scenario_db.etl import loader
from scenario_db.etl.validate_loaded import ValidationReport


class _Nested:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Session:
    def __init__(self) -> None:
        self.info = {}
        self.committed = False
        self.rolled_back = False

    def begin_nested(self) -> _Nested:
        return _Nested()

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def _write_usecase(path, *, edge_type: str) -> None:
    path.write_text(
        "\n".join(
            [
                "id: uc-cycle",
                "schema_version: '2.2'",
                "kind: scenario.usecase",
                "project_ref: proj-A",
                "metadata:",
                "  name: Cycle",
                "pipeline:",
                "  nodes:",
                "    - {id: a}",
                "    - {id: b}",
                "  edges:",
                "    - {from: a, to: b, type: OTF}",
                f"    - {{from: b, to: a, type: {edge_type}}}",
                "variants: []",
            ]
        ),
        encoding="utf-8",
    )


def test_load_yaml_dir_skips_scenario_usecase_with_data_flow_cycle(tmp_path, monkeypatch):
    called: list[str] = []
    _write_usecase(tmp_path / "cycle.yaml", edge_type="M2M")
    monkeypatch.setitem(
        loader.MAPPER_REGISTRY,
        "scenario.usecase",
        lambda raw, sha256, session: called.append(raw["id"]),
    )

    result = loader.load_yaml_dir(tmp_path, _Session())

    assert result.counts["scenario.usecase"] == 0
    assert called == []
    assert result.skipped


def test_load_yaml_dir_allows_control_feedback_edges(tmp_path, monkeypatch):
    called: list[str] = []
    _write_usecase(tmp_path / "control.yaml", edge_type="control")
    monkeypatch.setitem(
        loader.MAPPER_REGISTRY,
        "scenario.usecase",
        lambda raw, sha256, session: called.append(raw["id"]),
    )

    result = loader.load_yaml_dir(tmp_path, _Session())

    assert result.counts["scenario.usecase"] == 1
    assert called == ["uc-cycle"]


def test_load_yaml_dir_reads_yml_files(tmp_path, monkeypatch):
    called: list[str] = []
    _write_usecase(tmp_path / "control.yml", edge_type="control")
    monkeypatch.setitem(
        loader.MAPPER_REGISTRY,
        "scenario.usecase",
        lambda raw, sha256, session: called.append(raw["id"]),
    )

    result = loader.load_yaml_dir(tmp_path, _Session())

    assert result.counts["scenario.usecase"] == 1
    assert called == ["uc-cycle"]


def test_load_yaml_dir_strict_rolls_back_on_validation_errors(tmp_path, monkeypatch):
    _write_usecase(tmp_path / "control.yaml", edge_type="control")
    db = _Session()
    monkeypatch.setitem(
        loader.MAPPER_REGISTRY,
        "scenario.usecase",
        lambda raw, sha256, session: None,
    )
    monkeypatch.setattr(
        loader,
        "validate_loaded_db",
        lambda session: ValidationReport(errors=["Evidence meas-1 references missing variant uc-x/v1"]),
    )

    with pytest.raises(loader.LoaderValidationError, match="missing variant"):
        loader.load_yaml_dir(tmp_path, db, validate=True, strict=True)

    assert db.rolled_back is True
    assert db.committed is False


def test_load_yaml_dir_non_strict_returns_validation_report(tmp_path, monkeypatch):
    _write_usecase(tmp_path / "control.yaml", edge_type="control")
    db = _Session()
    monkeypatch.setitem(
        loader.MAPPER_REGISTRY,
        "scenario.usecase",
        lambda raw, sha256, session: None,
    )
    monkeypatch.setattr(
        loader,
        "validate_loaded_db",
        lambda session: ValidationReport(warnings=["Review rev-1 references missing evidence meas-1"]),
    )

    result = loader.load_yaml_dir(tmp_path, db, validate=True, strict=False)

    assert db.committed is True
    assert result.validation.warnings == ["Review rev-1 references missing evidence meas-1"]
