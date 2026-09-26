"""Create DUMMY measurement inputs (meta.yaml + rail CSV) for a derived project's KPI variants.

Not silicon data. Values are copied from the reference project's evidence (synthetic
measurement + simulation) and scaled, so the in-house flow can be exercised end to end:

    db_<SoC>_<board>/measurements/<variant>/meta.yaml          (edit these in-house)
    db_<SoC>_<board>/measurements/<variant>/rail_power_by_run.csv
      -> python scripts/import_measurements.py db_<SoC>_<board>   -> 03_evidence/<id>.yaml
      -> ETL (scripts/dev_up.ps1)

Run from implementation/ (overwrites only files it created; --force to regenerate):
    python scripts/generate_dummy_measurements.py --db db_Exynos2700_SM-S957B \
        --reference db_Exynos2600_SM-S947B --project sm-s957b
"""
from __future__ import annotations

import argparse
import csv
import io
from collections import defaultdict
from pathlib import Path

import yaml

from scenario_db.authoring.tree import compile_project

MARK = "DUMMY measurement input - not silicon data. Replace values with the in-house capture."
POWER_SCALE = 0.93      # arbitrary "next-gen" factor so dummy values differ from the reference
SW_SCALE = 1.05
RUN_SPREAD = (-0.012, 0.0, 0.012)   # deterministic 3-run spread


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _index_reference(ref_dir: Path) -> tuple[dict, dict]:
    meas, sim = {}, {}
    for p in sorted((ref_dir / "03_evidence").glob("*.yaml")):
        d = _load(p)
        v = d.get("variant_ref")
        if d.get("kind") == "evidence.measurement":
            # prefer a real-format capture over synthetic rescales
            if v not in meas or "synth" in meas[v]["id"]:
                meas[v] = d
        elif d.get("kind") == "evidence.simulation" and (d.get("kpi") or {}).get("total_bw_mbs"):
            # prefer a run with the per-DMA breakdown (read/write per IP)
            if v not in sim or (d.get("dma_breakdown") and not sim[v].get("dma_breakdown")):
                sim[v] = d
    return meas, sim


def _chain(variant: dict, parents: dict[str, str | None]) -> list[str]:
    out, cur = [], variant["id"]
    while cur and cur not in out:
        out.append(cur)
        cur = parents.get(cur)
    return out


def _kpi_mean(value) -> float | None:
    if isinstance(value, dict):
        return value.get("mean")
    return value


def _rail_csv(vdd_power: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["run", "rail", "voltage_v", "current_ma", "power_mw"])
    for run, d in enumerate(RUN_SPREAD, start=1):
        for rail, r in vdd_power.items():
            p = float(r.get("power_mw") or r.get("mean_mw") or 0.0) * POWER_SCALE * (1 + d)
            v = float(r.get("voltage_v") or 0.0)
            i = p / v if v > 0.05 else float(r.get("current_ma") or 0.0) * POWER_SCALE * (1 + d)
            w.writerow([run, rail, f"{v:.4f}", f"{i:.4f}", f"{p:.4f}"])
    return buf.getvalue()


def _bw_observations(sim: dict) -> list[dict]:
    obs = [{"metric_id": "bandwidth.total", "scope": {"kind": "scenario", "ref": sim["scenario_ref"]},
            "unit": "MB/s", "stats": {"mean": round(sim["kpi"]["total_bw_mbs"] * POWER_SCALE, 3)}}]
    per_ip: dict[tuple[str, str], float] = defaultdict(float)
    for row in sim.get("dma_breakdown") or []:
        if row.get("direction") in ("read", "write") and row.get("bw_mbs"):
            per_ip[(row["direction"], row.get("hw_name") or row.get("node_id"))] += float(row["bw_mbs"])
    for (direction, ip), bw in sorted(per_ip.items(), key=lambda x: (x[0][0], x[0][1])):
        mean = bw * POWER_SCALE
        obs.append({"metric_id": f"bandwidth.{direction}", "scope": {"kind": "ip", "ref": ip},
                    "unit": "MB/s", "stats": {"mean": round(mean, 3), "p95": round(mean * 1.08, 3)}})
    return obs


def _sw_timing(meas: dict) -> list[dict]:
    out = []
    for t in meas.get("sw_task_timing") or []:
        row = {"task": t["task"], "timing_scope": t.get("timing_scope") or "exclusive_sw"}
        for k in ("min_ms", "mean_ms", "p50_ms", "p95_ms", "max_ms"):
            if t.get(k) is not None:
                row[k] = round(float(t[k]) * SW_SCALE, 3)
        mean = row.get("mean_ms")
        if mean is None:
            continue
        row.setdefault("min_ms", round(mean * 0.85, 3))                 # summary import needs min/mean/max
        row.setdefault("max_ms", row.get("p95_ms") or round(mean * 1.3, 3))
        row.update(samples=int(t.get("samples") or 1), count_per_frame=t.get("count_per_frame") or 1.0,
                   value_source="assumed", source_note=MARK)
        out.append(row)
    return out


def build_meta(project_id: str, scenario_id: str, variant_id: str, meas: dict, sim: dict | None,
               sw_profile: str, revision: int = 1) -> dict:
    kpi = meas.get("kpi") or {}
    meta = {
        "schema_version": "2.2",
        "id": f"meas-dummy-{scenario_id.removeprefix('uc-')}-{variant_id}-evt0",
        "project_ref": project_id, "scenario_ref": scenario_id, "variant_ref": variant_id,
        "measured_at": "2026-09-27T10:00:00+09:00",
        "execution_context": {"silicon_rev": "EVT0", "sw_baseline_ref": sw_profile, "thermal": "room",
                              "ambient_temp_c": 25.0, "power_state": "discharging", "method": "measurement"},
        "provenance": {"revision": revision, "device_id": "DUMMY", "collection_method": "dummy_fixture",
                       "collection_tool_versions": {"generator": "generate_dummy_measurements.py"},
                       "sample_count": len(RUN_SPREAD), "duration_per_sample_s": 30.0, "confidence_level": 0.95},
        "kpi": {k: v for k, v in {
            "frame_latency_ms": _kpi_mean(kpi.get("frame_latency_ms")),
            "fps_effective": _kpi_mean(kpi.get("fps_effective"))}.items() if v is not None},
        "aggregation_strategy": "mean_over_runs",
        "power": {"format": "rail_long", "csv": "rail_power_by_run.csv", "total_power_rails": [],
                  "rails": {r: {k: v for k, v in {"domain": d.get("domain")}.items() if v}
                            for r, d in (meas.get("vdd_power") or {}).items()}},
        "artifacts": [{"type": "power_monitor_csv", "storage": "fileshare", "source": "rail_power_by_run.csv",
                       "path": f"artifacts/{project_id}/{scenario_id}/{variant_id}/dummy-evt0/rail_power_by_run.csv",
                       "mime": "text/csv"}],
    }
    if sim:
        meta["metric_observations"] = _bw_observations({**sim, "scenario_ref": scenario_id})
    timing = _sw_timing(meas)
    if timing:
        meta["sw_task_timing"] = timing
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--reference", type=Path, required=True)
    ap.add_argument("--project", required=True, help="authoring project key (derived project)")
    ap.add_argument("--authoring", type=Path, default=Path("authoring"))
    ap.add_argument("--force", action="store_true", help="overwrite existing meta.yaml / CSV")
    ap.add_argument("--revision", type=int, default=1,
                    help="provenance.revision to write (raise it when regenerating evidence already in a DB)")
    args = ap.parse_args()

    report = compile_project(args.authoring, args.project)
    docs = [d.data for d in report["documents"] if isinstance(d.data, dict)]
    project = next(d for d in docs if d.get("kind") == "project")
    project_id = project["id"]
    sw_profile = (project.get("globals") or {}).get("default_sw_profile_ref") or project["metadata"]["default_sw_profile_ref"]
    overlays = __import__("scenario_db.authoring.tree", fromlist=["load_project"]).load_project(
        args.authoring, args.project)
    meas_idx, sim_idx = _index_reference(args.reference)
    written, skipped = [], []
    for sc in (d for d in docs if d.get("kind") == "scenario.usecase"):
        src = overlays.scenarios[sc["id"]]
        parents = {e["id"]: e.get("extends") for e in src["variants"]}
        for v in sc.get("variants") or []:
            if "exploration-only" in (v.get("tags") or []):
                continue
            chain = _chain(v, parents)
            meas = next((meas_idx[c] for c in chain if c in meas_idx), None)
            sim = next((sim_idx[c] for c in chain if c in sim_idx), None)
            if meas is None:
                skipped.append(v["id"])
                continue
            out = args.db / "measurements" / v["id"]
            if (out / "meta.yaml").exists() and not args.force:
                skipped.append(v["id"] + " (exists)")
                continue
            out.mkdir(parents=True, exist_ok=True)
            meta = build_meta(project_id, sc["id"], v["id"], meas, sim, sw_profile, args.revision)
            header = (f"# {MARK}\n# Values from {meas['id']}" + (f" + {sim['id']}" if sim else "")
                      + f" (reference {chain[-1] if chain[0] not in meas_idx else chain[0]}), scaled.\n"
                      "# Update: edit values/CSV, bump provenance.revision, then run scripts/import_measurements.py\n")
            (out / "meta.yaml").write_text(header + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=110),
                                           encoding="utf-8", newline="\n")
            (out / "rail_power_by_run.csv").write_text(_rail_csv(meas.get("vdd_power") or {}), encoding="utf-8", newline="\n")
            written.append(v["id"])
    print(yaml.safe_dump({"written": written, "skipped": skipped}, sort_keys=False))


if __name__ == "__main__":
    main()
