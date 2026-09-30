"""Fit the ``mif-linear`` BW power model from measured scenarios.

    P_mem = sum_l r_l * base_l + e_rd * RD[GB/s] + e_wr * WR[GB/s]

one row per measured scenario: memory-rail power (MIF + DRAM rails), DMC read
/ write bandwidth (all masters) and the MIF level (dominant level, or level
residency r_l). Ordinary least squares over the rows gives e_rd, e_wr and a
base (no-traffic) power per MIF level; residuals per row are reported so the
confidence of the calibration is visible, not hidden in a total.

Inputs:
- CSV: ``label, read_mbs, write_mbs, mem_power_mw`` plus ``mif_mhz`` or
  residency columns ``mif@<MHz>`` (shares).
- measurement evidence YAMLs: ``bandwidth.mem_read/mem_write`` (scope mif),
  memory rails from ``vdd_power`` (``--rails``), MIF level from
  ``clock.ip_dominant`` / ``clock.ip_residency`` of the MIF clock ref.

CLI: ``python -m scenario_db.sim.bw_fit --csv rows.csv`` or
``--evidence-dir <dir> --rails BUCK_MIF,BUCK_DRAM --mif-ref MIF``.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class FitRow:
    label: str
    read_mbs: float
    write_mbs: float
    mem_power_mw: float
    mif_residency: dict[float, float] = field(default_factory=dict)   # MHz -> share


def fit_mif_linear(rows: list[FitRow], *, same_rw: bool = False,
                   capacity_mbs: dict[float, float] | None = None) -> dict[str, Any]:
    import numpy as np

    if not rows:
        raise ValueError("no rows to fit")
    levels = sorted({mhz for r in rows for mhz in r.mif_residency})
    if not levels:
        raise ValueError("rows need a MIF level (mif_mhz or mif@<MHz> residency)")
    columns = ["e_rw"] if same_rw else ["e_read", "e_write"]
    columns += [f"base@{mhz:g}" for mhz in levels]
    matrix, target = [], []
    for row in rows:
        total = sum(row.mif_residency.values()) or 1.0
        rd, wr = row.read_mbs / 1000.0, row.write_mbs / 1000.0
        energy = [rd + wr] if same_rw else [rd, wr]
        matrix.append(energy + [row.mif_residency.get(mhz, 0.0) / total for mhz in levels])
        target.append(row.mem_power_mw)
    a, y = np.asarray(matrix, dtype=float), np.asarray(target, dtype=float)
    coef, *_ = np.linalg.lstsq(a, y, rcond=None)
    pred = a @ coef
    resid = y - pred
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float((resid ** 2).sum()) / ss_tot if ss_tot > 0 else None
    rmse = float(np.sqrt((resid ** 2).mean()))
    values = dict(zip(columns, (float(c) for c in coef)))
    warnings = []
    if len(rows) < len(columns) + 2:
        warnings.append(f"{len(rows)} rows for {len(columns)} unknowns: under-determined, add scenarios")
    negative = [k for k, v in values.items() if v < 0]
    if negative:
        warnings.append(f"negative coefficients {negative}: rows do not separate levels / directions; "
                        "try --same-rw or more varied scenarios")
    e_read = values.get("e_rw", values.get("e_read", 0.0))
    e_write = values.get("e_rw", values.get("e_write", 0.0))
    capacity_mbs = capacity_mbs or {}
    bw_block = {
        "e_read_mw_per_gbps": round(max(0.0, e_read), 4),
        "e_write_mw_per_gbps": round(max(0.0, e_write), 4),
        "mif_opps": [
            {"mhz": mhz, "base_mw": round(max(0.0, values[f"base@{mhz:g}"]), 3),
             **({"capacity_mbs": capacity_mbs[mhz]} if mhz in capacity_mbs else {})}
            for mhz in levels
        ],
        "fit": {"method": "least_squares", "rows": len(rows), "r2": None if r2 is None else round(r2, 4),
                "rmse_mw": round(rmse, 3)},
    }
    residuals = [
        {"label": r.label, "measured_mw": round(float(m), 3), "predicted_mw": round(float(p), 3),
         "error_mw": round(float(p - m), 3), "error_pct": round(float((p - m) / m * 100), 2) if m else None}
        for r, m, p in zip(rows, y, pred)
    ]
    return {"bw": bw_block, "coefficients": values, "residuals": residuals, "warnings": warnings}


# ------------------------------------------------------------------ loaders
def rows_from_csv(path: Path) -> list[FitRow]:
    rows = []
    with path.open(encoding="utf-8", newline="") as fh:
        for index, raw in enumerate(csv.DictReader(line for line in fh if not line.startswith("#")), start=1):
            residency = {float(k.split("@", 1)[1]): float(v) for k, v in raw.items()
                         if k and k.startswith("mif@") and v not in (None, "")}
            if not residency and raw.get("mif_mhz"):
                residency = {float(raw["mif_mhz"]): 1.0}
            rows.append(FitRow(label=raw.get("label") or f"row{index}", read_mbs=float(raw["read_mbs"]),
                               write_mbs=float(raw["write_mbs"]), mem_power_mw=float(raw["mem_power_mw"]),
                               mif_residency=residency))
    return rows


def _obs_value(item: dict[str, Any]) -> float | None:
    value = item.get("value")
    if value is None:
        value = (item.get("stats") or {}).get("mean")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def row_from_evidence(doc: dict[str, Any], *, rails: list[str], mif_ref: str) -> FitRow | None:
    read = write = None
    residency: dict[float, float] = {}
    dominant = None
    for item in doc.get("metric_observations") or []:
        metric = item.get("metric_id")
        scope = item.get("scope") or {}
        if metric == "bandwidth.mem_read" and scope.get("kind") in ("mif", "dram"):
            read = _obs_value(item)
        elif metric == "bandwidth.mem_write" and scope.get("kind") in ("mif", "dram"):
            write = _obs_value(item)
        elif metric == "clock.ip_residency" and str(scope.get("ref", "")).startswith(f"{mif_ref}@"):
            value = _obs_value(item)
            if value:
                residency[float(str(scope["ref"]).rsplit("@", 1)[1])] = value
        elif metric == "clock.ip_dominant" and scope.get("ref") == mif_ref:
            dominant = _obs_value(item)
    power = 0.0
    found = False
    for rail, value in (doc.get("vdd_power") or {}).items():
        if rail in rails:
            number = value.get("mean", value.get("total_mw")) if isinstance(value, dict) else value
            if isinstance(number, dict):
                number = number.get("mean")
            if isinstance(number, (int, float)):
                power += float(number)
                found = True
    if not residency and dominant:
        residency = {dominant: 1.0}
    if read is None or write is None or not found or not residency:
        return None
    return FitRow(label=str(doc.get("id") or doc.get("variant_ref")), read_mbs=read, write_mbs=write,
                  mem_power_mw=power, mif_residency=residency)


def rows_from_evidence_dir(folder: Path, *, rails: list[str], mif_ref: str) -> tuple[list[FitRow], list[str]]:
    rows, skipped = [], []
    for path in sorted(folder.rglob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if doc.get("kind") != "evidence.measurement":
            continue
        row = row_from_evidence(doc, rails=rails, mif_ref=mif_ref)
        (rows.append(row) if row else skipped.append(path.name))
    return rows, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scenario_db.sim.bw_fit",
                                     description="Fit mif-linear BW power coefficients from measured scenarios.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", type=Path)
    src.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--rails", default="", help="memory rails to sum (evidence mode), comma separated")
    parser.add_argument("--mif-ref", default="MIF", help="clock scope ref of the MIF clock (evidence mode)")
    parser.add_argument("--same-rw", action="store_true", help="one energy coefficient for read and write")
    parser.add_argument("--capacity", default="", help="MHz=MB/s,... governor capacities to copy into mif_opps")
    parser.add_argument("--out", type=Path, help="write the bw block (YAML) here")
    args = parser.parse_args(argv)
    skipped: list[str] = []
    if args.csv:
        rows = rows_from_csv(args.csv)
    else:
        rails = [r.strip() for r in args.rails.split(",") if r.strip()]
        if not rails:
            parser.error("--rails is required with --evidence-dir")
        rows, skipped = rows_from_evidence_dir(args.evidence_dir, rails=rails, mif_ref=args.mif_ref)
    capacity = {float(k): float(v) for k, v in (p.split("=") for p in args.capacity.split(",") if "=" in p)}
    try:
        result = fit_mif_linear(rows, same_rw=args.same_rw, capacity_mbs=capacity)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if skipped:
        result["warnings"].append(f"skipped (missing BW / rails / MIF level): {skipped}")
    if args.out:
        args.out.write_text(yaml.safe_dump({"bw_model": "mif-linear", "bw": result["bw"]}, sort_keys=False),
                            encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
