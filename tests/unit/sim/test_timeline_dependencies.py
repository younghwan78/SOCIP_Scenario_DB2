from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from scenario_db.sim import timeline


def test_timeline_dependency_error_names_missing_package_and_install_command(monkeypatch):
    real_import_module = importlib.import_module

    def fake_import_module(name: str, package: str | None = None):
        if name == "simpy":
            raise ImportError("No module named simpy")
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    with pytest.raises(timeline.SimulationDependencyError) as exc_info:
        timeline.build_timeline_events([{"id": "producer", "duration_ms": 1.0}], [])

    assert exc_info.value.missing == ("simpy",)
    assert "timeline simulation dependencies are missing: simpy" in str(exc_info.value)
    assert "uv sync --group sim" in str(exc_info.value)


def test_server_deployment_docs_require_sim_dependency_group():
    ubuntu_readme = Path("README_ubuntu.md").read_text(encoding="utf-8")

    assert "uv sync --group sim" in ubuntu_readme
    assert "simulation_dependencies" in ubuntu_readme
    assert "not_ready" in ubuntu_readme
