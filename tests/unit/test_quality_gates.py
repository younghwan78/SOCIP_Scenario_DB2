from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_pyproject_declares_static_quality_gates() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    dev_dependencies = set(pyproject["dependency-groups"]["dev"])
    assert any(dependency.startswith("ruff") for dependency in dev_dependencies)
    assert any(dependency.startswith("mypy") for dependency in dev_dependencies)
    assert any(dependency.startswith("pre-commit") for dependency in dev_dependencies)

    assert pyproject["tool"]["ruff"]["line-length"] == 100
    assert "F" in pyproject["tool"]["ruff"]["lint"]["select"]
    assert pyproject["tool"]["mypy"]["python_version"] == "3.11"
    assert pyproject["tool"]["mypy"]["warn_unused_ignores"] is True
    assert pyproject["tool"]["coverage"]["report"]["fail_under"] >= 45


def test_pre_commit_runs_ruff_and_mypy() -> None:
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")

    assert "ruff-check" in config
    assert "ruff-format" in config
    assert "mypy" in config


def test_github_actions_runs_quality_and_test_gates() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "uv run ruff check ." in workflow
    assert "uv run mypy" in workflow
    assert "uv run pytest tests/unit" in workflow
    assert "uv run pytest tests/integration" in workflow
