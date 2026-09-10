"""Reproducible read benchmark on a disposable PostgreSQL 16 container.

Run from implementation: uv run python scripts/bench_large_reads.py --baseline-ref bcee4a3
No application database is accessed. The baseline is read from local Git.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import statistics
import subprocess
import time
import tracemalloc
from types import ModuleType

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

from scenario_db.api.routers.catalog import list_catalog
from scenario_db.api.routers.definition import list_scenarios
from scenario_db.api.schemas.definition import ScenarioResponse
from scenario_db.api.schemas.query import QueryRequest
from scenario_db.db.base import Base
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.db.models.evidence import Evidence
from scenario_db.query_engine import service


def seed(engine, scenario_count, histories):
    with Session(engine) as db:
        db.add(Project(id="bench-project", schema_version="2.2", yaml_sha256="bench",
                       metadata_={"name": "Benchmark board", "soc_ref": "bench-soc"}))
        db.flush()
        db.execute(Scenario.__table__.insert(), [dict(id=f"bench-{i:05}", project_ref="bench-project",
            schema_version="2.2", yaml_sha256="bench", metadata={"name": f"Scenario {i}", "category": ["camera"]},
            pipeline={"nodes": [], "edges": [], "buffers": {}, "padding": "x" * 8192}) for i in range(scenario_count)])
        db.execute(ScenarioVariant.__table__.insert(), [dict(scenario_id=f"bench-{i:05}", id="target" if i == 0 else "ordinary",
            severity="nominal", design_conditions={"fps": 30}) for i in range(scenario_count)])
        db.execute(Evidence.__table__.insert(), [dict(id=f"bench-evidence-{i:05}", scenario_ref="bench-00000", variant_ref="target",
            schema_version="2.2", kind="evidence.simulation", yaml_sha256="bench", aggregation={},
            execution_context={"padding": "c" * 4096}, resolution_result={"padding": "r" * 4096},
            kpi={"power": i}, run_info={"timestamp": f"2026-01-01T{(i // 3600) % 24:02}:{(i // 60) % 60:02}:{i % 60:02}Z"}) for i in range(histories)])
        db.commit()
    with engine.begin() as conn:
        conn.execute(text("ANALYZE"))


def measure(engine, fn, repeats):
    fn()  # warm cache; latency excludes tracing overhead
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        result = fn()
        times.append((time.perf_counter() - start) * 1000)
    statements = []
    def capture(_conn, cursor, sql, _params, _ctx, _many):
        if sql.startswith("SELECT"):
            statements.append((sql, cursor.rowcount))
    event.listen(engine, "after_cursor_execute", capture)
    tracemalloc.start()
    try:
        fn()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        event.remove(engine, "after_cursor_execute", capture)
    with ThreadPoolExecutor(max_workers=4) as pool:
        def timed(_):
            start = time.perf_counter()
            fn()
            return (time.perf_counter() - start) * 1000
        concurrent = list(pool.map(timed, range(12)))
    return {"median_ms": round(statistics.median(times), 2),
            "p95_ms": round(sorted(times)[math.ceil(len(times) * .95) - 1], 2),
            "concurrent_4_p95_ms": round(sorted(concurrent)[-1], 2),
            "peak_python_mib": round(peak / 1024**2, 2),
            "selects": len(statements), "returned_rows": sum(max(0, n) for _, n in statements),
            "json_bytes": len(json.dumps(result).encode())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default="bcee4a3")
    parser.add_argument("--scenarios", type=int, default=1500)
    parser.add_argument("--histories", type=int, default=3000)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--output", type=Path, default=Path("output/large-reads/benchmark.json"))
    args = parser.parse_args()
    if not (1 <= args.scenarios <= 5000 and 1 <= args.histories <= 20000 and args.repeats >= 1):
        parser.error("scenarios: 1..5000; histories: 1..20000; repeats >= 1")
    baseline = ModuleType("baseline_query_service")
    source = subprocess.check_output(["git", "show", f"{args.baseline_ref}:src/scenario_db/query_engine/service.py"], text=True, encoding="utf-8")
    exec(compile(source, "baseline_query_service.py", "exec"), baseline.__dict__)
    with PostgresContainer("postgres:16-alpine") as pg:
        engine = create_engine(pg.get_connection_url())
        Base.metadata.create_all(engine)
        seed(engine, args.scenarios, args.histories)
        request = QueryRequest(where=[{"field": "variant.id", "value": "target"}], limit=50)
        def run(module):
            with Session(engine) as db:
                return module.query_variants(db, request).model_dump()
        assert run(baseline) == run(service), "Query response changed"
        def full_list():
            with Session(engine) as db:
                response = list_scenarios(project_ref="bench-project", soc_ref=None, board_type=None,
                    limit=100, offset=0, sort_by=None, sort_dir="asc", db=db)
                return {"items": [ScenarioResponse.model_validate(row).model_dump() for row in response.items], "total": response.total}
        def summary_list():
            with Session(engine) as db:
                return list_catalog("scenarios", q="", id=None, soc_ref=None, project_ref="bench-project", board_type=None,
                    scenario_id=None, sort_by="id", sort_dir="asc", limit=100, offset=0, db=db).model_dump()
        assert [i["id"] for i in full_list()["items"]] == [i["id"] for i in summary_list()["items"]]
        report = {"database": "isolated PostgreSQL 16", "baseline_ref": args.baseline_ref,
                  "scenarios": args.scenarios, "histories": args.histories, "samples": args.repeats,
                  "query_before": measure(engine, lambda: run(baseline), args.repeats),
                  "query_after": measure(engine, lambda: run(service), args.repeats),
                  "list_before": measure(engine, full_list, args.repeats),
                  "list_after": measure(engine, summary_list, args.repeats)}
        with engine.connect() as conn:
            plan = conn.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT id FROM scenarios s WHERE EXISTS "
                "(SELECT 1 FROM scenario_variants v WHERE v.scenario_id=s.id AND lower(btrim(v.id))='target')")).scalar()
        report["candidate_plan"] = plan
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k != "candidate_plan"}, indent=2))
        engine.dispose()


if __name__ == "__main__":
    main()
