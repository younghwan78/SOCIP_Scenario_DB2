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
LINEAGE_FIELDS = ("power_model", "bw_power_model", "bw_coefficient", "power_params_hash", "clock_basis")

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

    params = getattr(config, "power_params", None)
    bw_model = bw_model_from_config(config)
    described = bw_model.describe() if bw_model is not None else {}
    return {
        "power_model": getattr(config, "power_model", None) or "v1-vfps",
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
    a = {**_LEGACY, **(old or {})}
    b = {**_LEGACY, **(new or {})}
    return [
        {"field": field, "old": a.get(field), "new": b.get(field)}
        for field in LINEAGE_FIELDS
        if a.get(field) != b.get(field)
    ]
