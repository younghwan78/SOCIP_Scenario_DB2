"""Scale benchmark: 1k / 10k variants, large evidence history, max-size exploration run.

Disposable PostgreSQL 16 (testcontainers) unless --database-url is given; never touches the
application database. Measures API latency, payload bytes and SELECT counts for the paths the
React UI calls (list endpoints are fetched page by page like ``allPages`` in ui/src/lib/api.ts),
plus the write paths that scale with the run size (promote, report).

Run from implementation/:
    uv run --group sim python scripts/bench_scale.py --variants 1000
    uv run --group sim python scripts/bench_scale.py --variants 10000 --repeats 3
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Callable

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

PROJECT = "bench-scale-project"
VARIANTS_PER_SCENARIO = 100
CONDITIONS = {
    "resolution": ["FHD", "UHD", "8K", "QHD"], "fps": [24, 30, 60, 120, 240],
    "hdr": ["SDR", "HDR10", "HLG"], "stabilization": ["none", "ois", "vdis", "supersteady"],
    "codec_mfc": ["HEVC", "AVC", "APV"], "camera_mode": ["rear", "front", "dual"],
}


# ------------------------------------------------------------------- template
def exploration_template() -> dict[str, Any]:
    """One real exploration summary (Exynos2600 fixture, UHD30 VDIS, power options on)."""
    import yaml
    from verify_is_v15_camera import FIXTURE, graph_from_fixture, read
    from scenario_db.db.models.capability import IpCatalog
    from scenario_db.sim import arch_exploration as ax
    from scenario_db.sim.models import DVFSTable

    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    raw = read(FIXTURE / "02_definition" / "uc-cam-recording-e2600.yaml")
    doc = yaml.safe_load((FIXTURE / "00_hw" / "dvfs-exynos2600-sample-v0.yaml").read_text(encoding="utf-8"))
    tables = {k: DVFSTable.model_validate(v) for k, v in doc["domains"].items()}
    spec = ax.ArchExplorationSpec.model_validate({"axes": {"power_options": {"enabled": True}}})
    summary = ax.explore_variant(graph_from_fixture(raw, "cam-rec-r1-uhd30-vdis", catalog), spec, dvfs_tables=tables)
    summary["_spec"] = spec.model_dump(mode="json")
    return json.loads(json.dumps(summary, default=str))


# ------------------------------------------------------------------- seed
def seed(engine, n_variants: int, histories: int, measurements: int, run_variants: int, tpl: dict[str, Any]) -> dict[str, Any]:
    from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
    from scenario_db.db.models.evidence import Evidence
    from scenario_db.db.models.exploration import ArchExplorationRun, Prediction
    from scenario_db.sim.arch_exploration import ENGINE_REV, prediction_payload

    n_scen = max(1, math.ceil(n_variants / VARIANTS_PER_SCENARIO))
    sids = [f"uc-bench-{i:04}" for i in range(n_scen)]
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    keys = list(CONDITIONS)

    def cond(i: int) -> dict[str, Any]:
        return {k: CONDITIONS[k][(i // (j + 1)) % len(CONDITIONS[k])] for j, k in enumerate(keys)}

    blobs = tpl.pop("_manifest_blobs", {}) or {}
    spec = tpl.pop("_spec")
    pipeline = {"nodes": [{"id": f"n{i}", "ip_ref": f"ip-{i}"} for i in range(40)],
                "edges": [{"from": f"n{i}", "to": f"n{i + 1}", "buffer": f"B{i}"} for i in range(39)],
                "buffers": {f"B{i}": {"format": "YUV420", "w": 3840, "h": 2160} for i in range(39)}}
    timeline = [{"task_id": f"t{i}", "node_id": f"n{i % 40}", "frame_index": i // 40, "start_ms": i * 0.3,
                 "end_ms": i * 0.3 + 2.0, "duration_ms": 2.0, "hw_name": f"IP{i % 40}"} for i in range(160)]
    dma = [{"node_id": f"n{i}", "hw_name": f"IP{i}", "port": f"P{i}", "direction": "read" if i % 2 else "write",
            "bw_mbs": 100.0 + i, "bw_power_mw": 3.0} for i in range(40)]
    rails = {f"VDD_RAIL_{i:02}": {"power_mw": 20.0 + i, "std_mw": 0.5, "voltage_v": 0.75} for i in range(24)}
    with Session(engine) as db:
        db.add(Project(id=PROJECT, schema_version="2.2", yaml_sha256="bench",
                       metadata_={"name": "Scale bench", "soc_ref": "bench-soc", "board_type": "EVT"}))
        db.flush()
        db.execute(Scenario.__table__.insert(), [dict(
            id=sid, project_ref=PROJECT, schema_version="2.2", yaml_sha256="bench",
            metadata={"name": f"Bench scenario {i}", "category": ["camera"]}, pipeline=pipeline)
            for i, sid in enumerate(sids)])
        rows = []
        for i in range(n_variants):
            rows.append(dict(scenario_id=sids[i // VARIANTS_PER_SCENARIO], id=f"v-{i:05}", severity="nominal",
                             design_conditions=cond(i), node_configs={f"n{j}": {"sim": {"mode": "Normal"}} for j in range(10)}))
        db.execute(ScenarioVariant.__table__.insert(), rows)
        # heavy history on scenario 0: simulation evidence (timeline + DMA) and measurements (rails)
        s0_vars = [r["id"] for r in rows if r["scenario_id"] == sids[0]]
        db.execute(Evidence.__table__.insert(), [dict(
            id=f"bench-sim-{i:05}", scenario_ref=sids[0], variant_ref=s0_vars[i % len(s0_vars)], schema_version="2.2",
            kind="evidence.simulation", yaml_sha256="bench", aggregation={}, execution_context={"silicon_rev": "EVT1", "thermal": "room"},
            kpi={"total_power_mw": 800.0 + i % 50}, run_info={"timestamp": (now + timedelta(minutes=i)).isoformat(), "source": "calculated"},
            power_breakdown={"ip": {"total_mw": 300.0}, "memory": {"total_mw": 200.0}, "cpu": {"total_mw": 300.0}},
            timeline_events=timeline, dma_breakdown=dma, ip_breakdown=[{"ip": f"IP{j}", "power_mw": 7.0} for j in range(40)])
            for i in range(histories)])
        db.execute(Evidence.__table__.insert(), [dict(
            id=f"bench-meas-{i:05}", scenario_ref=sids[0], variant_ref=s0_vars[i % len(s0_vars)], schema_version="2.2",
            kind="evidence.measurement", yaml_sha256="bench", aggregation={}, measured_at=now - timedelta(hours=i),
            execution_context={"silicon_rev": "EVT1", "thermal": "chamber25", "power_state": "screen_on"},
            kpi={"total_power_mw": {"mean": 820.0, "std": 5.0, "n": 5, "ci_95": [815.0, 825.0]}}, vdd_power=rails,
            provenance={"collection_method": "power_monitor", "device_id": f"EVT1-{i % 7}"})
            for i in range(measurements)])
        # max-size exploration run (scenario 0 .. ) cloned from the real template
        run_rows = [r for r in rows][:run_variants]
        variants = []
        for r in run_rows:
            v = deepcopy(tpl)
            v["scenario_id"], v["variant_id"] = r["scenario_id"], r["id"]
            variants.append(v)
        run_id = "EXP-bench-max"
        db.add(ArchExplorationRun(
            id=run_id, title="bench max run", scenario_type="camera", project_ref=PROJECT, soc_ref="bench-soc",
            spec=spec | {"scenario_ids": sorted({r["scenario_id"] for r in run_rows}), "manifest": {"engine_rev": ENGINE_REV, "blobs": blobs}},
            variants=variants, errors=[], summary={"variants": len(variants), "errors": 0, "spec_ok": len(variants), "cases": 0,
                                                   "eligible_cases": 0, "verified": 0, "recommended_power_mw": None},
            engine_rev=ENGINE_REV, input_hash="bench", created_at=now))
        # predictions for the variants outside the run (board / model-status scale with N)
        other_run = "EXP-bench-other"
        db.add(ArchExplorationRun(id=other_run, title="bench other", scenario_type="camera", project_ref=PROJECT,
                                  spec={}, variants=[], errors=[], summary={"variants": 0}, engine_rev=ENGINE_REV, input_hash="bench",
                                  created_at=now - timedelta(days=1)))
        db.flush()
        metrics = prediction_payload(tpl["objective_slice"], tpl["recommended"], tpl["buffers"])
        db.execute(Prediction.__table__.insert(), [dict(
            id=f"PRED-bench-{i:05}", scenario_ref=r["scenario_id"], variant_ref=r["id"], project_ref=PROJECT, status="current",
            exploration_run_ref=other_run, case_key=tpl["recommended"]["key"], selection_rule="auto:min-power",
            selected_by="auto", metrics=metrics, input_hash="bench") for i, r in enumerate(rows[run_variants:], start=run_variants)])
        db.commit()
    with engine.begin() as conn:
        conn.execute(text("ANALYZE"))
    return {"scenarios": sids, "run_id": run_id, "measurement": "bench-meas-00000"}


# ------------------------------------------------------------------- measure
@contextmanager
def count_selects(engine):
    stmts: list[str] = []

    def capture(_conn, _cursor, sql, _params, _ctx, _many):
        if sql.lstrip().upper().startswith(("SELECT", "WITH")):
            stmts.append(sql)
    event.listen(engine, "after_cursor_execute", capture)
    try:
        yield stmts
    finally:
        event.remove(engine, "after_cursor_execute", capture)


def measure(engine, fn: Callable[[], Any], repeats: int) -> dict[str, Any]:
    first = time.perf_counter()
    with count_selects(engine) as stmts:
        result = fn()
    cold = (time.perf_counter() - first) * 1000
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000)
    size = result if isinstance(result, int) else len(json.dumps(result, default=str).encode())
    times = times or [cold]
    return {"cold_ms": round(cold, 1), "median_ms": round(statistics.median(times), 1),
            "max_ms": round(max(times), 1), "selects": len(stmts), "bytes": size}


def all_pages(client, path: str, params: dict[str, Any], limit: int) -> int:
    """Mirror of ui/src/lib/api.ts allPages: returns total response bytes."""
    total_bytes, offset, total = 0, 0, None
    while total is None or offset < total:
        res = client.get(path, params={**params, "limit": limit, "offset": offset})
        res.raise_for_status()
        total_bytes += len(res.content)
        body = res.json()
        total = body["total"]
        if not body["items"]:
            break
        offset += len(body["items"])
    return total_bytes


def get_bytes(client, path: str, params: dict[str, Any] | None = None) -> int:
    res = client.get(path, params=params or {})
    res.raise_for_status()
    return len(res.content)


def run(args) -> dict[str, Any]:
    from fastapi.testclient import TestClient
    from scenario_db.api.app import create_app
    from scenario_db.api.deps import get_db
    from scenario_db.api.schemas.arch_exploration import ArchReportRequest, PromoteRequest
    from scenario_db.api.services import arch_exploration as svc
    from scenario_db.db.base import Base

    tpl_start = time.perf_counter()
    tpl = exploration_template()
    tpl_s = time.perf_counter() - tpl_start
    tpl_kb = len(json.dumps({k: v for k, v in tpl.items() if not k.startswith("_")}).encode()) // 1024

    engine = create_engine(args.database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    t0 = time.perf_counter()
    ids = seed(engine, args.variants, args.histories, args.measurements, args.run_variants, tpl)
    seed_s = time.perf_counter() - t0

    app = create_app()

    def _db():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = _db
    client = TestClient(app)
    api = "/api/v1"
    s0, rid = ids["scenarios"][0], ids["run_id"]
    r = args.repeats
    out: dict[str, Any] = {}

    def m(name: str, fn: Callable[[], Any], reps: int = r) -> None:
        out[name] = measure(engine, fn, reps)
        print(f"  {name:<42} {out[name]}", flush=True)

    # correctness at scale: catalog variant counts must add up to the seeded variants
    counted, offset = 0, 0
    while True:
        page = client.get(f"{api}/explorer/scenario-catalog", params={"project_ref": PROJECT, "limit": 500, "offset": offset}).json()
        counted += sum(item["variant_count"] for item in page["items"])
        offset += len(page["items"])
        if not page["items"] or offset >= page["total"]:
            break
    out["check.catalog_variant_count"] = {"expected": args.variants, "counted": counted, "ok": counted == args.variants}
    print(f"  check.catalog_variant_count                {out['check.catalog_variant_count']}", flush=True)
    m("explorer.scenario_catalog (allPages 500)", lambda: all_pages(client, f"{api}/explorer/scenario-catalog", {"project_ref": PROJECT}, 500))
    m("explorer.variant_matrix (allPages 1000)", lambda: all_pages(client, f"{api}/explorer/variant-matrix", {"project_ref": PROJECT}, 1000))
    m("scenario.variants s0 (allPages 500)", lambda: all_pages(client, f"{api}/scenarios/{s0}/variants", {}, 500))
    m("calibration.measurements s0", lambda: get_bytes(client, f"{api}/calibration/measurements", {"scenario_id": s0}))
    m("calibration.measurements all", lambda: get_bytes(client, f"{api}/calibration/measurements"))
    m("calibration.coverage_summary", lambda: get_bytes(client, f"{api}/calibration/coverage-summary"))
    m("calibration.coverage s0", lambda: get_bytes(client, f"{api}/calibration/coverage", {"scenario_id": s0}))
    m("calibration.measurement_detail", lambda: get_bytes(client, f"{api}/calibration/measurements/{ids['measurement']}"))
    m("arch.runs list", lambda: get_bytes(client, f"{api}/arch/exploration/runs", {"project_ref": PROJECT}))
    m("arch.run detail (max run)", lambda: get_bytes(client, f"{api}/arch/exploration/runs/{rid}"))
    m("arch.run manifest", lambda: get_bytes(client, f"{api}/arch/exploration/runs/{rid}/manifest"))
    m("arch.predictions board (project)", lambda: get_bytes(client, f"{api}/arch/predictions/board", {"project_ref": PROJECT}))
    m("arch.model_status", lambda: get_bytes(client, f"{api}/arch/model-status", {"project_ref": PROJECT}))

    def promote():
        with Session(engine) as db:
            return svc.promote(db, PromoteRequest(run_id=rid, expected_project_ref=PROJECT))
    m("WRITE promote all (max run)", promote, 0)
    report_id: dict[str, str] = {}

    def report():
        with Session(engine) as db:
            rep = svc.create_report(db, ArchReportRequest(run_id=rid))
            report_id["id"] = rep["id"]
            return len(svc.get_report(db, rep["id"]).rendered_html.encode())
    m("WRITE create report (bytes=html)", report, 0)
    rp = report_id["id"]
    m("arch.report detail (snapshot)", lambda: get_bytes(client, f"{api}/arch/reports/{rp}"))
    m("arch.report html", lambda: get_bytes(client, f"{api}/arch/reports/{rp}/html"))
    m("arch.report stale", lambda: get_bytes(client, f"{api}/arch/reports/{rp}/stale"))
    m("arch.report package", lambda: get_bytes(client, f"{api}/arch/reports/{rp}/package"))
    m("arch.report xlsx", lambda: get_bytes(client, f"{api}/arch/reports/{rp}/xlsx"))
    m("arch.predictions board (after promote)", lambda: get_bytes(client, f"{api}/arch/predictions/board", {"project_ref": PROJECT}))
    with engine.connect() as conn:
        db_mb = conn.execute(text("SELECT pg_database_size(current_database())")).scalar() / 1024**2
        run_mb = conn.execute(text("SELECT pg_column_size(variants) FROM arch_exploration_runs WHERE id=:i"), {"i": rid}).scalar() / 1024**2
    engine.dispose()
    return {"variants": args.variants, "scenarios": len(ids["scenarios"]), "sim_histories": args.histories,
            "measurements": args.measurements, "run_variants": args.run_variants, "repeats": r,
            "template_explore_s": round(tpl_s, 2), "template_summary_kb": tpl_kb,
            "seed_s": round(seed_s, 1), "db_mb": round(db_mb, 1), "run_variants_column_mb": round(run_mb, 1),
            "results": out}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variants", type=int, default=1000)
    parser.add_argument("--histories", type=int, default=None, help="simulation evidence rows on scenario 0 (default min(N, 2000))")
    parser.add_argument("--measurements", type=int, default=None, help="measurement rows on scenario 0 (default min(N/5, 500))")
    parser.add_argument("--run-variants", type=int, default=500, help="variants in the exploration run (API max 500)")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--database-url", default=os.environ.get("BENCH_DATABASE_URL"),
                        help="empty disposable database; default = new PostgreSQL 16 container")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    args.histories = min(args.variants, 2000) if args.histories is None else args.histories
    args.measurements = min(args.variants // 5, 500) if args.measurements is None else args.measurements
    args.run_variants = min(args.run_variants, args.variants)
    if not 1 <= args.variants <= 20000:
        parser.error("variants: 1..20000")
    print(f"bench: {args.variants} variants · {args.histories} sim · {args.measurements} meas · run {args.run_variants}", flush=True)
    if args.database_url:
        report = run(args)
    else:
        from testcontainers.postgres import PostgresContainer
        with PostgresContainer("postgres:16-alpine") as pg:
            args.database_url = pg.get_connection_url()
            report = run(args)
    output = args.output or Path(f"output/bench-scale/scale-{args.variants}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))


if __name__ == "__main__":
    main()
