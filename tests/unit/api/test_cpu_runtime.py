"""CPU input reuse and concurrent executor lifecycle preserve calculation results."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Event, current_thread
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from scenario_db.api.schemas.cpu import CpuRebalanceSweepRequest
from scenario_db.api.services import cpu
from scenario_db.exceptions import UnprocessableError
from scenario_db.models.capability.power_model import PowerModelParams
from scenario_db.sim.cpu_power import CpuPowerModel
from scenario_db.sim.models import CpuClusterProfile, CpuProfile, CpuTaskProfile


@pytest.fixture
def executor_factory(monkeypatch):
    cpu.shutdown_cpu_pool()
    pools = []

    def factory(*, max_workers, mp_context):
        pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="test-sweep")
        pools.append(pool)
        return pool

    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", factory)
    yield pools
    cpu.shutdown_cpu_pool()


def test_resize_waits_for_active_batch_and_shutdown_releases_pool(executor_factory):
    attempting, acquired = Event(), Event()

    def larger_batch():
        attempting.set()
        with cpu._pool_batch(3) as pool:
            acquired.set()
            return pool.submit(lambda: 42).result()

    with ThreadPoolExecutor(max_workers=1) as caller:
        with cpu._pool_batch(2) as initial:
            future = caller.submit(larger_batch)
            assert attempting.wait(2)
            assert not acquired.wait(0.05)
            assert initial.submit(lambda: "original is still usable").result() == "original is still usable"
        assert future.result(timeout=2) == 42
    assert len(executor_factory) == 2
    cpu.shutdown_cpu_pool()
    assert cpu._POOL is None and cpu._POOL_SIZE == 0
    with pytest.raises(RuntimeError, match="shutdown"):
        executor_factory[-1].submit(lambda: None)


def test_equal_size_batches_share_the_executor_without_serializing(executor_factory):
    acquired = Event()

    def peer():
        with cpu._pool_batch(2) as pool:
            acquired.set()
            return pool

    with ThreadPoolExecutor(max_workers=1) as caller:
        with cpu._pool_batch(2) as first:
            future = caller.submit(peer)
            assert acquired.wait(2)
            assert future.result(timeout=2) is first
    assert len(executor_factory) == 1


def test_worker_failure_does_not_recompute_successful_points(executor_factory, monkeypatch):
    calls = []

    def compute(growth, *_):
        in_worker = current_thread().name.startswith("test-sweep")
        calls.append((growth, in_worker))
        if growth == 2 and in_worker:
            raise RuntimeError("transport failed for one point")
        return {"growth": growth}

    monkeypatch.setattr(cpu, "_sweep_workers", lambda _: 2)
    monkeypatch.setattr(cpu, "_rebalance_compute", compute)
    values, workers = cpu._compute_points([(g, None, None, 30, cpu.RebalanceSpec()) for g in (1, 2, 3)])
    assert values == [{"growth": 1}, {"growth": 2}, {"growth": 3}]
    assert workers == 1 and cpu._POOL is None
    assert calls.count((1, True)) == 1 and (1, False) not in calls
    # A queued point may be cancelled; a completed/running point is reused.
    assert sum(g == 3 for g, _ in calls) == 1


def test_domain_error_is_not_changed_into_fallback(executor_factory, monkeypatch):
    monkeypatch.setattr(cpu, "_sweep_workers", lambda _: 2)
    monkeypatch.setattr(cpu, "_rebalance_compute", lambda *_: (_ for _ in ()).throw(UnprocessableError("bad profile")))
    with pytest.raises(UnprocessableError, match="bad profile"):
        cpu._compute_points([(1, None, None, 30, cpu.RebalanceSpec())] * 3)
    assert cpu._POOL_USERS == 0


@pytest.mark.parametrize("coupling_mode", ["off", "stage_slack"])
@pytest.mark.parametrize("growth", [{}, {"a": 1.2}])
def test_sweep_reuses_inputs_with_identical_points(coupling_mode, growth, monkeypatch):
    root = Path(__file__).resolve().parents[3]
    params = PowerModelParams.model_validate(yaml.safe_load(
        (root / "examples/cpu-topology/pmp-exynos2600-cpu-example.yaml").read_text(encoding="utf-8")))
    model = CpuPowerModel.from_params(params)
    profile = CpuProfile(tasks=[CpuTaskProfile(task=n, cluster="MID_LF0", cycles=3e6) for n in ("a", "b")],
                         clusters={"MID_LF0": CpuClusterProfile(freq_residency={1600: 1})})
    loads = {"profile": 0, "model": 0}

    def get_profile(*_):
        loads["profile"] += 1
        return deepcopy(profile)

    def get_model(*_):
        loads["model"] += 1
        return deepcopy(model)

    def timing(_db, _scenario, _variant, *, statistic, runtime_scale, growth=None):
        sw = 8 * runtime_scale + 2 * (growth or {}).get("a", runtime_scale)
        return {"period_ms": 1000 / 30, "runtime_scale": runtime_scale, "stretch": {"a": 1.5, "b": 1.5},
                "stages": [{"stage": "sw", "sw_ms": sw, "room_ms": 25, "slack_ms": 25 - sw,
                            "hw_ms": 2, "overhead_ms": 1, "stretch": 25 / sw,
                            "tasks": [{"task": "a", "ms": sw / 2}, {"task": "b", "ms": sw / 2}]}]}

    monkeypatch.setattr(cpu, "_profile", get_profile)
    monkeypatch.setattr(cpu, "_model", get_model)
    monkeypatch.setattr(cpu, "get_evidence", lambda *_: SimpleNamespace(scenario_ref="s", variant_ref="v"))
    monkeypatch.setattr(cpu, "timing_stretch", timing)
    monkeypatch.setattr(cpu, "bw_coefficient", lambda *_: {"mw_per_mbs": 0.08, "source": "builtin"})
    monkeypatch.setattr(cpu, "_sweep_workers", lambda _: 1)
    request = CpuRebalanceSweepRequest(cpu_profile_ref="measured", power_params_ref="target", growths=[1, 1.5, 2],
                                      timing_coupling=coupling_mode, growth=growth)
    before = profile.model_dump()
    current = cpu.run_cpu_rebalance_sweep(MagicMock(), request)
    assert loads == {"profile": 1, "model": 1}
    original_inputs = cpu._rebalance_inputs

    def independently_loaded(db, req, *, coupling_base=None, prepared=None):
        return original_inputs(db, req, coupling_base=coupling_base)

    monkeypatch.setattr(cpu, "_rebalance_inputs", independently_loaded)
    reference = cpu.run_cpu_rebalance_sweep(MagicMock(), request)
    current.pop("elapsed_ms")
    reference.pop("elapsed_ms")
    assert current == reference
    assert profile.model_dump() == before
