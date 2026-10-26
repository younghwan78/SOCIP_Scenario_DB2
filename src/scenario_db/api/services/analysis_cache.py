"""Bounded pure-result cache; database ownership and input validation stay with callers."""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future
from copy import deepcopy
from threading import Lock
from time import monotonic


class AnalysisResultCache:
    def __init__(self):
        self._lock = Lock()
        self._values = OrderedDict()
        self._pending: dict[str, Future] = {}

    def get_or_compute(self, key, compute, *, capacity=0, ttl=60):
        if capacity <= 0:
            return compute(), "disabled"
        with self._lock:
            now = monotonic()
            for old in [k for k, (expiry, _) in self._values.items() if expiry <= now]:
                del self._values[old]
            if key in self._values:
                self._values.move_to_end(key)
                return deepcopy(self._values[key][1]), "hit"
            pending = self._pending.get(key)
            owner = pending is None
            if owner:
                pending = Future()
                self._pending[key] = pending
        if not owner:
            return deepcopy(pending.result()), "shared"
        try:
            value = compute()
            with self._lock:
                self._values[key] = (monotonic() + ttl, deepcopy(value))
                while len(self._values) > capacity:
                    self._values.popitem(last=False)
            pending.set_result(deepcopy(value))
            return value, "miss"
        except BaseException as exc:
            pending.set_exception(exc)
            raise
        finally:
            with self._lock:
                self._pending.pop(key, None)

    def clear(self):
        with self._lock:
            self._values.clear()


whatif_cases = AnalysisResultCache()
