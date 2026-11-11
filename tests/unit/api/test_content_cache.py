"""O-04 content-addressed compute cache and O-05 HTTP validators."""

from __future__ import annotations

import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from verify_is_v15_camera import FIXTURE, graph_from_fixture, read  # noqa: E402

from scenario_db.api import http_cache  # noqa: E402
from scenario_db.api.schemas.timing_budget import TimingBudgetFleetRequest  # noqa: E402
from scenario_db.api.services import analysis_inputs  # noqa: E402
from scenario_db.api.services import timing_budget as timing  # noqa: E402
from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.sim import result_cache  # noqa: E402
from scenario_db.sim.models import DVFSTable, SimulationRunConfig  # noqa: E402
from scenario_db.sim.timing_budget import TimingBudgetOptions  # noqa: E402

UHD30 = "cam-rec-r1-uhd30-vdis"


@pytest.fixture(scope="module")
def env():
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    doc = read(FIXTURE / "00_hw" / "dvfs-exynos2600-sample-v0.yaml")
    tables = {k: DVFSTable.model_validate(v) for k, v in doc["domains"].items()}
    raw = read(FIXTURE / "02_definition" / "uc-cam-recording-e2600.yaml")
    return (lambda v=UHD30: graph_from_fixture(raw, v, catalog)), tables


@pytest.fixture
def on_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(result_cache, "cache_dir", lambda: tmp_path)
    return tmp_path


def key(graph, tables, config=None, options=None):
    return result_cache.calculation_key("t", graph, config=config or SimulationRunConfig(),
                                        options=options or TimingBudgetOptions(), tables=tables)


def test_key_follows_every_input(env):
    make, tables = env
    base = key(make(), tables)
    assert base == key(make(), tables) and len(base) == 64
    variant = deepcopy(make().variant)
    variant.design_conditions = {**(variant.design_conditions or {}), "fps": 60}
    assert key(replace(make(), variant=variant), tables) != base
    assert key(make(), tables, config=SimulationRunConfig(fps=60)) != base
    assert key(make(), tables, options=TimingBudgetOptions(statistic="mean")) != base
    assert key(make(), {}) != base
    g = make()
    ip = next(iter(g.ip_catalog))
    g.ip_catalog[ip] = IpCatalog(id=ip, schema_version="x", category="x", hierarchy={}, capabilities={"changed": True}, yaml_sha256="fixture")
    assert key(g, tables) != base
    assert key(make("cam-rec-r1-fhd30-sdr"), tables) != base
    assert result_cache.calculation_key("t", "not a graph", config=None, options=None, tables=None) is None


def test_engine_digest_is_part_of_the_key(env, monkeypatch):
    make, tables = env
    base = key(make(), tables)
    monkeypatch.setattr(result_cache, "_SOURCE_DIGEST", "another-engine")
    assert key(make(), tables) != base


def test_cache_roundtrip_and_off(on_disk, monkeypatch):
    calls = []

    def compute():
        calls.append(1)
        return {"x": (1, 2), "y": 1.5}
    first, hit1 = result_cache.cached("k" * 64, compute)
    second, hit2 = result_cache.cached("k" * 64, compute)
    assert (hit1, hit2) == (False, True) and len(calls) == 1 and second == {"x": [1, 2], "y": 1.5}
    # a torn file is a miss, not an error
    path = next(on_disk.glob("*/*.json.gz"))
    path.write_bytes(b"garbage")
    assert result_cache.get("k" * 64) is None
    assert result_cache.cached(None, compute) == ({"x": (1, 2), "y": 1.5}, False)
    monkeypatch.setattr(result_cache, "cache_dir", lambda: None)
    assert result_cache.cached("z" * 64, compute)[1] is False and result_cache.get("z" * 64) is None


def test_prune_keeps_the_newest(on_disk, monkeypatch):
    import scenario_db.config as config

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(compute_cache_max_entries=10, compute_cache_dir=str(on_disk)))
    for i in range(12):
        result_cache.put(f"{i:064d}", {"i": i})
    assert len(list(on_disk.glob("*/*.json.gz"))) <= 10
    assert result_cache.get(f"{11:064d}") == {"i": 11}


def test_fleet_rows_come_from_the_cache_on_a_second_visit(env, on_disk, monkeypatch):
    make, tables = env
    monkeypatch.setattr(analysis_inputs, "_apply_config_profile", lambda *a: None)
    monkeypatch.setattr(analysis_inputs.AnalysisSelection, "load",
                        lambda selection, db: analysis_inputs.AnalysisInputs(make(selection.request.variant_id), tables, "dvfs"))
    monkeypatch.setattr(timing, "scenario_policy", lambda *a: None)
    monkeypatch.setattr(timing, "apply_throughput", lambda options, policy: options)
    monkeypatch.setattr(timing, "with_cpu_profile", lambda db, options, *a: options)
    real = timing.analyze_timing_budget
    calls = []

    def counted(*a, **k):
        calls.append(1)
        return real(*a, **k)
    monkeypatch.setattr(timing, "analyze_timing_budget", counted)
    request = TimingBudgetFleetRequest(scenario_id="uc-cam-recording-e2600", variant_ids=[UHD30, "cam-rec-r1-fhd30-sdr"])
    first = timing.analyze_timing_budget_fleet(MagicMock(), request)
    second = timing.analyze_timing_budget_fleet(MagicMock(), request)
    assert len(calls) == 2 and first.model_dump() == second.model_dump() and len(second.rows) == 2


def _request(etag=None):
    headers = [(b"if-none-match", etag.encode())] if etag else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers, "query_string": b""})


def test_json_etag_and_304():
    first = http_cache.json_response(_request(), {"a": 1, "b": [1, 2]})
    assert first.status_code == 200 and first.headers["etag"].startswith('"') and first.headers["cache-control"] == "private, no-cache"
    again = http_cache.json_response(_request(first.headers["etag"]), {"a": 1, "b": [1, 2]})
    assert again.status_code == 304 and again.body == b""
    changed = http_cache.json_response(_request(first.headers["etag"]), {"a": 2})
    assert changed.status_code == 200 and changed.headers["etag"] != first.headers["etag"]
    assert http_cache.json_response(_request("W/" + first.headers["etag"]), {"a": 1, "b": [1, 2]}).status_code == 304


def test_html_etag_uses_the_stored_digest():
    r = http_cache.html_response(_request(), "<p>x</p>", "f" * 64)
    assert r.headers["etag"] == '"' + "f" * 32 + '"'
    assert http_cache.html_response(_request(r.headers["etag"]), "<p>x</p>", "f" * 64).status_code == 304
    assert http_cache.html_response(_request(), "<p>x</p>", None).headers["etag"] != r.headers["etag"]


def test_key_tells_explicit_from_omitted_options(env):
    make, tables = env
    omitted = key(make(), tables, options=TimingBudgetOptions())
    explicit = key(make(), tables, options=TimingBudgetOptions.model_validate({"cpu": {}}))
    assert TimingBudgetOptions().model_dump() == TimingBudgetOptions.model_validate({"cpu": {}}).model_dump()
    assert omitted != explicit


def test_engine_digest_covers_the_whole_package():
    from pathlib import Path

    import scenario_db

    root = Path(scenario_db.__file__).resolve().parent
    digest = result_cache.engine_source_digest()
    assert len(digest) == 64
    # modules outside sim/ that shape the calculation are part of it
    assert (root / "db" / "repositories" / "scenario_graph.py").exists()
    import hashlib
    h = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        h.update(str(path.relative_to(root)).encode())
        h.update(path.read_bytes())
    assert h.hexdigest() == digest
