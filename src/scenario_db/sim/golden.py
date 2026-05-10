from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from scenario_db.db.repositories.scenario_graph import load_canonical_graph
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.models import DVFSTable, SimRunResult, SimulationRunConfig
from scenario_db.sim.runner import run_simulation


def load_golden_cases(path: Path) -> dict[str, dict[str, Any]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cases = raw.get("cases") if isinstance(raw, dict) else None
    if not isinstance(cases, dict):
        raise ValueError(f"Golden case file must contain a 'cases' mapping: {path}")
    return {str(key): value for key, value in cases.items() if isinstance(value, dict)}


def run_golden_case(db: Session, case: dict[str, Any]) -> tuple[SimRunResult, list[dict[str, Any]]]:
    graph = load_canonical_graph(db, str(case["scenario_id"]), str(case["variant_id"]))
    config = SimulationRunConfig.model_validate(case.get("config") or {})
    dvfs_tables = {
        str(key): DVFSTable.model_validate(value)
        for key, value in (case.get("dvfs_tables") or {}).items()
        if isinstance(value, dict)
    }
    result = run_simulation(build_simulation_inputs(graph, config), dvfs_tables=dvfs_tables)
    return result, compare_golden_result(result, case.get("expected") or {})


def compare_golden_result(result: SimRunResult, expected: dict[str, Any]) -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []
    for metric, spec in (expected.get("metrics") or {}).items():
        _compare_value(diffs, f"metrics.{metric}", getattr(result, str(metric), None), spec)

    for node_id, node_expected in (expected.get("resolved") or {}).items():
        actual_node = result.resolved.get(str(node_id))
        if actual_node is None:
            diffs.append({"field": f"resolved.{node_id}", "reason": "missing node"})
            continue
        for field, spec in node_expected.items():
            _compare_value(diffs, f"resolved.{node_id}.{field}", getattr(actual_node, str(field), None), spec)

    expected_warnings = expected.get("warnings")
    if isinstance(expected_warnings, list) and [str(item) for item in expected_warnings] != result.warnings:
        diffs.append(
            {
                "field": "warnings",
                "expected": [str(item) for item in expected_warnings],
                "actual": list(result.warnings),
                "reason": "warning list changed",
            }
        )
    return diffs


def _compare_value(diffs: list[dict[str, Any]], field: str, actual: Any, spec: Any) -> None:
    if not isinstance(spec, dict):
        spec = {"value": spec}
    expected = spec.get("value")
    if actual is None:
        diffs.append({"field": field, "expected": expected, "actual": actual, "reason": "missing value"})
        return
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        abs_tol = float(spec.get("abs_tol") or 0.0)
        rel_tol = float(spec.get("rel_tol") or 0.0)
        tolerance = max(abs_tol, abs(float(expected)) * rel_tol)
        if abs(float(actual) - float(expected)) > tolerance:
            diffs.append(
                {
                    "field": field,
                    "expected": expected,
                    "actual": actual,
                    "tolerance": tolerance,
                    "reason": "outside tolerance",
                }
            )
        return
    if actual != expected:
        diffs.append({"field": field, "expected": expected, "actual": actual, "reason": "value changed"})

