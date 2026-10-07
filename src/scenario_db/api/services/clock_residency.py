"""Clock-domain residency view (CPU cluster · DSU · GPU) for the calibration page and the report.

Reads ``metric_observations`` written by ``meas_import/clock_residency.py`` (and the legacy
``cpu_breakdown[].freq_residency`` of perfetto imports) and turns them into per-domain
distributions plus rule-based reading notes, so the UI and the report say the same thing.
"""
from __future__ import annotations

from typing import Any, Iterable

from scenario_db.meas_import.clock_residency import DOMAIN_CLASSES, PASS_JSD_METRIC, PASS_JSD_WARN

RULES_VERSION = 1
HIGH_OPP_FRACTION = 0.8      # "high OPP" = frequency >= 80 % of the domain's max OPP
HIGH_OPP_WARN = 0.30         # time share at high OPP worth flagging
GAP_NOTE = 0.10              # |active mean - wall mean| / wall mean worth explaining
BURST_ACTIVE = 0.20          # low running share ...
BURST_FREQ = 0.70            # ... at a high mean clock = short bursts at high frequency
DSU_NAMES = ("dsu",)
IDLE_DOMAIN = 0.005          # running share below which a domain counts as idle


def _value(item: dict[str, Any]) -> float | None:
    v = item.get("value")
    if v is None:
        v = (item.get("stats") or {}).get("mean")
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _collect(observations: Iterable[Any]) -> tuple[dict[tuple[str, str, str], dict[float, float]],
                                                     dict[tuple[str, str], dict[str, float]], dict[tuple[str, str], float]]:
    freq: dict[tuple[str, str, str], dict[float, float]] = {}
    ratios: dict[tuple[str, str], dict[str, float]] = {}
    jsd: dict[tuple[str, str], float] = {}
    by_metric: dict[str, tuple[str, str, str]] = {}
    for dc in DOMAIN_CLASSES.values():
        by_metric[dc.residency_metric] = (dc.name, "wall", dc.freq_scope)
        by_metric[dc.active_metric] = (dc.name, "active", dc.freq_scope)
        for state in ("active", "clock_gated", "power_gated"):
            by_metric[dc.ratio_metric(state)] = (dc.name, f"ratio:{state}", dc.domain_scope)
    for item in observations:
        if not isinstance(item, dict):
            continue
        metric = str(item.get("metric_id") or "")
        scope = item.get("scope") or {}
        kind, ref, value = scope.get("kind"), str(scope.get("ref") or ""), _value(item)
        if value is None or not ref:
            continue
        if metric == PASS_JSD_METRIC:
            cls, _, domain = ref.partition("/")
            if cls in DOMAIN_CLASSES and domain:
                jsd[(cls, domain)] = value
            continue
        hit = by_metric.get(metric)
        if hit is None or kind != hit[2]:
            continue
        cls, what, _ = hit
        if what.startswith("ratio:"):
            ratios.setdefault((cls, ref), {})[what[len("ratio:"):]] = value
            continue
        domain, _, mhz_text = ref.rpartition("@")
        try:
            mhz = float(mhz_text)
        except ValueError:
            continue
        if domain and mhz > 0 and value > 0:
            freq.setdefault((cls, what, domain), {})[mhz] = value
    return freq, ratios, jsd


def _stats(levels: dict[float, float], fmax: float | None) -> dict[str, Any]:
    total = sum(levels.values())
    bins = [{"mhz": f, "ratio": round(v / total, 6)} for f, v in sorted(levels.items())]
    mean = sum(b["mhz"] * b["ratio"] for b in bins)
    acc, p50 = 0.0, bins[-1]["mhz"]
    for b in bins:
        acc += b["ratio"]
        if acc >= 0.5:
            p50 = b["mhz"]
            break
    # high-OPP share only against a known max OPP (the observed max says nothing about headroom)
    high = (round(sum(b["ratio"] for b in bins if b["mhz"] >= HIGH_OPP_FRACTION * fmax - 1e-9), 4) if fmax else None)
    dominant = max(bins, key=lambda b: (b["ratio"], b["mhz"]))
    return {"bins": bins, "mean_mhz": round(mean, 1), "p50_mhz": p50, "max_mhz": bins[-1]["mhz"],
            "min_mhz": bins[0]["mhz"], "dominant_mhz": dominant["mhz"], "dominant_share": dominant["ratio"],
            "high_share": high}


def _mhz(v: float) -> str:
    return f"{v / 1000:.2f} GHz" if v >= 1000 else f"{v:.0f} MHz"


def _notes(d: dict[str, Any]) -> list[dict[str, str]]:
    notes: list[dict[str, str]] = []
    wall, active, fmax = d["wall"], d["active"], d["opp_max_mhz"]
    if d["active_ratio"] is not None and d["active_ratio"] < IDLE_DOMAIN:
        return [{"level": "info", "code": "idle_domain",
                 "text": "측정 중 거의 동작하지 않았습니다 (clock gating · power gating). 분포는 idle 중 governor 값입니다."}]
    if d["pass_jsd"] is not None and d["pass_jsd"] > PASS_JSD_WARN:
        notes.append({"level": "warn", "code": "pass_divergence",
                      "text": f"측정 pass 사이 clock 분포가 다릅니다 (JSD {d['pass_jsd']:.3f} > {PASS_JSD_WARN}). "
                              "측정 중 온도·부하가 변했을 수 있어 capture 품질을 확인하세요."})
    base = active or wall
    if base and fmax and base["high_share"] is not None and base["high_share"] >= HIGH_OPP_WARN:
        notes.append({"level": "warn", "code": "high_opp",
                      "text": f"{'running 시간' if active else '전체 시간'}의 {base['high_share'] * 100:.0f}%를 "
                              f"고 OPP(≥{HIGH_OPP_FRACTION * 100:.0f}% fmax, ≥{_mhz(HIGH_OPP_FRACTION * fmax)})에서 보냅니다. "
                              "부하가 몰렸거나 boost가 걸린 상태 — CPU what-if에서 분산을 검토하세요."
                              if d["domain_class"] == "cpu" and not d["is_dsu"] else
                              f"{'running 시간' if active else '전체 시간'}의 {base['high_share'] * 100:.0f}%를 "
                              f"고 OPP(≥{_mhz(HIGH_OPP_FRACTION * fmax)})에서 보냅니다."})
    ar = d["active_ratio"]
    if ar is not None and ar < BURST_ACTIVE and base and fmax and base["mean_mhz"] >= BURST_FREQ * fmax:
        notes.append({"level": "warn", "code": "burst",
                      "text": f"동작 비율은 {ar * 100:.0f}%인데 평균 clock이 fmax의 {base['mean_mhz'] / fmax * 100:.0f}%입니다. "
                              "짧은 burst를 높은 clock으로 처리(race-to-idle) — governor rate limit·uclamp_max를 검토하세요."})
    if wall and active:
        gap = (active["mean_mhz"] - wall["mean_mhz"]) / wall["mean_mhz"] if wall["mean_mhz"] else 0.0
        if abs(gap) >= GAP_NOTE:
            notes.append({"level": "info", "code": "idle_gap",
                          "text": f"running 평균 {_mhz(active['mean_mhz'])} vs 전체 평균 {_mhz(wall['mean_mhz'])}: "
                                  f"idle 동안 clock이 {'낮게' if gap > 0 else '높게'} 머뭅니다."
                                  + (" dynamic power는 running 분포로 계산합니다." if d["domain_class"] == "cpu" else "")})
    return notes


def clock_residency_view(observations: Iterable[Any] | None, cpu_breakdown: Iterable[Any] | None = None, *,
                         opp_max: dict[str, float] | None = None) -> dict[str, Any] | None:
    """Per-domain residency + notes, or None when the evidence has no clock residency.

    ``opp_max``: domain name -> max OPP MHz (topology); without it the highest observed frequency is used.
    """
    freq, ratios, jsd = _collect(list(observations or []))
    sources = {key: "observation" for key in freq}
    for entry in cpu_breakdown or []:
        if not isinstance(entry, dict) or not entry.get("cluster"):
            continue
        key = ("cpu", "wall", str(entry["cluster"]))
        if key in freq:
            continue
        bins = {float(b["freq_mhz"]): float(b["ratio"]) for b in entry.get("freq_residency") or []
                if isinstance(b, dict) and b.get("freq_mhz") and b.get("ratio")}
        if bins:
            freq[key] = bins
            sources[key] = "perfetto"
    if not freq:
        return None
    domains: list[dict[str, Any]] = []
    for cls, domain in sorted({(c, d) for c, _, d in freq}, key=lambda k: (list(DOMAIN_CLASSES).index(k[0]),
                                                                            k[1].lower() in DSU_NAMES, k[1])):
        fmax = (opp_max or {}).get(domain)
        wall, active = freq.get((cls, "wall", domain)), freq.get((cls, "active", domain))
        r = ratios.get((cls, domain), {})
        is_dsu = cls == "cpu" and domain.lower() in DSU_NAMES
        d: dict[str, Any] = {
            "domain_class": cls, "class_label": "DSU" if is_dsu else DOMAIN_CLASSES[cls].label, "domain": domain,
            "is_dsu": is_dsu, "opp_max_mhz": fmax,
            "wall": _stats(wall, fmax) if wall else None, "active": _stats(active, fmax) if active else None,
            "active_ratio": r.get("active"), "clock_gated_ratio": r.get("clock_gated"), "power_gated_ratio": r.get("power_gated"),
            "pass_jsd": jsd.get((cls, domain)),
            "source": sources.get((cls, "wall", domain)) or sources.get((cls, "active", domain)),
        }
        if d["active_ratio"] is None and (d["clock_gated_ratio"] is not None or d["power_gated_ratio"] is not None):
            d["active_ratio"] = round(max(0.0, 1.0 - (d["clock_gated_ratio"] or 0.0) - (d["power_gated_ratio"] or 0.0)), 4)
        d["notes"] = _notes(d)
        domains.append(d)
    return {"rules_version": RULES_VERSION, "domains": domains, "summary": summary(domains),
            "thresholds": {"high_opp_fraction": HIGH_OPP_FRACTION, "high_opp_warn": HIGH_OPP_WARN,
                           "pass_jsd_warn": PASS_JSD_WARN}}


def summary(domains: list[dict[str, Any]]) -> list[str]:
    """Up to one sentence per class (+ warning count) for headers and the report."""
    out: list[str] = []
    cpus = [d for d in domains if d["domain_class"] == "cpu" and not d["is_dsu"]]
    if cpus:
        def busy(d: dict[str, Any]) -> float:
            s = d["active"] or d["wall"]
            return (d["active_ratio"] if d["active_ratio"] is not None else 1.0) * (s["mean_mhz"] if s else 0.0)
        top = max(cpus, key=busy)
        s = top["active"] or top["wall"]
        out.append(f"CPU: 가장 바쁜 cluster {top['domain']} — {'running' if top['active'] else '전체'} 평균 {_mhz(s['mean_mhz'])}"
                   + (f", 동작 {top['active_ratio'] * 100:.0f}%" if top["active_ratio"] is not None else "")
                   + f", 최빈 {_mhz(s['dominant_mhz'])} ({s['dominant_share'] * 100:.0f}%)")
    for d in domains:
        if d["is_dsu"] or d["domain_class"] != "cpu":
            s = d["active"] or d["wall"]
            out.append(f"{d['class_label'] if d['is_dsu'] else d['domain']}: {'running' if d['active'] else '전체'} 평균 {_mhz(s['mean_mhz'])}"
                       + (f", 동작 {d['active_ratio'] * 100:.0f}%" if d["active_ratio"] is not None else "")
                       + (f", 고 OPP {s['high_share'] * 100:.0f}%" if s["high_share"] is not None else ""))
    if cpus and not any(d["active"] for d in cpus):
        out.append("CPU running(idle 제외) 분포 없음 — dynamic power는 전체 시간 분포로 근사 "
                   "(perfetto cpu_active_residency 또는 basis: active source 추가 권장)")
    warns = sum(1 for d in domains for n in d["notes"] if n["level"] == "warn")
    if warns:
        out.append(f"확인 필요 {warns}건 — 아래 domain별 메모 참고")
    return out


def opp_max_from_ip_catalog(ip_rows: Iterable[Any], soc_ref: str | None) -> dict[str, float]:
    """Max frequency of non-CPU clock domains from the IP catalog (``capabilities.dvfs_model|properties.max_freq_khz``).

    Domain name = upper-case IP family (``ip-gpu-s5e9965`` -> ``GPU``); rows not compatible with ``soc_ref`` are skipped.
    """
    out: dict[str, float] = {}
    for row in ip_rows:
        get = row.get if isinstance(row, dict) else (lambda k, r=row: getattr(r, k, None))
        socs = get("compatible_soc") or []
        if soc_ref and socs and soc_ref not in socs:
            continue
        rid = str(get("id") or "")
        family = rid.removeprefix("ip-").split("-", 1)[0].upper()
        caps = get("capabilities") or {}
        khz = next((block.get("max_freq_khz") for block in (caps.get("dvfs_model"), caps.get("properties"))
                    if isinstance(block, dict) and block.get("max_freq_khz")), None)
        if family in {dc.label for dc in DOMAIN_CLASSES.values()} and isinstance(khz, (int, float)) and khz > 0:
            out[family] = float(khz) / 1000.0
    return out


def opp_max_from_params(params_rows: Iterable[Any], domains: set[str]) -> dict[str, float]:
    """Max OPP per CPU cluster / DSU from the power_model_params whose cluster names cover ``domains``.

    Picks the row covering most of the measured CPU domains (newest version on ties); {} when none matches.
    """
    best: tuple[int, int, dict[str, float]] = (0, -1, {})
    for row in params_rows:
        cpu = ((getattr(row, "params", None) or {}).get("cpu") or {}) if not isinstance(row, dict) else (row.get("cpu") or {})
        table: dict[str, float] = {}
        for c in cpu.get("clusters") or []:
            opps = [float(o["mhz"]) for o in c.get("opps") or [] if isinstance(o, dict) and o.get("mhz")]
            if c.get("name") and opps:
                table[str(c["name"])] = max(opps)
        dsu = cpu.get("dsu") or {}
        dsu_opps = [float(o["mhz"]) for o in dsu.get("opps") or [] if isinstance(o, dict) and o.get("mhz")]
        if dsu_opps:
            table[str(dsu.get("name") or "DSU")] = max(dsu_opps)
        hits = len(domains & set(table))
        version = int(getattr(row, "version", 0) or 0)
        if hits and (hits, version) > best[:2]:
            best = (hits, version, table)
    return best[2]
