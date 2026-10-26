from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest

from scenario_db.api.services.analysis_cache import AnalysisResultCache


def test_disabled_bounded_eviction_isolation_and_expiry(monkeypatch):
    from scenario_db.api.services import analysis_cache as module
    clock = [1.]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    cache = AnalysisResultCache()
    def compute():
        return {"items": [1]}
    assert cache.get_or_compute("a", compute)[1] == "disabled"
    first, state = cache.get_or_compute("a", compute, capacity=1, ttl=10)
    assert state == "miss"
    first["items"].append(2)
    assert cache.get_or_compute("a", compute, capacity=1)[0] == {"items": [1]}
    cache.get_or_compute("b", compute, capacity=1)
    assert cache.get_or_compute("a", compute, capacity=1, ttl=10)[1] == "miss"
    clock[0] = 12
    assert cache.get_or_compute("a", compute, capacity=1)[1] == "miss"
    cache.clear()
    assert cache.get_or_compute("a", compute, capacity=1)[1] == "miss"


def test_singleflight_and_failure_retry():
    cache = AnalysisResultCache()
    entered, release = Event(), Event()
    calls = []
    def compute():
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return {"x": [1]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.get_or_compute, "a", compute, capacity=2)
        assert entered.wait(5)
        second = pool.submit(cache.get_or_compute, "a", compute, capacity=2)
        release.set()
        a, b = first.result(), second.result()
    assert len(calls) == 1 and a[0] == b[0] and a[0] is not b[0]
    def fail():
        raise ValueError("bad model")
    with pytest.raises(ValueError):
        cache.get_or_compute("bad", fail, capacity=2)
    assert cache.get_or_compute("bad", lambda: 3, capacity=2) == (3, "miss")
