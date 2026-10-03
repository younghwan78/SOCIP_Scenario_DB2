"""CPU what-if sweep cost vs task / thread count (no database).

Builds a synthetic per-frame profile on the Exynos2600 example topology with N tasks and T threads
(in-house Exynos2700 recording profile: 21 tasks / 60 threads) and times ``cpu_sweep`` with the API
defaults. ``--dump`` writes the result JSON so an optimisation can be checked for identical output.

    uv run python scripts/bench_cpu_sweep.py --tasks 21 --threads 60
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import yaml

from scenario_db.models.capability.power_model import PowerModelParams
from scenario_db.sim.cpu_power import CpuPowerModel
from scenario_db.sim.cpu_sched import SweepSpec, cpu_sweep
from scenario_db.sim.models import CpuClusterProfile, CpuProfile, CpuTaskProfile

ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY = ROOT / "examples" / "cpu-topology" / "pmp-exynos2600-cpu-example.yaml"


def profile(n_tasks: int, n_threads: int, clusters: list[str]) -> CpuProfile:
    per = [n_threads // n_tasks + (1 if i < n_threads % n_tasks else 0) for i in range(n_tasks)]
    tasks = []
    for i, k in enumerate(per):
        cycles = 0.4e6 + (i * 7919 % 23) * 0.35e6          # 0.4 .. 8 Mcycles per frame, deterministic spread
        home = clusters[i % (len(clusters) - 1)]             # BIG not used by the measured placement
        threads = {f"t{j}": cycles * (k - j) / (k * (k + 1) / 2) for j in range(k)} if k > 1 else None
        tasks.append(CpuTaskProfile(task=f"task_{i:02}", cluster=home, cycles=cycles, stall_cycles=cycles * 0.15,
                                    threads=threads))
    used = {t.cluster for t in tasks}
    return CpuProfile(tasks=tasks, clusters={c: CpuClusterProfile(cycles=sum(t.cycles for t in tasks if t.cluster == c),
                                                                  freq_residency={1200.0: 1.0}) for c in used})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", type=int, default=21)
    ap.add_argument("--threads", type=int, default=60)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--max-cases", type=int, default=3000)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--uclamp", action="store_true", help="also sweep uclamp_max / uclamp_min knobs")
    ap.add_argument("--dump", type=Path, default=None)
    args = ap.parse_args()
    params = PowerModelParams.model_validate(yaml.safe_load(TOPOLOGY.read_text(encoding="utf-8")))
    model = CpuPowerModel.from_params(params)
    prof = profile(args.tasks, args.threads, [c.name for c in model.clusters])
    best = None
    for _ in range(args.repeats):
        t0 = time.perf_counter()
        result = cpu_sweep(prof, target=model, fps=args.fps, spec=SweepSpec(
            max_cases=args.max_cases,
            **({"knobs": ("pin", "upto", "uclamp_max", "uclamp_min"), "uclamp_max_levels": (512, 768),
                "uclamp_min_levels": (256,)} if args.uclamp else {})))
        dt = time.perf_counter() - t0
        best = dt if best is None else min(best, dt)
    r = result["range"]
    print(json.dumps({"tasks": args.tasks, "threads": args.threads, "seconds": round(best, 3), "space": r["space"],
                      "evaluated": r["evaluated"], "method": r["method"], "per_case_ms": round(1000 * best / r["evaluated"], 2),
                      "better": result["better_count"]}))
    if args.dump:
        args.dump.write_text(json.dumps(result, sort_keys=True, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
