"""Dump DB-free exploration results and compare canonical JSON without tolerances.

Run from the repository root with ``uv run python scripts/check_engine_equivalence.py``.
Timing/profile metadata lives in a subdirectory, outside the result comparison.
"""

from __future__ import annotations

import argparse
import cProfile
import json
from pathlib import Path
import pstats
from statistics import median
from time import perf_counter
from typing import Any

from verify_is_v15_camera import FIXTURE, graph_from_fixture, read

from scenario_db.db.models.capability import IpCatalog
from scenario_db.sim.arch_exploration import ArchExplorationSpec, explore_variant
from scenario_db.sim.models import DVFSTable


# Fixed coverage: all project review-policy Recording KPIs (including APV),
# the remaining IS-v15 Recording KPIs, and two Preview / Capture variants each.
VARIANTS = {
    "uc-cam-recording-e2600": (
        "cam-rec-r1-fhd30-sdr", "cam-rec-r1-fhd60-sdr", "cam-rec-r1-uhd30-sdr",
        "cam-rec-r1-uhd30-vdis", "cam-rec-r1-uhd60-sdr", "cam-rec-r1-8k30-sdr",
        "cam-rec-r1-fhd120", "cam-rec-r1-fhd240", "cam-rec-r1-uhd120",
        "cam-rec-r1-uhd30-portrait", "cam-rec-r1-fhd30-vdis",
        "cam-rec-r1-fhd60-supersteady", "cam-rec-r1-uhd60-supersteady",
    ),
    "uc-cam-recording-apv-e2600": ("cam-rec-apv-uhd60-422-sdr",),
    "uc-cam-preview-e2600": ("cam-prev-r1-30", "cam-prev-r1-60"),
    "uc-cam-capture-e2600": ("cam-cap-r1-sf", "cam-cap-r1-mf"),
}
PROFILE_VARIANT = "cam-rec-r1-uhd30-vdis"
# explore_variant currently has no nondeterministic result fields. Exclude none:
# hashes, manifests, generated case keys and every numeric result are compared.
EXCLUDED_PATHS: frozenset[tuple[str, ...]] = frozenset()


def canonical_json(value: Any, path: tuple[str, ...] = ()) -> str:
    def included(item: Any, current: tuple[str, ...]) -> Any:
        if isinstance(item, dict):
            return {
                key: included(child, (*current, str(key)))
                for key, child in item.items()
                if (*current, str(key)) not in EXCLUDED_PATHS
            }
        if isinstance(item, list):
            return [included(child, (*current, str(i))) for i, child in enumerate(item)]
        return item

    # json uses Python's round-trip float representation; never round/tolerate results.
    return json.dumps(included(value, path), sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def dump(out: Path, runs: int) -> int:
    out.mkdir(parents=True, exist_ok=True)
    metadata = out / "metadata"
    metadata.mkdir(exist_ok=True)
    catalog = {}
    for path in sorted((FIXTURE / "00_hw").glob("ip-*.yaml")):
        doc = read(path)
        catalog[doc["id"]] = IpCatalog(
            id=doc["id"], schema_version=doc["schema_version"], category=doc["category"],
            hierarchy=doc["hierarchy"], capabilities=doc["capabilities"], yaml_sha256="fixture",
        )
    dvfs_doc = read(FIXTURE / "00_hw" / "dvfs-exynos2600-sample-v0.yaml")
    tables = {key: DVFSTable.model_validate(value) for key, value in dvfs_doc["domains"].items()}
    spec = ArchExplorationSpec()
    measurements = {}
    for scenario_id, variants in VARIANTS.items():
        raw = read(FIXTURE / "02_definition" / f"{scenario_id}.yaml")
        for variant_id in variants:
            timings = []
            expected = None
            for _ in range(runs):
                graph = graph_from_fixture(raw, variant_id, catalog)
                started = perf_counter()
                result = explore_variant(graph, spec, dvfs_tables=tables)
                timings.append(perf_counter() - started)
                serialized = canonical_json(result)
                if expected is not None and serialized != expected:
                    raise ValueError(f"{variant_id}: repeated dumps are not deterministic")
                expected = serialized
            assert expected is not None
            (out / f"{variant_id}.json").write_bytes(expected.encode("utf-8"))
            measurements[variant_id] = {
                "scenario_id": scenario_id, "seconds": timings, "median_seconds": median(timings),
            }
            print(f"{variant_id}: median {median(timings):.6f}s ({runs} runs)", flush=True)
            if variant_id == PROFILE_VARIANT:
                graph = graph_from_fixture(raw, variant_id, catalog)
                profiler = cProfile.Profile()
                profiler.runcall(explore_variant, graph, spec, dvfs_tables=tables)
                profiler.dump_stats(str(metadata / f"{variant_id}.prof"))
                stats = pstats.Stats(profiler)
                calls = {
                    name: sum(info[1] for (_, _, func), info in stats.stats.items() if func == name)
                    for name in (
                        "build_simulation_inputs", "selected_sensor_mode", "_base_selected_sensor_mode",
                        "_selected_sensor_row", "_preferred_sensor_mode", "_is_16_9_size", "_size_tuple",
                    )
                }
                measurements[variant_id]["profile_calls"] = calls
                print(f"  profile calls: {json.dumps(calls, sort_keys=True)}", flush=True)
    (metadata / "measurements.json").write_bytes(canonical_json(measurements).encode("utf-8"))
    print(f"Dumped {len(measurements)} variants to {out}")
    return 0


def first_difference(a: Any, b: Any, path: str = "$") -> str | None:
    if type(a) is not type(b):
        return f"{path}: type {type(a).__name__} != {type(b).__name__}"
    if isinstance(a, dict):
        for key in sorted(a.keys() | b.keys()):
            child_path = f"{path}[{json.dumps(key, ensure_ascii=False)}]"
            if key not in a or key not in b:
                return f"{child_path}: missing from {'a' if key not in a else 'b'}"
            difference = first_difference(a[key], b[key], child_path)
            if difference:
                return difference
    elif isinstance(a, list):
        for index, (left, right) in enumerate(zip(a, b)):
            difference = first_difference(left, right, f"{path}[{index}]")
            if difference:
                return difference
        if len(a) != len(b):
            return f"{path}[{min(len(a), len(b))}]: list length {len(a)} != {len(b)}"
    elif json.dumps(a) != json.dumps(b):
        return f"{path}: {str(a)[:160]!r} != {str(b)[:160]!r}"
    return None


def compare(a: Path, b: Path) -> int:
    left = {path.name: path for path in a.glob("*.json")}
    right = {path.name: path for path in b.glob("*.json")}
    if not left or not right:
        print("FAIL: both directories must contain result JSON files")
        return 1
    differences = 0
    for name in sorted(left.keys() | right.keys()):
        if name not in left or name not in right:
            print(f"FAIL {name}: $: missing from {'a' if name not in left else 'b'}")
            differences += 1
            continue
        a_bytes, b_bytes = left[name].read_bytes(), right[name].read_bytes()
        if a_bytes == b_bytes:
            print(f"OK {name}")
            continue
        difference = first_difference(json.loads(a_bytes), json.loads(b_bytes))
        print(f"FAIL {name}: {difference or '$: JSON bytes differ (format or key order)'}")
        differences += 1
    print(f"Compared {len(left.keys() | right.keys())} variants: {differences} differences")
    return int(differences != 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    dump_parser = modes.add_parser("dump", help="dump the fixed fixture cases without a database")
    dump_parser.add_argument("--out", type=Path, required=True)
    dump_parser.add_argument("--runs", type=int, default=3, help="wall-time samples per variant")
    compare_parser = modes.add_parser("compare", help="compare every byte and show first JSON differences")
    compare_parser.add_argument("--a", type=Path, required=True)
    compare_parser.add_argument("--b", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "dump":
        if args.runs < 1:
            parser.error("--runs must be positive")
        return dump(args.out, args.runs)
    return compare(args.a, args.b)


if __name__ == "__main__":
    raise SystemExit(main())
