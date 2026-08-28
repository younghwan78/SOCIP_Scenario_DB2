from __future__ import annotations

from typing import Any

from scenario_db.meas_import.meta import MeasurementImportMeta
from scenario_db.meas_import.perfetto_digest import PerfettoDigest
from scenario_db.meas_import.power_csv import PowerDigest
from scenario_db.models.evidence.metrics import (
    MetricObservation,
    load_default_metric_catalog,
)


def build_metric_observations(
    meta: MeasurementImportMeta,
    power: PowerDigest | None,
    perfetto: PerfettoDigest | None,
    *,
    kpi: dict[str, Any],
) -> list[dict]:
    """Merge explicit observations with canonical observations derived by adapters.

    An explicit observation wins for the same metric/scope identity. This lets
    measurement owners override a lossy derived digest without creating
    ambiguous duplicate rows.
    """
    observations = [
        item.model_dump(exclude_none=True) for item in meta.metric_observations
    ]
    identities = {_identity(item) for item in observations}

    catalog = load_default_metric_catalog()
    for metric_id, definition in catalog.metrics.items():
        if not definition.kpi_key or definition.kpi_key not in kpi:
            continue
        observation = _from_kpi(
            metric_id,
            definition.canonical_unit,
            kpi[definition.kpi_key],
        )
        if observation is None:
            continue
        _append_if_new(observations, identities, observation)

    if power is not None:
        for rail, entry in power.vdd_power.items():
            rail_kpi = power.rail_kpi.get(rail)
            power_stats = _stats_from_mapping(rail_kpi or entry, metric="power")
            if power_stats:
                _append_if_new(
                    observations,
                    identities,
                    _stats_observation("power.rail", "rail", rail, "mW", power_stats),
                )

            voltage = _number(entry.get("voltage_v"))
            if voltage is not None:
                _append_if_new(
                    observations,
                    identities,
                    _stats_observation(
                        "power.rail_voltage",
                        "rail",
                        rail,
                        "V",
                        _mean_stats(voltage, power.sample_count),
                    ),
                )

            current = _number(entry.get("current_ma"))
            if current is not None:
                _append_if_new(
                    observations,
                    identities,
                    _stats_observation(
                        "power.rail_current",
                        "rail",
                        rail,
                        "mA",
                        _mean_stats(current, power.sample_count),
                    ),
                )

    if perfetto is not None:
        for task in perfetto.sw_task_timing:
            stats = _task_runtime_stats(task)
            if not stats:
                continue
            task_ref = str(task.get("task") or "").strip()
            if not task_ref:
                continue
            _append_if_new(
                observations,
                identities,
                _stats_observation("sw.runtime", "task", task_ref, "ms", stats),
            )

    return observations


def _from_kpi(metric_id: str, unit: str, value: Any) -> dict | None:
    base = {
        "metric_id": metric_id,
        "scope": {"kind": "scenario", "ref": "self"},
        "unit": unit,
    }
    if isinstance(value, dict):
        stats = _stats_from_mapping(value)
        if stats:
            return {**base, "stats": stats}
        # A dict KPI with no recognizable stat keys must not become
        # {"value": None} — that fails MetricObservation validation with a
        # raw traceback instead of a structured import report.
        return None
    scalar = _number(value)
    if scalar is None:
        return None
    return {**base, "value": scalar}


def _stats_from_mapping(value: Any, *, metric: str | None = None) -> dict[str, float | int]:
    if not isinstance(value, dict):
        return {}
    keys = {
        "mean": (
            ("mean", "mean_mw", "power_mw")
            if metric == "power"
            else ("mean", "mean_ms")
        ),
        "p50": ("p50", "p50_ms"),
        "p95": ("p95", "p95_mw", "p95_ms"),
        "p99": ("p99",),
        "min": ("min",),
        "max": ("max", "max_ms"),
        "std": ("std", "std_mw"),
    }
    out: dict[str, float | int] = {}
    for target, candidates in keys.items():
        for candidate in candidates:
            number = _number(value.get(candidate))
            if number is not None:
                out[target] = number
                break
    n = value.get("n")
    if isinstance(n, int) and not isinstance(n, bool) and n > 0:
        out["n"] = n
    return out


def _task_runtime_stats(task: dict[str, Any]) -> dict[str, float | int]:
    stats = _stats_from_mapping(task)
    if not stats:
        return {}
    samples = task.get("samples")
    if isinstance(samples, int) and not isinstance(samples, bool) and samples > 0:
        stats["n"] = samples
    return stats


def _mean_stats(value: float, sample_count: int) -> dict[str, float | int]:
    stats: dict[str, float | int] = {"mean": value}
    if sample_count > 0:
        stats["n"] = sample_count
    return stats


def _stats_observation(
    metric_id: str,
    scope_kind: str,
    scope_ref: str,
    unit: str,
    stats: dict[str, float | int],
) -> dict:
    return {
        "metric_id": metric_id,
        "scope": {"kind": scope_kind, "ref": scope_ref},
        "unit": unit,
        "stats": stats,
    }


def _append_if_new(
    observations: list[dict],
    identities: set[tuple[str, str, str]],
    observation: dict,
) -> None:
    identity = _identity(observation)
    if identity in identities:
        return
    MetricObservation.model_validate(observation)
    observations.append(observation)
    identities.add(identity)


def _identity(observation: dict) -> tuple[str, str, str]:
    scope = observation["scope"]
    return (
        str(observation["metric_id"]),
        str(scope["kind"]),
        str(scope["ref"]),
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
