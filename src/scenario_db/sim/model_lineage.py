"""Which physics produced a number: power model, BW model, coefficients, clock tier.

Two predictions (or a prediction and a measurement) are only comparable at
face value when they came from the same model lineage. A change of
``power_model_params``, BW model or clock basis moves power without any
design change, so comparisons report it instead of attributing the delta to
the scenario.
"""
from __future__ import annotations

from typing import Any

# Fields whose change alone moves predicted power/clock.
LINEAGE_FIELDS = ("power_model", "power_model_version", "bw_power_model", "bw_coefficient", "power_params_hash", "clock_basis")

# Formula version a lineage recorded before ``power_model_version`` existed was made with.
_VERSION_BEFORE_RECORDING = {"v1-vfps": "1.0", "v2-vf": "1.1"}

_LEGACY = {
    "power_model": "v1-vfps",
    "bw_power_model": "builtin",
    "bw_coefficient": 80.0,  # SimulationRunConfig.bw_power_coeff default
    "power_params_ref": None,
    "power_params_hash": None,
    "clock_basis": "calculated",
}


def run_model_lineage(config: Any) -> dict[str, Any]:
    """Lineage of a ``SimulationRunConfig`` (resolved params, before the run)."""
    from scenario_db.sim.bw_power import bw_model_from_config

    from scenario_db.sim.power_model import POWER_MODELS

    params = getattr(config, "power_params", None)
    bw_model = bw_model_from_config(config)
    described = bw_model.describe() if bw_model is not None else {}
    model_id = getattr(config, "power_model", None) or "v1-vfps"
    return {
        "power_model": model_id,
        "power_model_version": POWER_MODELS[model_id].version if model_id in POWER_MODELS else None,
        "bw_power_model": described.get("id", "builtin"),
        "bw_coefficient": described.get("mw_per_gbps", described.get("bw_power_coeff", config.bw_power_coeff)),
        "power_params_ref": params.params_ref if params is not None else None,
        "power_params_hash": params.params_hash() if params is not None else None,
        "clock_basis": getattr(config, "clock_basis", None) or "calculated",
    }


def evidence_model_lineage(evidence: dict[str, Any]) -> dict[str, Any] | None:
    """Lineage recorded in a simulation evidence document (None for measurements)."""
    if evidence.get("kind") not in (None, "evidence.simulation"):
        return None
    model = (evidence.get("power_breakdown") or {}).get("model") or {}
    bw = model.get("bw_model") or {}
    bases: set[str] = set()
    used: set[str] = set()
    measured_refs: set[str] = set()
    for item in evidence.get("dvfs_breakdown") or []:
        ledger = (item or {}).get("clock_ledger") or {}
        if ledger:
            bases.add(str(ledger.get("basis") or "calculated"))
            used.add(str(ledger.get("basis_used") or "calculated"))
            if ledger.get("basis_used") == "measured" and ledger.get("measured_evidence_ref"):
                measured_refs.add(str(ledger["measured_evidence_ref"]))
    return {
        "power_model": model.get("id") or "v1-vfps",
        "power_model_version": model.get("version"),
        "bw_power_model": bw.get("id", "builtin"),
        "bw_coefficient": bw.get("mw_per_gbps", bw.get("bw_power_coeff")),
        "power_params_ref": model.get("params_ref"),
        "power_params_hash": model.get("params_hash"),
        "clock_basis": ",".join(sorted(bases)) if bases else "calculated",
        "clock_basis_used": sorted(used) if used else ["calculated"],
        "measured_clock_evidence": sorted(measured_refs),
    }


def lineage_differences(old: dict[str, Any] | None, new: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Fields that differ; a missing lineage is the legacy default (code constants, calculated clock)."""
    a = _with_version({**_LEGACY, **(old or {})})
    b = _with_version({**_LEGACY, **(new or {})})
    return [
        {"field": field, "old": a.get(field), "new": b.get(field)}
        for field in LINEAGE_FIELDS
        if a.get(field) != b.get(field)
    ]


def _with_version(lineage: dict[str, Any]) -> dict[str, Any]:
    """An unrecorded formula version is the one its power model had before versions were recorded."""
    if lineage.get("power_model_version") is None:
        lineage["power_model_version"] = _VERSION_BEFORE_RECORDING.get(str(lineage.get("power_model")))
    return lineage
