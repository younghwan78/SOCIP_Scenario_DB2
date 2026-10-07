"""SYNTHETIC Exynos2600 clock-residency capture example (CPU cluster · DSU · GPU, 3 PMU passes).

Writes ``examples/measurement-import/clock-residency-e2600/<variant>/`` — perfetto-SQL-export-like CSVs
(wall / running residency per CPU, idle states, DSU and GPU frequency tracks; one ``pass`` column for the
three 15 s PMU passes) and a ``meta.yaml`` showing the ``domain_class`` / ``basis`` / ``group`` source options.
NOT silicon data (provenance.collection_method synthetic_clock_residency).

    python scripts/generate_clock_residency_example.py            # writes the example folders
    uv run python -m scenario_db.meas_import.cli \\
        --meta examples/measurement-import/clock-residency-e2600/cam-rec-r1-uhd30-vdis/meta.yaml \\
        --out db_Exynos2600_SM-S947B/03_evidence --strict
"""
from __future__ import annotations

import csv
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1] / "examples" / "measurement-import" / "clock-residency-e2600"
PASS_NS = 15_000_000_000          # 15 s per PMU pass
CPU_MAP = {"0-2": "MID_LF0", "3-5": "MID_LF1", "6-8": "MID_HF", "9": "BIG"}
CPUS = {"MID_LF0": [0, 1, 2], "MID_LF1": [3, 4, 5], "MID_HF": [6, 7, 8], "BIG": [9]}

# per variant: cluster -> (wall {MHz: share}, running {MHz: share}, running share, clock-gated share)
# pass_shift: (cluster, pass, {MHz: share}) overrides of the running distribution (DVFS drift between passes)
VARIANTS = {
    "cam-rec-r1-uhd30-vdis": {
        "measured_at": "2026-10-07T10:00:00+09:00",
        "cpu": {
            "MID_LF0": ({400: 0.30, 1000: 0.70}, {400: 0.08, 1000: 0.92}, 0.51, 0.22),
            "MID_LF1": ({400: 1.0}, {400: 1.0}, 0.30, 0.32),
            "MID_HF": ({600: 0.95, 1200: 0.05}, {600: 0.85, 1200: 0.15}, 0.11, 0.40),
            "BIG": ({1000: 1.0}, {}, 0.0, 0.45),
        },
        "pass_shift": [("MID_LF0", 3, {400: 0.10, 1000: 0.90})],
        "dsu": ({400: 0.30, 900: 0.70}, {400: 0.15, 900: 0.85}),
        "gpu": ({226: 0.55, 262: 0.25, 356: 0.15, 461: 0.05}, {226: 0.35, 262: 0.30, 356: 0.25, 461: 0.10}, 0.22, 0.38),
    },
    "cam-rec-r1-8k30-psm": {
        "measured_at": "2026-10-07T11:00:00+09:00",
        "cpu": {
            "MID_LF0": ({400: 0.20, 1000: 0.50, 1600: 0.30}, {400: 0.05, 1000: 0.55, 1600: 0.40}, 0.47, 0.24),
            "MID_LF1": ({400: 0.60, 1000: 0.40}, {400: 0.35, 1000: 0.65}, 0.41, 0.27),
            "MID_HF": ({600: 0.70, 1200: 0.30}, {600: 0.55, 1200: 0.45}, 0.25, 0.34),
            "BIG": ({1000: 1.0}, {}, 0.0, 0.45),
        },
        # third pass ran warmer: MID_LF0 spends less time at 1.6 GHz
        "pass_shift": [("MID_LF0", 3, {400: 0.10, 1000: 0.80, 1600: 0.10})],
        "dsu": ({400: 0.15, 900: 0.60, 1500: 0.25}, {400: 0.05, 900: 0.60, 1500: 0.35}),
        "gpu": ({262: 0.35, 356: 0.35, 461: 0.20, 605: 0.10}, {262: 0.20, 356: 0.35, 461: 0.28, 605: 0.17}, 0.34, 0.30),
    },
}


def _rows(levels: dict[int, float], scale: float) -> list[tuple[int, int]]:
    return [(mhz * 1000, round(share * scale)) for mhz, share in sorted(levels.items()) if share > 0]


def write_variant(vid: str, spec: dict) -> Path:
    out = ROOT / vid
    out.mkdir(parents=True, exist_ok=True)
    shifts = {(c, p): lv for c, p, lv in spec["pass_shift"]}
    with (out / "cpu_freq_residency.csv").open("w", newline="") as fw, \
         (out / "cpu_freq_residency_running.csv").open("w", newline="") as fa, \
         (out / "cpu_idle_residency.csv").open("w", newline="") as fi:
        ww, wa, wi = csv.writer(fw, lineterminator="\n"), csv.writer(fa, lineterminator="\n"), csv.writer(fi, lineterminator="\n")
        ww.writerow(["pass", "cpu", "freq_khz", "dur_ns"])
        wa.writerow(["pass", "cpu", "freq_khz", "dur_ns"])
        wi.writerow(["pass", "cpu", "state", "dur_ns"])
        for p in (1, 2, 3):
            for cluster, (wall, running, run_share, cg) in spec["cpu"].items():
                running = shifts.get((cluster, p), running)
                for i, cpu in enumerate(CPUS[cluster]):
                    tweak = 1.0 + 0.02 * (i - 1)            # CPUs of a cluster are not identical
                    run = min(1.0, run_share * tweak)
                    for khz, ns in _rows(wall, PASS_NS):
                        ww.writerow([p, cpu, khz, ns])
                    for khz, ns in _rows(running, PASS_NS * run):
                        wa.writerow([p, cpu, khz, ns])
                    pg = max(0.0, 1.0 - run - cg)
                    for state, share in (("running", run), ("WFI", cg), ("C2", pg)):
                        wi.writerow([p, cpu, state, round(share * PASS_NS)])
    dsu_wall, dsu_run = spec["dsu"]
    gpu_wall, gpu_run, gpu_active, gpu_cg = spec["gpu"]
    with (out / "dsu_gpu_freq_residency.csv").open("w", newline="") as fd:
        w = csv.writer(fd, lineterminator="\n")
        w.writerow(["pass", "domain", "basis", "freq_khz", "dur_ns"])
        for p in (1, 2, 3):
            for domain, wall, run, share in (("DSU", dsu_wall, dsu_run, 0.6), ("GPU", gpu_wall, gpu_run, gpu_active)):
                for khz, ns in _rows(wall, PASS_NS):
                    w.writerow([p, domain, "wall", khz, ns])
                for khz, ns in _rows(run, PASS_NS * share):
                    w.writerow([p, domain, "running", khz, ns])
    with (out / "gpu_idle_residency.csv").open("w", newline="") as fg:
        w = csv.writer(fg, lineterminator="\n")
        w.writerow(["pass", "domain", "state", "dur_ns"])
        for p in (1, 2, 3):
            pg = max(0.0, 1.0 - gpu_active - gpu_cg)
            for state, share in (("busy", gpu_active), ("clock_gated", gpu_cg), ("power_off", pg)):
                w.writerow([p, "GPU", state, round(share * PASS_NS)])
    (out / "meta.yaml").write_text(_meta(vid, spec), encoding="utf-8")
    return out


def _meta(vid: str, spec: dict) -> str:
    cpu_states = {"running": "active", "WFI": "clock_gated", "C2": "power_gated"}
    sources: list[dict] = []
    for p in (1, 2, 3):
        sources.append({"file": "cpu_freq_residency.csv", "kind": "freq_residency", "group": f"pass{p}",
                        "filter": {"pass": f"^{p}$"}, "cpu": {"column": "cpu"}, "freq_column": "freq_khz",
                        "freq_unit": "khz", "value_column": "dur_ns"})
    for p in (1, 2, 3):
        sources.append({"file": "cpu_freq_residency_running.csv", "kind": "freq_residency", "basis": "active",
                        "group": f"pass{p}", "filter": {"pass": f"^{p}$"}, "cpu": {"column": "cpu"},
                        "freq_column": "freq_khz", "freq_unit": "khz", "value_column": "dur_ns"})
    sources.append({"file": "cpu_idle_residency.csv", "kind": "idle_residency", "cpu": {"column": "cpu"},
                    "state_column": "state", "value_column": "dur_ns", "states": cpu_states})
    for domain, cls in (("DSU", "cpu"), ("GPU", "gpu")):
        for basis, label in (("wall", "wall"), ("active", "running")):
            groups = (1, 2, 3) if domain == "GPU" and basis == "wall" else (None,)
            for p in groups:
                src = {"file": "dsu_gpu_freq_residency.csv", "kind": "freq_residency", "domain_class": cls,
                       "filter": {"domain": f"^{domain}$", "basis": f"^{label}$", **({"pass": f"^{p}$"} if p else {})},
                       "cluster": {"column": "domain"}, "freq_column": "freq_khz", "freq_unit": "khz",
                       "value_column": "dur_ns"}
                if basis == "active":
                    src["basis"] = "active"
                if p:
                    src["group"] = f"pass{p}"
                sources.append(src)
    sources.append({"file": "gpu_idle_residency.csv", "kind": "idle_residency", "domain_class": "gpu",
                    "cluster": {"column": "domain"}, "state_column": "state", "value_column": "dur_ns",
                    "states": {"busy": "active", "clock_gated": "clock_gated", "power_off": "power_gated"}})
    meta = {
        "schema_version": "2.2",
        "id": f"meas-synthetic-clock-residency-{vid.removeprefix('cam-rec-')}-e2600-evt1",
        "project_ref": "proj-sm-s947b",
        "scenario_ref": "uc-cam-recording-e2600",
        "variant_ref": vid,
        "measured_at": spec["measured_at"],
        "execution_context": {"silicon_rev": "EVT1", "sw_baseline_ref": "sw-vendor-v1.2.3", "thermal": "room",
                              "ambient_temp_c": 25.0, "power_state": "discharging", "method": "measurement"},
        "provenance": {"device_id": "SYNTHETIC", "collection_method": "synthetic_clock_residency", "sample_count": 3,
                       "duration_per_sample_s": 15.0, "confidence_level": 0.95},
        "aggregation_strategy": "mean_over_capture",
        "pmu": {"format": "table", "cpu_map": CPU_MAP, "table": {"sources": sources}},
    }
    head = ("# SYNTHETIC Exynos2600 clock-residency example (generated by scripts/generate_clock_residency_example.py).\n"
            "# 3 PMU passes x 15 s: wall + running (non-idle) CPU residency per pass (group -> pass divergence),\n"
            "# DSU (domain_class cpu) and GPU (domain_class gpu) frequency tracks, idle states.\n")
    return head + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)


def main() -> int:
    for vid, spec in VARIANTS.items():
        print(write_variant(vid, spec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
