from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from scenario_db.models.evidence.metrics import (
    MetricCatalog,
    MetricDefinition,
    load_default_metric_catalog,
)

_BLOCKING_IDENTITY_FIELDS = ("project_ref", "scenario_ref", "variant_ref")
_BLOCKING_CONTEXT_FIELDS = ("sw_baseline_ref", "thermal", "power_state")
_ADVISORY_CONTEXT_FIELDS = ("silicon_rev", "ambient_temp_c")


def compare_prediction_measurement(
    prediction: dict[str, Any],
    measurement: dict[str, Any],
    *,
    catalog: MetricCatalog | None = None,
) -> dict[str, Any]:
    """Compare normalized prediction/measurement observations without hiding gaps."""
    active_catalog = catalog or load_default_metric_catalog()
    context = compare_evidence_context(prediction, measurement)
    prediction_items = normalize_evidence_observations(prediction, active_catalog)
    measurement_items = normalize_evidence_observations(measurement, active_catalog)

    prediction_by_id = {_identity(item): item for item in prediction_items}
    measurement_by_id = {_identity(item): item for item in measurement_items}
    identities = sorted(set(prediction_by_id) | set(measurement_by_id))

    rows = [
        _comparison_row(
            identity,
            prediction_by_id.get(identity),
            measurement_by_id.get(identity),
            active_catalog,
            context_compatible=context["compatible"],
        )
        for identity in identities
    ]
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row["status"])
        counts[status] = counts.get(status, 0) + 1

    return {
        "prediction_id": prediction.get("id"),
        "measurement_id": measurement.get("id"),
        "context": context,
        "rows": rows,
        "summary": {
            "total": len(rows),
            "status_counts": counts,
            "matched": counts.get("MATCHED", 0),
            "prediction_only": counts.get("PREDICTION_ONLY", 0),
            "measurement_only": counts.get("MEASUREMENT_ONLY", 0),
        },
    }


def compare_evidence_context(
    prediction: dict[str, Any],
    measurement: dict[str, Any],
) -> dict[str, Any]:
    prediction_context = _mapping(prediction.get("execution_context"))
    measurement_context = _mapping(measurement.get("execution_context"))
    rows: list[dict[str, Any]] = []

    for field in _BLOCKING_IDENTITY_FIELDS:
        rows.append(
            _context_row(
                field,
                prediction.get(field),
                measurement.get(field),
                severity="blocking",
            )
        )
    for field in _BLOCKING_CONTEXT_FIELDS:
        rows.append(
            _context_row(
                field,
                prediction_context.get(field),
                measurement_context.get(field),
                severity="blocking",
            )
        )
    for field in _ADVISORY_CONTEXT_FIELDS:
        rows.append(
            _context_row(
                field,
                prediction_context.get(field),
                measurement_context.get(field),
                severity="advisory",
            )
        )

    blockers = [
        row
        for row in rows
        if row["severity"] == "blocking" and row["status"] == "MISMATCH"
    ]
    return {
        "compatible": not blockers,
        "rows": rows,
        "blocking_mismatches": [row["field"] for row in blockers],
    }


def normalize_evidence_observations(
    evidence: dict[str, Any],
    catalog: MetricCatalog | None = None,
) -> list[dict[str, Any]]:
    active_catalog = catalog or load_default_metric_catalog()
    out: list[dict[str, Any]] = []
    identities: set[tuple[str, str, str]] = set()

    for item in evidence.get("metric_observations") or []:
        if isinstance(item, dict) and _valid_raw_observation_shape(item):
            _append_if_new(out, identities, dict(item))

    kpi = _mapping(evidence.get("kpi"))
    for metric_id, definition in active_catalog.metrics.items():
        if definition.kpi_key and definition.kpi_key in kpi:
            _append_if_new(
                out,
                identities,
                _from_legacy_value(
                    metric_id,
                    "scenario",
                    "self",
                    definition.canonical_unit,
                    kpi[definition.kpi_key],
                ),
            )

    for rail, entry in _mapping(evidence.get("vdd_power")).items():
        if not isinstance(entry, dict):
            entry = {"power_mw": entry}
        power = _from_rail_power(entry)
        if power:
            _append_if_new(
                out,
                identities,
                _from_legacy_value("power.rail", "rail", rail, "mW", power),
            )
        for metric_id, key, unit in (
            ("power.rail_voltage", "voltage_v", "V"),
            ("power.rail_current", "current_ma", "mA"),
        ):
            if _number(entry.get(key)) is not None:
                _append_if_new(
                    out,
                    identities,
                    _from_legacy_value(metric_id, "rail", rail, unit, entry[key]),
                )

    for task in evidence.get("sw_task_timing") or []:
        if not isinstance(task, dict) or not task.get("task"):
            continue
        runtime = _timing_stats(task)
        if runtime:
            _append_if_new(
                out,
                identities,
                {
                    "metric_id": "sw.runtime",
                    "scope": {"kind": "task", "ref": str(task["task"])},
                    "unit": "ms",
                    "stats": runtime,
                },
            )

    for item in evidence.get("dma_breakdown") or []:
        if not isinstance(item, dict):
            continue
        direction = str(item.get("direction") or "")
        metric_id = f"bandwidth.{direction}"
        if metric_id not in active_catalog.metrics:
            continue
        value = _number(item.get("bw_mbs"))
        node = str(item.get("node_id") or "")
        port = str(item.get("port") or "")
        if value is None or not node or not port:
            continue
        _append_if_new(
            out,
            identities,
            _from_legacy_value(
                metric_id,
                "dma_port",
                f"{node}:{port}",
                "MB/s",
                value,
            ),
        )

    for item in evidence.get("timing_breakdown") or []:
        if not isinstance(item, dict):
            continue
        value = _number(item.get("hw_time_ms"))
        node = str(item.get("node_id") or "")
        if value is None or not node:
            continue
        _append_if_new(
            out,
            identities,
            _from_legacy_value("latency.stage", "pipeline_stage", node, "ms", value),
        )

    return out


def _comparison_row(
    identity: tuple[str, str, str],
    prediction: dict[str, Any] | None,
    measurement: dict[str, Any] | None,
    catalog: MetricCatalog,
    *,
    context_compatible: bool,
) -> dict[str, Any]:
    metric_id, scope_kind, scope_ref = identity
    definition = catalog.metrics.get(metric_id)
    prediction_value, prediction_stat = _selected_value(prediction, definition)
    measurement_value, measurement_stat = _selected_value(measurement, definition)
    prediction_unit = prediction.get("unit") if prediction else None
    measurement_unit = measurement.get("unit") if measurement else None
    unit = prediction_unit or measurement_unit

    status = "MATCHED"
    if prediction is None:
        status = "MEASUREMENT_ONLY"
    elif measurement is None:
        status = "PREDICTION_ONLY"
    elif prediction_unit != measurement_unit:
        status = "UNIT_MISMATCH"
    elif prediction_value is None or measurement_value is None:
        status = "STATISTIC_MISSING"
    elif not context_compatible:
        status = "CONTEXT_MISMATCH"

    delta: float | None = None
    delta_pct: float | None = None
    if status == "MATCHED":
        delta = round(prediction_value - measurement_value, 6)
        if measurement_value != 0:
            delta_pct = round(delta / measurement_value * 100.0, 3)

    return {
        "metric_id": metric_id,
        "category": definition.category if definition else None,
        "scope_kind": scope_kind,
        "scope_ref": scope_ref,
        "unit": unit,
        "prediction": prediction_value,
        "prediction_statistic": prediction_stat,
        "measurement": measurement_value,
        "measurement_statistic": measurement_stat,
        "measurement_p95": _stat_value(measurement, "p95"),
        "delta": delta,
        "delta_pct": delta_pct,
        "polarity": definition.polarity if definition else "neutral",
        "status": status,
    }


def _selected_value(
    observation: dict[str, Any] | None,
    definition: MetricDefinition | None,
) -> tuple[float | None, str | None]:
    if observation is None:
        return None, None
    value = _number(observation.get("value"))
    if value is not None:
        return value, "value"
    statistic = definition.compare_statistic if definition else "mean"
    if statistic == "value":
        return None, "value"
    return _stat_value(observation, statistic), statistic


def _stat_value(observation: dict[str, Any] | None, statistic: str) -> float | None:
    if not observation:
        return None
    return _number(_mapping(observation.get("stats")).get(statistic))


def _context_row(
    field: str,
    prediction: Any,
    measurement: Any,
    *,
    severity: str,
) -> dict[str, Any]:
    if prediction is None or measurement is None:
        status = "MISSING"
    elif prediction == measurement:
        status = "MATCH"
    else:
        status = "MISMATCH"
    return {
        "field": field,
        "prediction": prediction,
        "measurement": measurement,
        "status": status,
        "severity": severity,
    }


def _from_legacy_value(
    metric_id: str,
    scope_kind: str,
    scope_ref: str,
    unit: str,
    value: Any,
) -> dict[str, Any]:
    base = {
        "metric_id": metric_id,
        "scope": {"kind": scope_kind, "ref": scope_ref},
        "unit": unit,
    }
    if isinstance(value, dict):
        stats = _generic_stats(value)
        if stats:
            return {**base, "stats": stats}
    return {**base, "value": _number(value)}


def _generic_stats(value: dict[str, Any]) -> dict[str, float | int]:
    out: dict[str, float | int] = {}
    for key in ("mean", "p50", "p95", "p99", "min", "max", "std"):
        number = _number(value.get(key))
        if number is not None:
            out[key] = number
    n = value.get("n")
    if isinstance(n, int) and not isinstance(n, bool) and n > 0:
        out["n"] = n
    return out


def _from_rail_power(entry: dict[str, Any]) -> dict[str, Any] | float | None:
    mapping = {
        "mean": _first_number(entry, ("mean_mw", "power_mw", "power", "mean")),
        "p95": _first_number(entry, ("p95_mw", "p95")),
        "std": _first_number(entry, ("std_mw", "std")),
    }
    stats = {key: value for key, value in mapping.items() if value is not None}
    return stats or None


def _timing_stats(task: dict[str, Any]) -> dict[str, float | int]:
    mapping = {
        "mean": task.get("mean_ms"),
        "p50": task.get("p50_ms"),
        "p95": task.get("p95_ms"),
        "max": task.get("max_ms"),
    }
    stats: dict[str, float | int] = {}
    for key, value in mapping.items():
        number = _number(value)
        if number is not None:
            stats[key] = number
    samples = task.get("samples")
    if stats and isinstance(samples, int) and not isinstance(samples, bool) and samples > 0:
        stats["n"] = samples
    return stats


def _append_if_new(
    out: list[dict[str, Any]],
    identities: set[tuple[str, str, str]],
    observation: dict[str, Any],
) -> None:
    identity = _identity(observation)
    if identity in identities:
        return
    out.append(observation)
    identities.add(identity)


def _identity(observation: dict[str, Any]) -> tuple[str, str, str]:
    scope = _mapping(observation.get("scope"))
    return (
        str(observation.get("metric_id") or ""),
        str(scope.get("kind") or ""),
        str(scope.get("ref") or ""),
    )


def _valid_raw_observation_shape(observation: dict[str, Any]) -> bool:
    metric_id, scope_kind, scope_ref = _identity(observation)
    return bool(metric_id and scope_kind and scope_ref and observation.get("unit"))


def _first_number(mapping: dict[str, Any], keys: Iterable[str]) -> float | None:
    for key in keys:
        value = _number(mapping.get(key))
        if value is not None:
            return value
    return None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
