"""Content-addressed cache for repeated calculations (O-04).

The key is a digest of everything the engine reads for one calculation — the scenario pipeline,
size profile and power options, the variant, the project globals, the SoC compression catalog,
the IP catalog capabilities, the run config, the options, the DVFS tables — plus a digest of the
engine source itself. A changed input or engine gives a new key, so entries never need
invalidating and every API worker reading the same directory agrees (unlike a process-global
memo). Entries are gzip JSON files written atomically; the oldest are pruned past a size limit.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import tempfile
from dataclasses import is_dataclass
from pathlib import Path
from typing import Any, Callable

_log = logging.getLogger(__name__)
_SOURCE_DIGEST: str | None = None
_SOURCE_DIRS = ("sim", "models/definition", "models/capability")


def engine_source_digest() -> str:
    """sha256 of the engine source (sim/ and the model definitions): a code change is a new key."""
    global _SOURCE_DIGEST
    if _SOURCE_DIGEST is None:
        root = Path(__file__).resolve().parents[1]
        h = hashlib.sha256()
        for sub in _SOURCE_DIRS:
            for path in sorted((root / sub).rglob("*.py")):
                h.update(str(path.relative_to(root)).encode())
                h.update(path.read_bytes())
        _SOURCE_DIGEST = h.hexdigest()
    return _SOURCE_DIGEST


def _jsonable(value: Any) -> Any:
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        from dataclasses import asdict

        return asdict(value)
    return value


def calculation_key(kind: str, graph: Any, *, config: Any, options: Any, tables: dict[str, Any] | None) -> str | None:
    """Digest of one calculation's inputs, or None when the graph is not a canonical graph (no cache)."""
    from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
    from scenario_db.sim.arch_exploration import _variant_doc

    if not isinstance(graph, CanonicalScenarioGraph):
        return None
    scenario, project, soc = graph.scenario, graph.project, graph.soc
    payload = {
        "kind": kind,
        "engine": engine_source_digest(),
        "scenario": {"id": scenario.id, "project_ref": getattr(scenario, "project_ref", None),
                     "pipeline": getattr(scenario, "pipeline", None), "size_profile": getattr(scenario, "size_profile", None),
                     "power_options": getattr(scenario, "power_options", None)},
        "variant": _variant_doc(graph.variant),
        "project": None if project is None else {"id": project.id, "metadata": getattr(project, "metadata_", None),
                                                  "globals": getattr(project, "globals_", None)},
        "soc": None if soc is None else {"id": getattr(soc, "id", None), "compression_modes": getattr(soc, "compression_modes", None),
                                          "platform_model": getattr(soc, "platform_model", None)},
        "ip_catalog": {k: {"category": getattr(r, "category", None), "hierarchy": getattr(r, "hierarchy", None),
                           "capabilities": getattr(r, "capabilities", None)} for k, r in sorted(graph.ip_catalog.items())},
        "config": _jsonable(config),
        "options": _jsonable(options),
        "tables": {k: _jsonable(t) for k, t in sorted((tables or {}).items())},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def cache_dir() -> Path | None:
    from scenario_db.config import get_settings

    configured = get_settings().compute_cache_dir
    if configured == "off":
        return None
    return Path(configured) if configured else Path(tempfile.gettempdir()) / "scenario-db-compute-cache"


def _path(root: Path, key: str) -> Path:
    return root / key[:2] / f"{key}.json.gz"


def get(key: str) -> Any | None:
    root = cache_dir()
    if root is None:
        return None
    try:
        with gzip.open(_path(root, key), "rb") as fh:
            return json.loads(fh.read().decode())
    except FileNotFoundError:
        return None
    except (OSError, ValueError):  # a torn / foreign file is a miss
        return None


def put(key: str, value: Any) -> None:
    root = cache_dir()
    if root is None:
        return
    path = _path(root, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(fd, "wb") as fh:
            fh.write(gzip.compress(json.dumps(value, sort_keys=True, default=str).encode()))
        os.replace(tmp, path)
        _prune(root)
    except Exception:  # noqa: BLE001 - a cache write never fails the calculation
        _log.warning("compute cache write failed", exc_info=True)


def _prune(root: Path) -> None:
    from scenario_db.config import get_settings

    limit = get_settings().compute_cache_max_entries
    files = list(root.glob("*/*.json.gz"))
    if len(files) <= limit:
        return
    files.sort(key=lambda p: p.stat().st_mtime)
    for p in files[: len(files) - int(limit * 0.9)]:
        try:
            p.unlink()
        except OSError:
            pass


def cached(key: str | None, compute: Callable[[], Any]) -> tuple[Any, bool]:
    """(value, hit). Without a key the value is computed and not stored; cache trouble only costs a recompute."""
    if key is None:
        return compute(), False
    try:
        hit = get(key)
    except Exception:  # noqa: BLE001 - e.g. settings not loadable: no cache
        _log.warning("compute cache read failed", exc_info=True)
        return compute(), False
    if hit is not None:
        return hit, True
    value = compute()
    put(key, value)
    return value, False
