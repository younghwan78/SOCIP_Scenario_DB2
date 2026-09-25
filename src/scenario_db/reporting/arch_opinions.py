"""Category review opinions for the architecture report.

Rows are grouped the way recording scenarios are reviewed:
30 fps (resolution x EIS x codec), 60 fps (resolution), high-speed (>= 100 fps)
and heavy modes (pro / portrait / dual / triple). Every sentence is derived
from the frozen snapshot numbers; nothing here is a measured result.
"""

from __future__ import annotations

import re
import statistics
from typing import Any

CATEGORIES = [
    ("fps30", "30 fps recording", "해상도(FHD · UHD · 8K) × EIS on/off × HEVC/APV"),
    ("fps60", "60 fps recording", "FHD · UHD"),
    ("highspeed", "고속 recording", "FHD120 · FHD240 · UHD120 (그 이상 포함)"),
    ("heavy", "Heavy scenario", "Pro · Portrait · Dual/PIP/RCV · Triple — 기존 과제 heavy 분류"),
    ("other", "기타", "위 분류에 속하지 않는 variant"),
]
_RES_RE = re.compile(r"(?:^|-)(fhd|uhd|qhd|8k|4k|hd)(?=\d|-|$)", re.I)
_HEAVY_ID = re.compile(r"(?:^|-)(pro|portrait|pip|rcv|rdual|rtriple|dual|triple)(?:-|$)", re.I)


def classify(variant_id: str, scenario_id: str, fps: float | None, eis_on: bool | None, dc: dict[str, Any] | None,
             severity: str | None = None) -> dict[str, Any]:
    """Category + axes of one variant. dc = resolved design_conditions (may be empty)."""
    dc = dc or {}
    res = str(dc.get("resolution") or "").upper()
    if not res:
        m = _RES_RE.search(variant_id)
        res = m.group(1).upper() if m else "해상도 미정"
    codec = "APV" if "apv" in scenario_id.lower() or "apv" in str(dc.get("codec_mfc") or "").lower() else "HEVC"
    mode = str(dc.get("camera_mode") or "")
    heavy_kind = None
    hm = _HEAVY_ID.search(variant_id)
    if dc.get("portrait") in (1, True, "1") or (hm and hm.group(1).lower() == "portrait"):
        heavy_kind = "Portrait"
    elif mode.startswith("dual") or (hm and hm.group(1).lower() in ("pip", "rcv", "rdual", "dual")):
        heavy_kind = "Dual"
    elif mode == "triple" or (hm and hm.group(1).lower() in ("rtriple", "triple")):
        heavy_kind = "Triple"
    elif hm and hm.group(1).lower() == "pro":
        heavy_kind = "Pro"
    f = float(fps or dc.get("fps") or 0)
    if f >= 100:
        cat = "highspeed"
    elif heavy_kind:
        cat = "heavy"
    elif 55 <= f <= 65:
        cat = "fps60"
    elif 0 < f <= 31:
        cat = "fps30"
    else:
        cat = "other"
    return {"category": cat, "resolution": res, "codec": codec, "eis": bool(eis_on), "heavy_kind": heavy_kind,
            "fps": f, "severity": severity}


def _share(p: dict[str, Any]) -> dict[str, float]:
    t = p.get("total_mw") or 0.0
    if not t:
        return {}
    bw = (p.get("bw_ip_mw", p.get("bw_mw")) or 0.0) + (p.get("bw_cpu_mw") or 0.0)
    return {"CPU": 100 * (p.get("cpu_mw") or 0.0) / t, "IP core": 100 * (p.get("hw_mw") or 0.0) / t, "BW": 100 * bw / t}


def _pair_delta(rows: list[dict[str, Any]], axis: str, a: Any, b: Any, keys: tuple[str, ...]) -> list[tuple[str, float, float]]:
    """(label, mean ΔmW, mean Δ%) for rows that differ only in `axis` (b - a)."""
    groups: dict[tuple, dict[Any, list[float]]] = {}
    for r in rows:
        t = r["power"].get("total_mw")
        if t is None:
            continue
        k = tuple(r["cls"][x] for x in keys)
        groups.setdefault(k, {}).setdefault(r["cls"][axis], []).append(t)
    out = []
    for k, by in groups.items():
        if a in by and b in by:
            va, vb = statistics.mean(by[a]), statistics.mean(by[b])
            label = " ".join(("EIS on" if x else "EIS off") if isinstance(x, bool) else str(x) for x in k)
            out.append((label, vb - va, 100 * (vb - va) / va if va else 0.0))
    return out


_RES_ORDER = ["HD", "FHD", "QHD", "UHD", "4K", "8K"]


def _res_matrix(rows: list[dict[str, Any]]) -> list[tuple[str, list[tuple[str, list[float]]]]]:
    """Resolution -> [(EIS off/on [+ codec], totals)] in resolution order."""
    m: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        t = r["power"].get("total_mw")
        if t is None:
            continue
        c = r["cls"]
        key = ("EIS on" if c["eis"] else "EIS off") + (" · APV" if c["codec"] == "APV" else "")
        m.setdefault(c["resolution"], {}).setdefault(key, []).append(t)
    order = sorted(m, key=lambda k: _RES_ORDER.index(k) if k in _RES_ORDER else 99)
    return [(res, sorted(m[res].items())) for res in order]


def _f(v: float | None, d: int = 0) -> str:
    return "—" if v is None else f"{v:,.{d}f}"


def build_opinions(rows: list[dict[str, Any]], domains: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One block per non-empty category: stats + ordered opinion sentences."""
    out = []
    for cat, title, scope in CATEGORIES:
        rs = [r for r in rows if r["cls"]["category"] == cat]
        if not rs:
            continue
        ok = [r for r in rs if r["spec_ok"]]
        tot = [r["power"]["total_mw"] for r in ok if r["power"].get("total_mw") is not None]
        bws = [r["bw_mbs"] for r in ok if r.get("bw_mbs") is not None]
        shares = [s for s in (_share(r["power"]) for r in ok) if s]
        avg_share = {k: statistics.mean(s[k] for s in shares) for k in ("CPU", "IP core", "BW")} if shares else {}
        ops: list[str] = []
        ops.append(f"{len(rs)}개 variant 중 spec 만족 {len(ok)}개" + (f", 미달 {len(rs) - len(ok)}개" if len(ok) < len(rs) else "") + ".")
        if tot:
            ops.append(f"등록 예측 Total {_f(min(tot))}–{_f(max(tot))} mW (중앙 {_f(statistics.median(tot))} mW), BW {_f(min(bws))}–{_f(max(bws))} MB/s." if bws
                       else f"등록 예측 Total {_f(min(tot))}–{_f(max(tot))} mW.")
        if avg_share:
            top = max(avg_share, key=lambda k: avg_share[k])
            hint = {"BW": "compression 확대와 MIF/DRAM 경로 절감이 가장 큰 lever", "CPU": "SW task(EIS·RTA 등) 최적화 또는 CPU 배치가 우선",
                    "IP core": "IP clock·DVFS level(전압) 조정이 우선"}[top]
            ops.append(f"평균 구성 CPU {avg_share['CPU']:.0f}% · IP core {avg_share['IP core']:.0f}% · BW {avg_share['BW']:.0f}% → {top} 비중이 가장 커서 {hint}.")
        if cat in ("fps30", "fps60"):
            for res, cells in _res_matrix(ok):
                ops.append(f"{res}: " + " / ".join(f"{k} {_f(statistics.mean(v))} mW (n={len(v)})" for k, v in cells) + ".")
        if cat == "fps30":
            eis = _pair_delta(ok, "eis", False, True, ("resolution", "codec"))
            if eis:
                ops.append("EIS on 영향 (같은 해상도·codec 평균): " + ", ".join(f"{k} {d:+.0f} mW ({p:+.1f}%)" for k, d, p in eis)
                           + " — EIS SW와 GDC 경로 추가분.")
            else:
                ops.append("EIS on/off 쌍이 같은 해상도·codec에 없어 EIS 영향은 비교 불가.")
            apv = _pair_delta(ok, "codec", "HEVC", "APV", ("resolution", "eis"))
            if apv:
                ops.append("APV vs HEVC (같은 해상도·EIS): " + ", ".join(f"{k} {d:+.0f} mW ({p:+.1f}%)" for k, d, p in apv) + ".")
            elif any(r["cls"]["codec"] == "APV" for r in rs):
                ops.append("APV variant가 run에 있으나 같은 조건의 HEVC 쌍이 없어 codec 영향은 비교 불가.")
            else:
                ops.append("이 run에는 APV variant가 없음 — APV 비교는 APV scenario를 포함한 run으로 재생성 필요.")
        if cat == "fps60":
            pairs = _pair_delta([r for r in ok], "resolution", "FHD", "UHD", ("eis", "codec"))
            if pairs:
                ops.append("UHD60 vs FHD60: " + ", ".join(f"{k or '동일 조건'} {d:+.0f} mW ({p:+.1f}%)" for k, d, p in pairs) + ".")
        if cat == "highspeed":
            ops.append("120 fps 이상 NRT batch 처리는 모델 밖 — 결과는 1 frame = 1 period 가정의 보수적 추정.")
            ops.append(f"period {1000 / max(r['cls']['fps'] for r in rs):.2f}–{1000 / min(r['cls']['fps'] for r in rs):.2f} ms 안에 NRT SW(runtime + latency)가 들어가야 함 — SW 병렬화·frame batch 없이는 HW 예산이 남지 않음.")
        if cat == "heavy":
            kinds: dict[str, list[str]] = {}
            for r in rs:
                kinds.setdefault(r["cls"]["heavy_kind"] or "?", []).append(r["variant_id"].replace("cam-rec-", ""))
            ops.append("구성: " + "; ".join(f"{k} {len(v)} ({', '.join(v[:4])}{'…' if len(v) > 4 else ''})" for k, v in kinds.items()) + ".")
            sev: dict[str, int] = {}
            for r in rs:
                sev[str(r["cls"].get("severity") or "미정")] = sev.get(str(r["cls"].get("severity") or "미정"), 0) + 1
            ops.append("기존 과제 부하 등급: " + ", ".join(f"{k} {v}" for k, v in sorted(sev.items())) + ".")
            if "Dual" in kinds or "Triple" in kinds:
                ops.append("Dual/Triple은 물리 IP 공유를 보수적으로 가정한 contention 모델 — 실제 ISP chain 수와 RT 스케줄 확인 전까지 참고치.")
            if "Portrait" in kinds:
                ops.append("Portrait의 depth/segmentation 가속기 전력은 catalog 계수가 없으면 합계에서 빠짐 — 과소 추정 가능.")
        fails = [r for r in rs if not r["spec_ok"]]
        if fails:
            by_reason: dict[str, list[str]] = {}
            for r in fails:
                by_reason.setdefault(r["reasons"][0] if r["reasons"] else "원인 미기록", []).append(r["variant_id"].replace("cam-rec-", ""))
            ops.append("미달 원인: " + "; ".join(f"{k} — {', '.join(v[:5])}{f' 외 {len(v) - 5}' if len(v) > 5 else ''}" for k, v in by_reason.items()) + ".")
        # tightest SW margin and DVFS headroom among spec-OK variants
        margins = [r for r in ok if r.get("sw_margin_pct") is not None]
        if margins:
            w = min(margins, key=lambda r: r["sw_margin_pct"])
            ops.append(f"SW timing margin 최소 {w['sw_margin_pct']:.1f}% ({w['variant_id'].replace('cam-rec-', '')}, {str(w.get('sw_stage') or '').upper()}"
                       + (f", 병목 {w['sw_bottleneck']}" if w.get("sw_bottleneck") else "") + ")"
                       + (" → SW 증가 여유 부족, 차기 SW 성장 시 clock 상향 필요." if w["sw_margin_pct"] < 10 else "."))
        ids = {r["variant_id"] for r in ok}
        dom = [d for d in domains if d["variant_id"] in ids and d.get("headroom_pct") is not None]
        if dom:
            d = min(dom, key=lambda x: x["headroom_pct"])
            ops.append(f"DVFS headroom 최소: {d['domain']} L{d['level']} {_f(d['speed_mhz'])} MHz, 필요 {_f(d['required_mhz'])} MHz (+{d['headroom_pct']:.0f}%, driver {d.get('driver') or '-'}).")
        out.append({"category": cat, "title": title, "scope": scope, "variants": [r["variant_id"] for r in rs],
                    "spec_ok": len(ok), "count": len(rs), "power_range_mw": [min(tot), max(tot)] if tot else None,
                    "share_pct": {k: round(v, 1) for k, v in avg_share.items()}, "opinions": ops})
    return out
