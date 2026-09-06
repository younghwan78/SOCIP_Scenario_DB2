"""Loader .etlignore support for auxiliary non-document YAML."""
from __future__ import annotations

import pytest

from scenario_db.etl.loader import _iter_yaml_files, _is_ignored, _load_etlignore

pytestmark = pytest.mark.unit


def test_etlignore_patterns_filter_yaml_discovery(tmp_path):
    (tmp_path / "doc.yaml").write_text("kind: ip\n", encoding="utf-8")
    (tmp_path / "sim_import_mapping.yaml").write_text("mappings: {}\n", encoding="utf-8")
    sub = tmp_path / "notes"
    sub.mkdir()
    (sub / "scratch.yml").write_text("x: 1\n", encoding="utf-8")
    (tmp_path / ".etlignore").write_text(
        "# auxiliary files\nsim_import_mapping.yaml\nnotes/*.yml\n",
        encoding="utf-8",
    )

    names = [path.name for path in _iter_yaml_files(tmp_path)]

    assert names == ["doc.yaml"]


def test_missing_etlignore_keeps_all_files(tmp_path):
    (tmp_path / "a.yaml").write_text("kind: ip\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("kind: ip\n", encoding="utf-8")

    assert _load_etlignore(tmp_path) == []
    assert len(_iter_yaml_files(tmp_path)) == 2


def test_is_ignored_matches_relative_path_or_basename(tmp_path):
    target = tmp_path / "sub" / "aux.yaml"
    target.parent.mkdir()
    target.write_text("x: 1\n", encoding="utf-8")

    assert _is_ignored(target, tmp_path, ["sub/aux.yaml"]) is True
    assert _is_ignored(target, tmp_path, ["aux.yaml"]) is True
    assert _is_ignored(target, tmp_path, ["other.yaml"]) is False
