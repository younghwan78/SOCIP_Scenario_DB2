"""Exploration runs in the process pool give the sequential result; progress and cancellation."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from verify_is_v15_camera import FIXTURE, graph_from_fixture, read  # noqa: E402

from scenario_db.api.schemas.arch_exploration import ArchExplorationRunRequest  # noqa: E402
from scenario_db.api.services import analysis_inputs  # noqa: E402
from scenario_db.api.services import arch_exploration as svc  # noqa: E402
from scenario_db.api.services import cpu  # noqa: E402
from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.sim.arch_exploration import ArchExplorationSpec  # noqa: E402
from scenario_db.sim.models import DVFSTable, SimulationRunConfig  # noqa: E402

VARIANTS = ("cam-rec-r1-fhd30-sdr", "cam-rec-r1-uhd30-sdr", "cam-rec-r1-fhd60-sdr")


def _items():
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    doc = read(FIXTURE / "00_hw" / "dvfs-exynos2600-sample-v0.yaml")
    tables = {k: DVFSTable.model_validate(v) for k, v in doc["domains"].items()}
    raw = read(FIXTURE / "02_definition" / "uc-cam-recording-e2600.yaml")
    spec = ArchExplorationSpec.model_validate({"axes": {"power_options": {"enabled": False}}})
    return [{"scenario_id": "uc-cam-recording-e2600", "variant_id": v, "graph": graph_from_fixture(raw, v, catalog),
             "tables": tables, "dvfs_ref": "dvfs-test", "config": SimulationRunConfig(), "spec": spec,
             "budget": {"mw": None, "source": None}, "applied": []} for v in VARIANTS]


def test_pool_results_equal_the_sequential_ones(monkeypatch):
    monkeypatch.setattr(svc, "_exploration_workers", lambda n: 2)
    items = _items()
    ticks = []
    pooled = svc._explore_parallel(items, 200_000, ticks.append)
    assert sorted(pooled) == [0, 1, 2] and sorted(ticks) == sorted(VARIANTS)
    for i, item in enumerate(items):
        assert pooled[i] == svc._explore_item(item, 200_000)


def test_pool_failure_leaves_everything_to_the_caller(monkeypatch):
    monkeypatch.setattr(svc, "_exploration_workers", lambda n: 2)

    @contextmanager
    def broken(size):
        raise OSError("no processes here")
        yield
    monkeypatch.setattr(cpu, "_pool_batch", broken)
    assert svc._explore_parallel(_items(), 200_000, lambda v: None) == {}
    monkeypatch.setattr(svc, "_exploration_workers", lambda n: 1)
    assert svc._explore_parallel(_items(), 200_000, lambda v: None) == {}


def _scenario():
    return SimpleNamespace(id="uc-a", project_ref="proj-a", metadata_={"category": ["camera"], "name": "uc-a"})


@pytest.fixture
def mocked_run(monkeypatch):
    monkeypatch.setattr(svc, "_scenarios", lambda *a: [_scenario()])
    monkeypatch.setattr(svc, "_variant_ids", lambda *a: ["v1", "v2", "v3"])
    monkeypatch.setattr(analysis_inputs, "_apply_config_profile", lambda *a: None)
    monkeypatch.setattr(analysis_inputs.AnalysisSelection, "load",
                        lambda selection, db: analysis_inputs.AnalysisInputs(SimpleNamespace(), {}, "dvfs-test"))
    monkeypatch.setattr(svc, "_graph_soc_ref", lambda g: "soc-test")
    calls = []

    def explore(graph, spec, **kw):
        calls.append(spec.max_cases_per_variant)
        return {"scenario_id": "uc-a", "variant_id": f"v{len(calls)}", "spec_ok": True, "input_hash": str(len(calls)),
                "counts": {"cases": 10, "eligible": 1}, "recommended": {"total_mw": 1, "verified": {"ok": True}}}
    monkeypatch.setattr(svc, "explore_variant", explore)
    return calls


def test_progress_reports_every_variant_and_cancel_stores_nothing(mocked_run):
    seen = []
    db = MagicMock()
    svc.run_exploration(db, ArchExplorationRunRequest(category="camera"),
                        progress=lambda done, total, v: seen.append((done, total)) or True)
    assert seen == [(0, 3), (1, 3), (2, 3), (3, 3)]
    db = MagicMock()
    with pytest.raises(svc.ExplorationCancelled):
        svc.run_exploration(db, ArchExplorationRunRequest(category="camera"),
                            progress=lambda done, total, v: done < 2)
    db.add.assert_not_called()


def test_pooled_result_is_recomputed_when_the_run_case_cap_binds(mocked_run, monkeypatch):
    pooled = {i: {"scenario_id": "uc-a", "variant_id": f"p{i}", "spec_ok": True, "input_hash": f"p{i}",
                  "counts": {"cases": 10, "eligible": 1}, "recommended": {"total_mw": 1, "verified": {"ok": True}}}
              for i in range(3)}
    monkeypatch.setattr(svc, "_explore_parallel", lambda items, cap, tick: deepcopy(pooled))
    run = svc.run_exploration(MagicMock(), ArchExplorationRunRequest(category="camera"), parallel=True)
    assert [v["variant_id"] for v in run["variants"]] == ["p0", "p1", "p2"] and not mocked_run
    # 10 cases per variant, 25 for the run: the 3rd variant's cap is 5, not 10 -> recomputed in-process
    monkeypatch.setattr(svc, "_MAX_RUN_CASES", 25)
    request = ArchExplorationRunRequest(category="camera", spec={"max_cases_per_variant": 10})
    run = svc.run_exploration(MagicMock(), request, parallel=True)
    assert [v["variant_id"] for v in run["variants"]] == ["p0", "p1", "v1"] and mocked_run == [5]
