"""Resolve and stamp SoC-scoped ``power_model_params`` for a simulation run.

Params are opt-in: a run only uses them when ``SimulationRunConfig.power_params_ref``
names a document. The API layer resolves the reference against the database
into ``SimulationRunConfig.power_params`` (so the request hash covers the
actual coefficients); the pure engine only ever sees the resolved object.
"""
from __future__ import annotations

from typing import Any

from scenario_db.models.capability.power_model import PowerModelParams


def effective_power_params(config: Any) -> PowerModelParams | None:
    """Resolved params of a run config; a ref without resolved params is an error."""
    params = getattr(config, "power_params", None)
    if params is None and getattr(config, "power_params_ref", None):
        raise ValueError(
            f"power_params_ref '{config.power_params_ref}' was not resolved to parameters; "
            "resolve it through the simulation service or pass power_params inline"
        )
    return params


def power_params_lineage(params: PowerModelParams | None) -> dict[str, Any] | None:
    """What evidence records under ``power_breakdown.model`` for reproducibility."""
    if params is None:
        return None
    return {
        "params_ref": params.params_ref,
        "params_hash": params.params_hash(),
        "calibration_evidence": list(params.calibration.source_evidence),
    }


def power_params_from_row(row: Any) -> PowerModelParams:
    return PowerModelParams.model_validate(
        {
            "id": row.id,
            "schema_version": row.schema_version,
            "kind": "power_model_params",
            "soc_ref": row.soc_ref,
            "version": row.version,
            "status": row.status,
            "description": row.description,
            "notes": row.notes,
            **dict(row.params or {}),
        }
    )
