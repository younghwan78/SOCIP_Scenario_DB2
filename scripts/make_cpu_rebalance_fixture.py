"""MID rebalance fixtures (SYNTHETIC) for the CPU what-if "MID 재분배" mode: UI mock data and regression.

Same camera UHD30 recording CPU profile (12 camera tasks on the first MID cluster, 2 system tasks on the
second) on two topologies — Exynos2600 example (MID_LF0 / MID_LF1 / MID_HF / BIG) and Exynos2800 example
(MID_HF0 / MID_HF1 / BIG_LF / BIG) — with an assumed DSU vote table, through ``cpu_rebalance``.

    uv run python scripts/make_cpu_rebalance_fixture.py      # -> ui/tests/fixtures/cpu-rebalance-*.json
"""
from __future__ import annotations

import json
from pathlib import Path
import time

import yaml

from scenario_db.models.capability.power_model import PowerModelParams
from scenario_db.sim.cpu_power import CpuPowerModel
from scenario_db.sim.cpu_rebalance import RebalanceSpec, cpu_rebalance
from scenario_db.sim.models import CpuClusterProfile, CpuProfile, CpuTaskProfile

ROOT = Path(__file__).resolve().parents[1]
TOPO = ROOT / "examples" / "cpu-topology"
OUT = ROOT / "ui" / "tests" / "fixtures"
FPS = 30.0
STALL = 0.18
# task, home slot (0 = first MID cluster, 1 = second), Mcycles/frame (IPC-1 ref), thread split, budget ms
TASKS: list[tuple[str, int, float, list[float], float | None]] = [
    ("cam_hal_request", 0, 13.0, [0.5, 0.3, 0.2], 10.0),
    ("cam_hal_result", 0, 7.0, [0.6, 0.4], 8.0),
    ("isp_ctrl", 0, 9.0, [0.7, 0.3], 4.0),
    ("aaa_ae_awb", 0, 11.0, [0.6, 0.4], 8.0),
    ("af_algo", 0, 5.0, [1.0], 6.0),
    ("eis_vdis", 0, 17.0, [0.4, 0.3, 0.2, 0.1], 12.0),
    ("face_det_post", 0, 6.0, [0.6, 0.4], 10.0),
    ("c2_encoder", 0, 8.0, [0.7, 0.3], 8.0),
    ("mfc_enc_drv", 0, 4.0, [1.0], 4.0),
    ("preview_render", 0, 9.0, [0.6, 0.4], 10.0),
    ("recorder_mux", 0, 3.5, [1.0], None),
    ("sensor_ctrl", 0, 2.5, [1.0], 2.0),
    ("surfaceflinger", 1, 8.0, [0.7, 0.3], 8.0),
    ("audio_hal", 1, 3.0, [1.0], None),
]
BUDGETS = {t[0]: t[4] for t in TASKS if t[4] is not None}
# assumed DSU vote (architecture phase): cluster OPP -> DSU min MHz, by core type
VOTE = {"MID_LF": [[1000, 400], [1600, 900], [2000, 1500]], "MID_HF": [[1200, 400], [2000, 900], [2600, 1500]],
        "BIG_LF": [[2000, 900], [3000, 1500]], "BIG": [[2000, 900], [3600, 1500]]}
SOCS = {"e2600": ("pmp-exynos2600-cpu-example.yaml", ("MID_LF0", "MID_LF1")),
        "e2800": ("pmp-exynos2800-cpu-example.yaml", ("MID_HF0", "MID_HF1"))}


def profile(slots: tuple[str, str]) -> CpuProfile:
    tasks = []
    for name, slot, mcyc, split, _ in TASKS:
        cyc = mcyc * 1e6
        threads = {f"{name}.t{i}": cyc * s for i, s in enumerate(split)} if len(split) > 1 else None
        tasks.append(CpuTaskProfile(task=name, cluster=slots[slot], cycles=cyc, stall_cycles=cyc * STALL, threads=threads))
    return CpuProfile(scenario_ref="uc-cam-recording", variant_ref="rear-wide-uhd30-eis-SYNTHETIC", tasks=tasks,
                      clusters={c: CpuClusterProfile(cycles=sum(t.cycles for t in tasks if t.cluster == c)) for c in slots})


def run(key: str) -> dict:
    file, slots = SOCS[key]
    params = PowerModelParams.model_validate(yaml.safe_load((TOPO / file).read_text(encoding="utf-8")))
    model = CpuPowerModel.from_params(params)
    spec = RebalanceSpec(budgets_ms=BUDGETS, dsu_mode="vote", dsu_vote=VOTE)
    t0 = time.perf_counter()
    result = cpu_rebalance(profile(slots), target=model, fps=FPS, spec=spec)
    seconds = round(time.perf_counter() - t0, 2)
    print(key, "computed in", seconds, "s")
    result["_fixture"] = {"synthetic": True, "power_params_ref": params.params_ref,
                          "request": {"fps": FPS, "budgets_ms": BUDGETS, "dsu_mode": "vote", "dsu_vote": VOTE}}
    return result


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for key in SOCS:
        r = run(key)
        path = OUT / f"cpu-rebalance-{key}.json"
        path.write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")
        b = r["best"]
        print(key, path.stat().st_size, r["method"], r["pool"], "| ref", r["reference"]["total_mw"],
              "-> best", b["total_mw"], b["mhz"], "moved", len(b["moved"]))


if __name__ == "__main__":
    main()
