from __future__ import annotations

import shlex
import tomllib
from collections import Counter
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _workflow() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))


def test_pyproject_declares_static_quality_gates() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    dev_dependencies = set(pyproject["dependency-groups"]["dev"])
    assert any(dependency.startswith("ruff") for dependency in dev_dependencies)
    assert any(dependency.startswith("mypy") for dependency in dev_dependencies)
    assert any(dependency.startswith("pip-audit") for dependency in dev_dependencies)
    assert any(dependency.startswith("pre-commit") for dependency in dev_dependencies)
    assert any(dependency.startswith("pytest-xdist") for dependency in dev_dependencies)

    assert pyproject["tool"]["ruff"]["line-length"] == 100
    assert "F" in pyproject["tool"]["ruff"]["lint"]["select"]
    assert "E9" in pyproject["tool"]["ruff"]["lint"]["select"]
    assert "B904" in pyproject["tool"]["ruff"]["lint"]["select"]
    assert pyproject["tool"]["mypy"]["python_version"] == "3.11"
    assert pyproject["tool"]["mypy"]["warn_unused_ignores"] is True
    mypy_files = set(pyproject["tool"]["mypy"]["files"])
    assert "src/scenario_db/api/auth.py" in mypy_files
    assert "src/scenario_db/api/cache.py" in mypy_files
    assert "src/scenario_db/api/deps.py" in mypy_files
    assert pyproject["tool"]["coverage"]["report"]["fail_under"] >= 80


def test_pre_commit_runs_ruff_and_mypy() -> None:
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")

    assert "ruff-check" in config
    assert "ruff-format" in config
    assert "mypy" in config


def test_github_actions_runs_quality_and_test_gates() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "actions/checkout@v5.1.0" in workflow
    assert "astral-sh/setup-uv@v8.3.2" in workflow
    assert "uv sync --frozen --group dev --group dashboard --group sim --extra profiling" in workflow
    assert "uv run --extra profiling ruff check ." in workflow
    assert "uv run --extra profiling mypy" in workflow
    assert "uv run --extra profiling pip-audit" in workflow
    assert "uv run --extra profiling pytest ${{ matrix.tests }}" in workflow
    assert "uv run --extra profiling pytest tests/integration" in workflow


def test_parallel_ci_preserves_coverage_and_required_check_names() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    unit_command = next(
        step["run"] for step in jobs["unit"]["steps"]
        if "pytest ${{ matrix.tests }}" in step.get("run", "")
    )
    integration_command = jobs["integration"]["steps"][-1]["run"]
    assert "-n 4" in unit_command
    assert "--cov=scenario_db" in unit_command
    shards = jobs["unit"]["strategy"]["matrix"]["include"]
    assert {shard["shard"]: shard["tests"] for shard in shards} == {
        "sim": "tests/unit/sim",
        "trace": "tests/unit/meas_import tests/unit/authoring",
        "rest": "tests/unit --ignore=tests/unit/sim --ignore=tests/unit/meas_import"
                " --ignore=tests/unit/authoring",
    }
    assert jobs["unit"]["strategy"]["fail-fast"] is False
    gate = jobs["quality"]
    assert set(gate["needs"]) == {"static-quality", "unit"}
    assert gate["if"] == "${{ always() }}"
    assert 'test "$STATIC_RESULT" = success' in gate["steps"][0]["run"]
    assert 'test "$UNIT_RESULT" = success' in gate["steps"][0]["run"]
    coverage_check = gate["steps"][-3]["run"]
    assert coverage_check == " && ".join(
        f"test -s .coverage.{shard['shard']}" for shard in shards
    )
    assert gate["steps"][-2]["run"].endswith("coverage combine")
    assert gate["steps"][-1]["run"].endswith("coverage report --fail-under=80")
    assert "-n 4" in integration_command
    assert "--dist loadfile" in integration_command
    assert "github.run_id" in workflow["concurrency"]["group"]
    assert workflow["concurrency"]["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"


def test_unit_shards_cover_every_test_file_exactly_once() -> None:
    test_files = {
        path for path in (ROOT / "tests/unit").rglob("*.py")
        if path.name.startswith("test_") or path.name.endswith("_test.py")
    }
    owners: Counter[Path] = Counter()
    shards = _workflow()["jobs"]["unit"]["strategy"]["matrix"]["include"]
    for shard in shards:
        arguments = shlex.split(shard["tests"])
        roots = [ROOT / arg for arg in arguments if not arg.startswith("--")]
        ignored = [ROOT / arg.removeprefix("--ignore=")
                   for arg in arguments if arg.startswith("--ignore=")]
        selected = {
            path for path in test_files
            if any(path.is_relative_to(root) for root in roots)
            and not any(path.is_relative_to(root) for root in ignored)
        }
        assert selected, f"Empty unit shard: {shard['shard']}"
        owners.update(selected)
    assert owners == Counter({path: 1 for path in test_files})


def test_trace_shard_caches_and_measures_the_pinned_perfetto_binary() -> None:
    steps = _workflow()["jobs"]["unit"]["steps"]
    cache = next(step for step in steps if step.get("name") == "Cache pinned Perfetto binary")
    warmup = next(step for step in steps if step.get("name") == "Measure Perfetto binary setup")
    assert cache["if"] == warmup["if"] == "matrix.shard == 'trace'"
    assert cache["with"]["path"] == "~/.local/share/perfetto/prebuilts"
    assert all(part in cache["with"]["key"] for part in (
        "runner.os", "runner.arch", "hashFiles('uv.lock')",
    ))
    assert cache["with"]["key"].startswith(cache["with"]["restore-keys"])
    test_index = next(i for i, step in enumerate(steps)
                      if "pytest ${{ matrix.tests }}" in step.get("run", ""))
    assert steps.index(cache) < steps.index(warmup) < test_index


def test_ubuntu_runbook_matches_mutation_auth_contract() -> None:
    runbook = (ROOT / "docs" / "operations" / "deployment-ubuntu.md").read_text(encoding="utf-8")

    assert "SCENARIO_DB_MUTATION_API_KEYS" in runbook
    assert "SCENARIO_DB_MUTATION_AUTH_DISABLED=false" in runbook
    assert "X-ScenarioDB-Key-Id" in runbook
    assert "X-ScenarioDB-API-Key" in runbook
    assert "uv sync --group dashboard --group sim" in runbook
    assert "Authentication and authorization are not implemented yet." not in runbook
    assert "actor identity is currently client-supplied" not in runbook
