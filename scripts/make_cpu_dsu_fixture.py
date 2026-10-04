"""DSU vote parity fixture (SYNTHETIC): the UI recomputes DSU power for another vote table from a sweep response;
this writes two sweeps of the same profile on the Exynos2600 example — server rule ``proportional`` and server rule
``vote`` with VOTE — so ``ui/tests`` can check that the client recomputation reproduces the server.

    uv run python scripts/make_cpu_dsu_fixture.py
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from scenario_db.models.capability.power_model import PowerModelParams
from scenario_db.sim.cpu_power import CpuPowerModel
from scenario_db.sim.cpu_sched import SweepSpec, cpu_sweep
from scenario_db.sim.models import CpuClusterProfile, CpuDsuProfile, CpuProfile, CpuTaskProfile

ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY = ROOT / "examples" / "cpu-topology" / "pmp-exynos2600-cpu-example.yaml"
OUT = ROOT / "ui" / "tests" / "fixtures" / "cpu-dsu-sweeps.json"
VOTE = {"MID_LF": [[1000, 400], [1600, 900], [2000, 1500]], "MID_HF": [[1200, 400], [2000, 900], [2600, 1500]],
        "BIG": [[2000, 900], [3600, 1500]]}


def main() -> None:
    model = CpuPowerModel.from_params(PowerModelParams.model_validate(yaml.safe_load(TOPOLOGY.read_text(encoding="utf-8"))))
    tasks = [CpuTaskProfile(task=f"cam{i}", cluster="MID_LF0", cycles=c * 1e6, stall_cycles=c * 1.5e5)
             for i, c in enumerate([17, 13, 11, 9, 7, 5])]
    prof = CpuProfile(tasks=tasks, clusters={"MID_LF0": CpuClusterProfile(cycles=sum(t.cycles for t in tasks))},
                      dsu=CpuDsuProfile(freq_residency={900.0: 0.4, 1500.0: 0.6}))
    out = {"vote_table": VOTE}
    for key, spec in (("proportional", SweepSpec(dsu_mode="proportional", top=12)),
                      ("measured", SweepSpec(dsu_mode="measured", top=12)),
                      ("vote", SweepSpec(dsu_mode="vote", dsu_vote=VOTE, top=12))):
        r = cpu_sweep(prof, target=model, fps=30.0, spec=spec)
        for c in [r["reference"], r["eas_default"], r["measured_placement"], *r["cases"], *r["others"]]:
            c.pop("equivalents", None)
            for cl in c["clusters"].values():
                cl["cpus"] = []
        r["range"]["tasks"] = []
        out[key] = r
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    print(OUT, OUT.stat().st_size, {k: (out[k]["reference"]["total_mw"], out[k]["reference"]["dsu"]["mhz"]) for k in ("proportional", "measured", "vote")})


if __name__ == "__main__":
    main()
