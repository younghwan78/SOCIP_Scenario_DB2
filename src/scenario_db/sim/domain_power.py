"""Power of non-CPU clock domains (GPU, NPU, …) from their measured frequency residency.

Coefficients live with the IP (IP catalog ``capabilities.power_model``), like the per-IP simulation
parameters:

- ``dynamic_coeff_uw_per_mhz_v2`` (or the driver's ``profiler_dynamic_coeff``, same profiler convention
  as the CPU energy model): dynamic mW at 100 % busy = coeff * MHz * V^2 / 1000
- ``vf_table`` [{mhz, mv}] (``vf_table_sample`` when only an assumed table exists — results are flagged)
- ``leakage`` / ``leakage_sample``: {mw_at_ref, ref_mv, exponent} -> static = mw_at_ref * (V/ref)^exp

Estimate (per frame-independent average power):

    dynamic = active_ratio * sum_f r_running(f) * P_dyn(f)      (running residency; else wall residency)
    static  = (1 - power_gated_ratio) * sum_f r_wall(f) * P_leak(V(f))
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# measured rails of a domain class (calibration join), by rail name
RAIL_HINTS = {"gpu": r"G3D|GPU", "npu": r"NPU"}


@dataclass(frozen=True)
class DomainPowerModel:
    name: str
    ip_ref: str
    coeff_uw_per_mhz_v2: float
    vf: tuple[tuple[float, float], ...]          # (MHz, mV) ascending
    leak_mw_at_ref: float = 0.0
    leak_ref_mv: float = 750.0
    leak_exponent: float = 2.0
    sample: bool = False                         # V-f / leakage are assumed values
    coeff_source: str = "dynamic_coeff_uw_per_mhz_v2"

    def mv(self, mhz: float) -> float:
        for f, v in self.vf:
            if f >= mhz - 1e-9:
                return v
        return self.vf[-1][1]

    def dyn_mw(self, mhz: float) -> float:
        v = self.mv(mhz) / 1000.0
        return self.coeff_uw_per_mhz_v2 * mhz * v * v / 1000.0

    def leak_mw(self, mhz: float) -> float:
        if self.leak_mw_at_ref <= 0:
            return 0.0
        return self.leak_mw_at_ref * (self.mv(mhz) / self.leak_ref_mv) ** self.leak_exponent

    @classmethod
    def from_ip(cls, name: str, ip_ref: str, capabilities: dict[str, Any] | None) -> DomainPowerModel | None:
        pm = (capabilities or {}).get("power_model") or {}
        coeff_source = "dynamic_coeff_uw_per_mhz_v2" if "dynamic_coeff_uw_per_mhz_v2" in pm else "profiler_dynamic_coeff"
        coeff = pm.get(coeff_source)
        table, sample = pm.get("vf_table"), False
        if not table:
            table, sample = pm.get("vf_table_sample"), True
        if not isinstance(coeff, (int, float)) or coeff <= 0 or not table:
            return None
        vf = tuple(sorted((float(r["mhz"]), float(r["mv"])) for r in table if r.get("mhz") and r.get("mv")))
        if not vf:
            return None
        leak = pm.get("leakage") or pm.get("leakage_sample") or {}
        sample = sample or (not pm.get("leakage") and bool(pm.get("leakage_sample")))
        return cls(name=name, ip_ref=ip_ref, coeff_uw_per_mhz_v2=float(coeff), vf=vf,
                   leak_mw_at_ref=float(leak.get("mw_at_ref") or 0.0), leak_ref_mv=float(leak.get("ref_mv") or 750.0),
                   leak_exponent=float(leak.get("exponent") or 2.0), sample=sample, coeff_source=coeff_source)

    def estimate(self, wall: list[dict[str, float]] | None, active: list[dict[str, float]] | None,
                 active_ratio: float | None, power_gated_ratio: float | None) -> dict[str, Any]:
        notes: list[str] = []
        run = active or wall or []
        if not active:
            notes.append("running 분포 없음 — 전체 분포로 dynamic 근사")
        busy = active_ratio
        if busy is None:
            busy = 1.0
            notes.append("동작 비율 없음 — 100% 동작 가정 (상한)")
        dyn = busy * sum(b["ratio"] * self.dyn_mw(b["mhz"]) for b in run)
        on = 1.0 - (power_gated_ratio or 0.0)
        static = on * sum(b["ratio"] * self.leak_mw(b["mhz"]) for b in (wall or run))
        if self.sample:
            notes.append("V-f 표·leakage가 SAMPLE 값 (ECT/ASV 미확보)")
        if self.coeff_source == "profiler_dynamic_coeff":
            notes.append("driver profiler 계수 사용 — 단위·scale을 실측 rail로 확인 필요")
        return {"dynamic_mw": round(dyn, 2), "static_mw": round(static, 2), "total_mw": round(dyn + static, 2),
                "ip_ref": self.ip_ref, "sample": self.sample, "coeff_source": self.coeff_source, "notes": notes,
                "at_fmax_mw": round(self.dyn_mw(self.vf[-1][0]), 1)}


def models_from_ip_catalog(ip_rows: Any, soc_ref: str | None, labels: dict[str, str]) -> dict[str, DomainPowerModel]:
    """Domain name -> model for IP rows compatible with ``soc_ref``; ``labels``: domain class label -> class."""
    out: dict[str, DomainPowerModel] = {}
    for row in ip_rows:
        get = row.get if isinstance(row, dict) else (lambda k, r=row: getattr(r, k, None))
        socs = get("compatible_soc") or []
        if soc_ref and socs and soc_ref not in socs:
            continue
        rid = str(get("id") or "")
        family = rid.removeprefix("ip-").split("-", 1)[0].upper()
        if family not in labels:
            continue
        model = DomainPowerModel.from_ip(family, rid, get("capabilities"))
        if model is not None:
            out[family] = model
    return out


def measured_rail_mw(vdd_power: dict[str, Any] | None, domain_class: str) -> tuple[float | None, list[str]]:
    """Sum of measured rails of a domain class (by rail name hint)."""
    hint = RAIL_HINTS.get(domain_class)
    if not hint or not isinstance(vdd_power, dict):
        return None, []
    rails = [(name, r) for name, r in vdd_power.items() if re.search(hint, name, re.I) and isinstance(r, dict)]
    vals = [float(r["power_mw"]) for _, r in rails if isinstance(r.get("power_mw"), (int, float))]
    return (round(sum(vals), 2) if vals else None), [n for n, _ in rails]
