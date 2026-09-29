"""Measured tier of the clock ledger, fed from PMU ``metric_observations``.

``meas_import/pmu_digest.py`` stores per-IP clock observations
(``clock.ip`` stats, ``clock.ip_dominant`` value; scope ``ip`` = catalog id).
This module reduces them to one ``MeasuredClock`` per IP so a run can use
``clock_basis="measured"`` and reports can show Meas next to Calc/Cfg.

``clock.ip_residency`` observations (scope ``ip_freq``, ref ``<ip>@<MHz>``)
are attached to the weighted-mean clock, so the resolver can evaluate power
over the levels actually visited instead of snapping the mean to a level.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from scenario_db.sim.clock_models import MeasuredClock, MeasuredClockStat

_STAT_FIELD: dict[str, str] = {"weighted_mean": "mean", "mean": "mean", "max": "max"}


def measured_clocks_from_observations(
    observations: Iterable[dict[str, Any]],
    *,
    stat: MeasuredClockStat = "weighted_mean",
    evidence_ref: str | None = None,
) -> dict[str, MeasuredClock]:
    """{ip catalog id: MeasuredClock} from clock.ip / clock.ip_dominant observations."""
    metric_id = "clock.ip_dominant" if stat == "dominant" else "clock.ip"
    observations = list(observations)
    residency = residency_from_observations(observations)
    out: dict[str, MeasuredClock] = {}
    for item in observations:
        if not isinstance(item, dict) or item.get("metric_id") != metric_id:
            continue
        scope = item.get("scope") or {}
        if scope.get("kind") != "ip" or not scope.get("ref"):
            continue
        if stat == "dominant":
            value = item.get("value")
        else:
            value = (item.get("stats") or {}).get(_STAT_FIELD.get(stat, "mean"))
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            continue
        ref = str(scope["ref"])
        out[ref] = MeasuredClock(
            mhz=float(value),
            stat=stat,
            evidence_ref=evidence_ref,
            source="pmu_digest",
            residency=residency.get(ref) if stat in ("weighted_mean", "mean") else None,
        )
    return out


def residency_from_observations(observations: list[dict[str, Any]]) -> dict[str, dict[float, float]]:
    """{ip ref: {MHz: share}} from ``clock.ip_residency`` observations."""
    out: dict[str, dict[float, float]] = {}
    for item in observations:
        if not isinstance(item, dict) or item.get("metric_id") != "clock.ip_residency":
            continue
        scope = item.get("scope") or {}
        ref, _, freq = str(scope.get("ref") or "").rpartition("@")
        value = item.get("value")
        if scope.get("kind") != "ip_freq" or not ref or isinstance(value, bool):
            continue
        try:
            mhz = float(freq)
        except ValueError:
            continue
        if isinstance(value, (int, float)) and mhz > 0 and value > 0:
            out.setdefault(ref, {})[mhz] = float(value)
    return out
