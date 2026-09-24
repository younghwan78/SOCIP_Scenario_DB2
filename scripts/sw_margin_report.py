"""Timing-aware SW margin report over fixture scenario variants (read-only).

Compares the rule-of-thumb clock margin (default 25 %: HW time <= 75 % of the
frame) with the margin the pipeline timeline actually needs, given the SW task
runtime / latency recorded for the scenario (previous-project basis) and a
next-project SW growth sweep.

Run from implementation/:
  uv run python scripts/sw_margin_report.py --statistic mean max \
      --ip-overhead-ms 1.0,0.6 --out output/sw-margin

Nothing is written to the DB or fixtures.
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
from scenario_db.sim.sw_margin import SwMarginOptions, analyze_sw_margin  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DERIVED_MARKERS = ("-explored-", "-timing-min", "-timing-max")


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


def load_dvfs(path: str | None) -> dict[str, DVFSTable]:
    if not path:
        return {}
    doc = read(Path(path))
    return {
        key: DVFSTable.model_validate(value) for key, value in (doc.get("domains") or {}).items()
    }


def parse_stat(text: str) -> dict:
    """'mean' or 'min/mean/max' in ms -> TimingStat payload."""
    parts = [float(x) for x in text.split("/")]
    if len(parts) == 1:
        parts = parts * 3
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("use MEAN or MIN/MEAN/MAX")
    return {"min_ms": parts[0], "mean_ms": parts[1], "max_ms": parts[2]}


def recommendations(row: dict, period_ms: float) -> list[str]:
    tips: list[str] = []
    rule, required = row["rule"], row["required"]
    critical = row.get("critical_path") or {}
    headroom = (row.get("growth_headroom_at_rule") or {}).get("max_runtime_scale")
    if rule["verdict"] == "clock_unreachable":
        binding = " ".join(required["binding"][:3])
        cause = (
            "shared HW resource overloaded (multi-stream time-multiplexing) - check IP instance count / stream split"
            if "C1 load" in binding and "CPU" not in binding
            else "SW path dominates - cut SW runtime/latency on the chain or relax the latency budget"
        )
        tips.append(
            f"Clock alone cannot fix it: needs margin {required['margin']:.1%} "
            f"(HW time <= {required['hw_time_limit_ms']:.1f} ms); {cause}."
        )
    elif required["margin"] is None:
        tips.append(
            "Upper-bound margin still fails: SW path alone breaks the budget -> SW pipelining/offload required."
        )
    elif rule["verdict"] == "rule_insufficient":
        tips.append(
            f"Rule {row['rule_margin']:.0%} is insufficient: needs {required['margin']:.1%} "
            f"(HW time <= {required['hw_time_limit_ms']:.1f} ms); binding: {'; '.join(required['binding'][:2])}."
        )
    elif rule["verdict"] == "rule_over_provisioned":
        tips.append(
            f"Rule over-provisions by {rule['margin_gap']:.1%}: clock can drop to margin {required['margin']:.1%} "
            "(power saving once DVFS/voltage scaling is modelled) - confirm per-IP driver overhead first."
        )
    share = (critical.get("share_pct") or {}).get("sw", 0.0) + (
        critical.get("share_pct") or {}
    ).get("serial_overhead", 0.0)
    if share >= 25.0:
        tips.append(
            f"SW + serialized overhead is {share:.0f}% of the {critical.get('sink')} critical latency "
            "-> optimize/parallelize SW on the chain before raising HW clock."
        )
    jitter = max((rule.get("latency_jitter_ms") or {}).values(), default=0.0)
    if not rule["feasible"] and jitter > period_ms:
        tips.append(
            f"At the rule the pipeline backs up (latency grows {jitter:.0f} ms over the run): throughput limit, not jitter."
        )
    elif jitter > 0.1 * period_ms:
        tips.append(
            f"Frame-to-frame latency jitter {jitter:.1f} ms from shared-CPU contention -> separate task affinity/priority."
        )
    if headroom is not None and headroom < 1.2:
        tips.append(
            f"SW growth headroom at the rule is only x{headroom:.2f}: next-project SW +20% breaks timing."
        )
    return tips


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--scenario", default="02_definition/uc-camera-recording.yaml")
    parser.add_argument("--variants", nargs="*", help="default: all non-derived variants")
    parser.add_argument(
        "--statistic", nargs="+", default=["mean", "max"], choices=["min", "mean", "max"]
    )
    parser.add_argument("--rule-margin", type=float, default=0.25)
    parser.add_argument("--latency-budget-frames", type=float, default=3.0)
    parser.add_argument(
        "--sink-budget", action="append", default=[], help="NODE=FRAMES, e.g. storage_write=4"
    )
    parser.add_argument(
        "--ip-overhead-ms",
        type=str,
        default=None,
        help="default serialized overhead per M2M IP: SETUP,COMPLETION each MEAN or MIN/MEAN/MAX",
    )
    parser.add_argument("--growth", type=float, nargs="*", default=[1.0, 1.1, 1.2, 1.3, 1.5])
    parser.add_argument(
        "--samples", type=int, default=0, help="Monte Carlo samples per variant/statistic"
    )
    parser.add_argument("--dvfs-table", help="soc.dvfs_table YAML")
    parser.add_argument("--out", default="output/sw-margin")
    args = parser.parse_args()

    raw = read(FIXTURE / args.scenario)
    Usecase.model_validate(raw)
    catalog = load_catalog()
    dvfs = load_dvfs(args.dvfs_table)
    overhead = None
    if args.ip_overhead_ms:
        setup, completion = args.ip_overhead_ms.split(",")
        overhead = {
            "setup": parse_stat(setup),
            "completion": parse_stat(completion),
            "source": "cli assumption",
        }
    sink_budget = {k: float(v) for k, v in (item.split("=") for item in args.sink_budget)}
    variants = args.variants or [
        v["id"] for v in raw["variants"] if not any(m in v["id"] for m in DERIVED_MARKERS)
    ]
    rows, errors = [], []
    started = time.time()
    for variant in variants:
        for statistic in args.statistic:
            options = SwMarginOptions(
                statistic=statistic,
                rule_margin=args.rule_margin,
                growth_sweep=args.growth,
                default_ip_overhead=overhead,
                monte_carlo_samples=args.samples,
                per_ip_plan=False,
                constraints={
                    "latency_budget_frames": args.latency_budget_frames,
                    "sink_budget_frames": sink_budget,
                },
            )
            try:
                graph = graph_from_fixture(raw, variant, catalog)
                row = analyze_sw_margin(graph, options, dvfs_tables=dvfs)
            except Exception as exc:  # report and continue over the fleet
                errors.append(
                    {
                        "variant": variant,
                        "statistic": statistic,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue
            row["recommendations"] = recommendations(row, row["period_ms"])
            rows.append(row)
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "assumptions": {
            "rule_margin": args.rule_margin,
            "latency_budget_frames": args.latency_budget_frames,
            "sink_budget_frames": sink_budget,
            "default_ip_overhead": overhead,
            "dvfs_table": args.dvfs_table,
            "sw_timing_source": "scenario node_configs.sw_timing (value_source per task)",
        },
        "rows": rows,
        "errors": errors,
        "elapsed_s": round(time.time() - started, 1),
    }
    (out / "sw_margin_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "sw_margin_report.md").write_text(render_markdown(payload), encoding="utf-8")
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


def _pct(value) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def render_markdown(payload: dict) -> str:
    rows = payload["rows"]
    a = payload["assumptions"]
    lines = [
        "# SW timing margin report",
        "",
        f"- Rule of thumb: margin {a['rule_margin']:.0%} (HW time <= {1 - a['rule_margin']:.0%} of frame, x(1+h_blank) in the sim)",
        f"- Latency budget: {a['latency_budget_frames']} frames (declared display sinks) · per-sink: {a['sink_budget_frames'] or '—'}",
        f"- Per-IP serialized SW overhead: {a['default_ip_overhead'] or 'none (pipeline SW only)'}",
        f"- DVFS table: {a['dvfs_table'] or 'none (continuous clock, no voltage scaling)'}",
        "",
        "## Summary",
        "",
        "| Variant | Stat | fps | Required margin | HW limit ms | Rule verdict | Gap | Growth headroom @rule | SW+ovh share | Binding |",
        "| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for r in rows:
        crit = r.get("critical_path") or {}
        share = crit.get("share_pct") or {}
        lines.append(
            "| {v} | {s} | {fps:g} | {m} | {lim} | {verdict} | {gap} | {hr} | {sh} | {b} |".format(
                v=r["variant_id"],
                s=r["statistic"],
                fps=r["fps"],
                m=_pct(r["required"]["margin"]),
                lim=r["required"]["hw_time_limit_ms"]
                if r["required"]["hw_time_limit_ms"] is not None
                else "—",
                verdict=r["rule"]["verdict"],
                gap=_pct(r["rule"]["margin_gap"]),
                hr=(r["growth_headroom_at_rule"] or {}).get("max_runtime_scale", "—"),
                sh=f"{share.get('sw', 0) + share.get('serial_overhead', 0):.0f}%" if share else "—",
                b=(
                    r["required"]["binding"][0]
                    if r["required"]["binding"]
                    else r["required"]["status"]
                ).replace("|", "/"),
            )
        )
    solved = [r for r in rows if r["required"]["margin"] is not None]
    ranked = sorted(
        solved,
        key=lambda r: (
            r["rule"]["margin_gap"],
            (r["growth_headroom_at_rule"] or {}).get("max_runtime_scale") or 0,
        ),
    )
    lines += ["", "## Top 5 smallest SW margin (rule margin - required margin)", ""]
    for i, r in enumerate(ranked[:5], 1):
        lines.append(
            f"### {i}. {r['variant_id']} ({r['statistic']}) — gap {_pct(r['rule']['margin_gap'])}"
        )
        lines.append("")
        sweep = ", ".join(f"x{g['runtime_scale']}: {_pct(g['margin'])}" for g in r["growth_sweep"])
        lines.append(f"- Required margin by SW growth: {sweep}")
        crit = r.get("critical_path") or {}
        if crit:
            lines.append(
                f"- Critical {crit['sink']}: {crit['latency_ms']} / {crit['budget_ms']} ms · HW {crit['hw_ms']} · SW {crit['sw_ms']} "
                f"· overhead {crit['serial_overhead_ms']} · wait {crit['wait_ms']} ms"
            )
        for tip in r["recommendations"] or ["No action: rule adequate with growth headroom."]:
            lines.append(f"- {tip}")
        lines.append("")
    unsolved = [r for r in rows if r["required"]["margin"] is None]
    if unsolved:
        lines += ["## No feasible margin (model or spec limit)", ""]
        for r in unsolved:
            binding = "; ".join(r["required"]["binding"][:2]).replace("|", "/")
            lines.append(f"- {r['variant_id']} ({r['statistic']}): {binding}")
        lines.append("")
    if payload["errors"]:
        lines += ["## Skipped", ""] + [
            f"- {e['variant']} ({e['statistic']}): {e['error']}" for e in payload["errors"]
        ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
