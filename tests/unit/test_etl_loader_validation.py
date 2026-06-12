from __future__ import annotations

from scenario_db.etl import loader


class _Nested:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Session:
    def __init__(self) -> None:
        self.info = {}
        self.committed = False

    def begin_nested(self) -> _Nested:
        return _Nested()

    def commit(self) -> None:
        self.committed = True


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

    counts = loader.load_yaml_dir(tmp_path, _Session())

    assert counts["scenario.usecase"] == 0
    assert called == []


def test_load_yaml_dir_allows_control_feedback_edges(tmp_path, monkeypatch):
    called: list[str] = []
    _write_usecase(tmp_path / "control.yaml", edge_type="control")
    monkeypatch.setitem(
        loader.MAPPER_REGISTRY,
        "scenario.usecase",
        lambda raw, sha256, session: called.append(raw["id"]),
    )

    counts = loader.load_yaml_dir(tmp_path, _Session())

    assert counts["scenario.usecase"] == 1
    assert called == ["uc-cycle"]
