"""Stage timing budget over fixture scenario variants (read-only, no DB).

RT keeps the 25 % SW margin rule; NRT (MTNR..MCSC) and GDC (after EIS) get the
HW time left after their SW runtime + latency; outputs must keep 1000/fps.

Run from implementation/:
  uv run python scripts/timing_budget_report.py --statistic max \
      --dvfs-table db_fixtures_Exynos2600_S26Plus/00_hw/dvfs-exynos2600-sample-v0.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_is_v15_camera import FIXTURE, graph_from_fixture, read  # noqa: E402

from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.models.definition.usecase import Usecase  # noqa: E402
from scenario_db.sim.models import DVFSTable  # noqa: E402
from scenario_db.sim.timing_budget import (  # noqa: E402
    DERIVED_VARIANT_MARKERS,
    TimingBudgetOptions,
    analyze_timing_budget,
    fleet_row,
)

ROOT = Path(__file__).resolve().parents[1]


def load_catalog() -> dict:
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(
            id=d["id"],
            schema_version=d["schema_version"],
            category=d["category"],
            hierarchy=d["hierarchy"],
            capabilities=d["capabilities"],
            yaml_sha256="fixture",
        )
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--scenario", default="02_definition/uc-camera-recording.yaml")
    parser.add_argument("--variants", nargs="*")
    parser.add_argument("--statistic", default="max", choices=["min", "mean", "max"])
    parser.add_argument("--runtime-scale", type=float, default=1.0)
    parser.add_argument("--eis", default="auto", choices=["auto", "on", "off"])
    parser.add_argument("--dvfs-table", help="soc.dvfs_table YAML")
    parser.add_argument("--detail", nargs="*", default=[], help="variants to dump in full (JSON)")
    parser.add_argument("--out", default="output/timing-budget")
    args = parser.parse_args()

    raw = read(FIXTURE / args.scenario)
    Usecase.model_validate(raw)
    catalog = load_catalog()
    tables = {}
    if args.dvfs_table:
        doc = read(Path(args.dvfs_table))
        tables = {k: DVFSTable.model_validate(v) for k, v in (doc.get("domains") or {}).items()}
    options = TimingBudgetOptions(
        statistic=args.statistic, runtime_scale=args.runtime_scale, eis=args.eis
    )
    variants = args.variants or [
        v["id"] for v in raw["variants"] if not any(m in v["id"] for m in DERIVED_VARIANT_MARKERS)
    ]
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    rows, errors, started = [], [], time.time()
    for variant in variants:
        try:
            report = analyze_timing_budget(
                graph_from_fixture(raw, variant, catalog), options, dvfs_tables=tables
            )
        except Exception as exc:  # keep going over the fleet
            errors.append({"variant_id": variant, "error": f"{type(exc).__name__}: {exc}"})
            continue
        rows.append(fleet_row(report))
        if variant in args.detail:
            (out / f"{variant}.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
            )
    payload = {
        "options": options.model_dump(),
        "dvfs_table": args.dvfs_table,
        "rows": rows,
        "errors": errors,
        "elapsed_s": round(time.time() - started, 2),
    }
    (out / "fleet.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (out / "fleet.md").write_text(render(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "rows": len(rows),
                "errors": len(errors),
                "elapsed_s": payload["elapsed_s"],
                "out": str(out),
            }
        )
    )
    return 0


def _f(v, d=1):
    return "—" if v is None else f"{v:.{d}f}"


def render(payload: dict) -> str:
    lines = [
        "# Stage timing budget",
        "",
        f"- statistic: {payload['options']['statistic']} · SW scale ×{payload['options']['runtime_scale']} · EIS {payload['options']['eis']}",
        f"- DVFS: {payload['dvfs_table'] or 'none (continuous clock, reference voltage)'}",
        "",
        "| Variant | fps | EIS | RT HW/budget | NRT SW / HW budget | NRT clk rule→set (L) | Post SW / HW budget | Interval P/V | Latency P/V | Power CPU/HW/BW mW | BW MB/s | Verdict |",
        "| --- | ---: | :---: | --- | --- | --- | --- | --- | --- | --- | ---: | --- |",
    ]
    for r in payload["rows"]:
        s, c = r["stages"], r["clocks"]
        lines.append(
            f"| {r['variant_id']} | {r['fps']:g} | {'ON' if r['eis_on'] else '—'} | {_f(s['rt']['hw_ms'])}/{_f(s['rt']['budget_ms'])} "
            f"| {_f(s['nrt']['sw_ms'])} / {_f(s['nrt']['budget_ms'])} | {_f(c['nrt']['rule_mhz'], 0)}→{_f(c['nrt']['set_mhz'], 0)} (L{c['nrt']['level'] if c['nrt']['level'] is not None else '—'}) "
            f"| {_f(s['post']['sw_ms'])} / {_f(s['post']['budget_ms'])} | {_f(r['intervals']['preview_max_ms'], 2)}/{_f(r['intervals']['video_max_ms'], 2)} "
            f"| {_f(r['latency']['preview_ms'], 0)}/{_f(r['latency']['video_ms'], 0)} | {_f(r['power']['cpu_mw'], 0)}/{_f(r['power']['hw_mw'], 0)}/{_f(r['power']['bw_mw'], 0)} "
            f"| {_f(r['bw']['total_mbs'], 0)} | {r['verdict']['status']} |"
        )
    if payload["errors"]:
        lines += ["", "## Errors", ""] + [
            f"- {e['variant_id']}: {e['error']}" for e in payload["errors"]
        ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
