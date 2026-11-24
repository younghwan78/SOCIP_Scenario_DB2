"""Wake residency ``wake-residency-v1`` (R-4 / M-5): what screen-off audio power is made of.

Screen-off playback power is set less by throughput than by who wakes how often. From the wake sources of the
active subsystems (``report.subsystems[*].wake``, mcps-v1) and the coefficients of the run config
(``config.residency``, from the project ``sim.config_profile`` ``run_config.residency``):

* W = sum of wake rates [1/s]; ``P_cpu_wake = W x e_wake_mj`` (entry / exit only: SW runtime stays the CPU model's);
* each source k keeps DRAM out of self-refresh for its burst plus the exit / entry time,
  ``p_k = min(1, rate_k x (burst_k + t_exit) / 1000)`` with burst = ``period_burst_ms`` (period IRQ, event) or
  ``mb / refill_mb_s`` (refill); independent sources overlap, so ``r_MIF = 1 - prod(1 - p_k)``;
  the screen on (``design_conditions.screen_on``) keeps MIF active: ``r_MIF = 1``;
* ``P_MIF_state = r_MIF x mif_active_mw + (1 - r_MIF) x mif_self_refresh_mw``.

Owners: ABOX units are the subsystem's (mcps-v1), SW runtime the CPU model's, traffic-proportional BW power the BW
model's; this adds only the wake entry / exit and the MIF state power. Without coefficients nothing is added
(``status: no_coefficients``, the wake rates are still reported); without a wake source there is no residency.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from scenario_db.models.common import BaseScenarioModel

MODEL_ID = "wake-residency-v1"


class ResidencyParams(BaseScenarioModel):
    """Wake / MIF state coefficients (project assumption or calibrated)."""

    e_wake_mj: float = Field(ge=0, allow_inf_nan=False)             # AP entry + exit energy per wake
    t_exit_ms: float = Field(ge=0, allow_inf_nan=False)             # DRAM self-refresh exit + entry per burst
    period_burst_ms: float = Field(ge=0, allow_inf_nan=False)       # AP busy per period IRQ / event wake
    refill_mb_s: float = Field(gt=0, allow_inf_nan=False)           # DRAM read rate of an offload refill
    mif_active_mw: float = Field(ge=0, allow_inf_nan=False)         # MIF active (not self-refresh) state power
    mif_self_refresh_mw: float = Field(ge=0, allow_inf_nan=False)
    value_source: str = "assumed"
    basis: str | None = None


def evaluate_residency(subsystems: dict[str, dict[str, Any]], params: ResidencyParams | None,
                       screen_on: Any) -> dict[str, Any] | None:
    """``report.residency``, or None when no subsystem declares an active wake source."""
    sources = [{"node": node, **src} for node, sub in sorted((subsystems or {}).items())
               for src in (sub.get("wake") or {}).get("sources") or []]
    if not sources:
        return None
    wakeups = sum(float(s["per_s"]) for s in sources)
    out: dict[str, Any] = {"model": MODEL_ID, "wakeups_per_s": round(wakeups, 4), "sources": sources,
                           "screen_on": bool(screen_on)}
    if params is None:
        out["status"] = "no_coefficients"
        out["note"] = "config.residency 계수 없음: wake 횟수만 보고하고 전력은 더하지 않음"
        return out
    keep_on = 1.0
    for s in sources:
        burst = (float(s.get("mb") or 0.0) / params.refill_mb_s * 1000.0 if s["kind"] == "refill"
                 else params.period_burst_ms)
        p = min(1.0, float(s["per_s"]) * (burst + params.t_exit_ms) / 1000.0)
        s["burst_ms"] = round(burst, 4)
        s["active_ratio"] = round(p, 6)
        keep_on *= 1.0 - p
    ratio = 1.0 if screen_on else 1.0 - keep_on
    cpu_wake = wakeups * params.e_wake_mj
    mif = ratio * params.mif_active_mw + (1.0 - ratio) * params.mif_self_refresh_mw
    out.update(status="ok", mif_active_ratio=round(ratio, 6), cpu_wake_mw=round(cpu_wake, 3),
               mif_state_mw=round(mif, 3), mw=round(cpu_wake + mif, 3), value_source=params.value_source,
               mif_active_mw=params.mif_active_mw, mif_self_refresh_mw=params.mif_self_refresh_mw,
               basis=params.basis or ("wake-residency-v1: P = W x E_wake + r_MIF x P_active + (1 - r_MIF) x "
                                      "P_self_refresh; independent sources: r = 1 - prod(1 - p_k)"))
    return out
