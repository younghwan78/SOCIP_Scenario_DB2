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

from scenario_db.reporting.reason_text import diagnose, explain_all, first_text

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
    recording = "camera-recording" in scenario_id.lower() or variant_id.startswith("cam-rec-")
    codec = str(dc.get("codec_mfc") or ("APV" if "apv" in scenario_id.lower() else "HEVC" if recording else "미정")).upper()
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
    if not recording:
        cat = "other"
    elif f >= 100:
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
    bw = p.get("bw_mw")
    if bw is None:
        bw = (p.get("bw_ip_mw") or 0.0) + (p.get("bw_cpu_mw") or 0.0)
    return {"CPU": 100 * (p.get("cpu_mw") or 0.0) / t, "IP core": 100 * (p.get("hw_mw") or 0.0) / t, "BW": 100 * bw / t}


def _pair_delta(rows: list[dict[str, Any]], axis: str, a: Any, b: Any, keys: tuple[str, ...]) -> list[tuple[str, float, float]]:
    """Grouped mean differences, not a controlled estimate of the axis's effect."""
    groups: dict[tuple, dict[Any, list[float]]] = {}
    for r in rows:
        t = r["power"].get("total_mw")
        if t is None:
            continue
        k = (r["cls"]["fps"], *(r["cls"][x] for x in keys))
        groups.setdefault(k, {}).setdefault(r["cls"][axis], []).append(t)
    out = []
    for k, by in groups.items():
        if a in by and b in by:
            va, vb = statistics.mean(by[a]), statistics.mean(by[b])
            label = " ".join(("EIS on" if x else "EIS off") if isinstance(x, bool) else str(x) for x in k[1:]) + f" ({k[0]:g} fps)"
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
        key = ("EIS on" if c["eis"] else "EIS off") + f" · {c['codec']} · {c['fps']:g} fps"
        m.setdefault(c["resolution"], {}).setdefault(key, []).append(t)
    order = sorted(m, key=lambda k: _RES_ORDER.index(k) if k in _RES_ORDER else 99)
    return [(res, sorted(m[res].items())) for res in order]


def _f(v: float | None, d: int = 0) -> str:
    return "—" if v is None else f"{v:,.{d}f}"


def build_opinions(rows: list[dict[str, Any]], domains: list[dict[str, Any]], *, sample_dvfs: bool = False,
                   measured: set[tuple[str, str]] | None = None, options: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """One block per non-empty category: stats + ordered opinion sentences.

    Every sentence carries its evidence basis (R5): 실측 (measurement), 산출 (computed from the
    prediction), 가정 (rests on an assumed input such as SW timing or the CPU model), 입력 (catalog data).
    """
    measured = measured or set()
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
        basis: list[str] = []

        def add(text: str, b: str, ops: list[str] = ops, basis: list[str] = basis) -> None:
            ops.append(text)
            basis.append(b)

        dv = "산출 · DVFS SAMPLE" if sample_dvfs else "산출"
        add(f"{len(rs)}개 variant 중 spec 만족 {len(ok)}개" + (f", 미달 {len(rs) - len(ok)}개" if len(ok) < len(rs) else "") + ".", "산출")
        if tot:
            add(f"예측 Total (등록 또는 추천) {_f(min(tot))}–{_f(max(tot))} mW (중앙 {_f(statistics.median(tot))} mW), BW {_f(min(bws))}–{_f(max(bws))} MB/s." if bws
                       else f"예측 Total (등록 또는 추천) {_f(min(tot))}–{_f(max(tot))} mW.", dv)
        if avg_share:
            top = max(avg_share, key=lambda k: avg_share[k])
            hint = {"BW": "compression 확대와 MIF/DRAM 경로 절감이 가장 큰 lever", "CPU": "SW task(EIS·RTA 등) 최적화 또는 CPU 배치가 우선",
                    "IP core": "IP clock·DVFS level(전압) 조정이 우선"}[top]
            add(f"평균 구성 CPU {avg_share['CPU']:.0f}% · IP core {avg_share['IP core']:.0f}% · BW {avg_share['BW']:.0f}% → {top} 비중이 가장 커서 {hint}.", "가정 · CPU 모델" if top == "CPU" else dv)
        if cat in ("fps30", "fps60"):
            for res, cells in _res_matrix(ok):
                add(f"{res}: " + " / ".join(f"{k} {_f(statistics.mean(v))} mW (n={len(v)})" for k, v in cells) + ".", dv)
        if cat == "fps30":
            eis = _pair_delta(ok, "eis", False, True, ("resolution", "codec"))
            if eis:
                add("EIS on/off 그룹 평균 차이 (같은 fps·해상도·codec): " + ", ".join(f"{k} {d:+.0f} mW ({p:+.1f}%)" for k, d, p in eis)
                           + " — 센서·HDR·선택 clock 등은 통제하지 않았으므로 EIS 단독 영향이 아님.", "산출")
            else:
                add("EIS on/off 쌍이 같은 해상도·codec에 없어 EIS 영향은 비교 불가.", "산출")
            apv = _pair_delta(ok, "codec", "HEVC", "APV", ("resolution", "eis"))
            if apv:
                add("APV vs HEVC 그룹 평균 (같은 fps·해상도·EIS): " + ", ".join(f"{k} {d:+.0f} mW ({p:+.1f}%)" for k, d, p in apv) + " — 기타 조건 미통제, codec 단독 영향이 아님.", "산출")
            elif any(r["cls"]["codec"] == "APV" for r in rs):
                add("APV variant가 run에 있으나 같은 조건의 HEVC 쌍이 없어 codec 영향은 비교 불가.", "산출")
            else:
                add("이 run에는 APV variant가 없음 — APV 비교는 APV scenario를 포함한 run으로 재생성 필요.", "입력")
        if cat == "fps60":
            pairs = _pair_delta([r for r in ok], "resolution", "FHD", "UHD", ("eis", "codec"))
            if pairs:
                add("UHD60 vs FHD60: " + ", ".join(f"{k or '동일 조건'} {d:+.0f} mW ({p:+.1f}%)" for k, d, p in pairs) + ".", dv)
        if cat == "highspeed":
            add("120 fps 이상 NRT batch 처리는 모델 밖 — 결과는 1 frame = 1 period 가정의 보수적 추정.", "가정 · 모델 밖")
            add(f"period {1000 / max(r['cls']['fps'] for r in rs):.2f}–{1000 / min(r['cls']['fps'] for r in rs):.2f} ms 안에 NRT SW(runtime + latency)가 들어가야 함 — SW 병렬화·frame batch 없이는 HW 예산이 남지 않음.", "가정 · SW timing")
        if cat == "heavy":
            kinds: dict[str, list[str]] = {}
            for r in rs:
                kinds.setdefault(r["cls"]["heavy_kind"] or "?", []).append(r["variant_id"].replace("cam-rec-", ""))
            add("구성: " + "; ".join(f"{k} {len(v)} ({', '.join(v[:4])}{'…' if len(v) > 4 else ''})" for k, v in kinds.items()) + ".", "입력")
            sev: dict[str, int] = {}
            for r in rs:
                sev[str(r["cls"].get("severity") or "미정")] = sev.get(str(r["cls"].get("severity") or "미정"), 0) + 1
            add("기존 과제 부하 등급: " + ", ".join(f"{k} {v}" for k, v in sorted(sev.items())) + ".", "입력")
            if "Dual" in kinds or "Triple" in kinds:
                add("Dual/Triple은 물리 IP 공유를 보수적으로 가정한 contention 모델 — 실제 ISP chain 수와 RT 스케줄 확인 전까지 참고치.", "가정 · contention")
            if "Portrait" in kinds:
                add("Portrait의 depth/segmentation 가속기 전력은 catalog 계수가 없으면 합계에서 빠짐 — 과소 추정 가능.", "가정 · catalog")
        fails = [r for r in rs if not r["spec_ok"]]
        if fails:
            by_reason: dict[str, list[str]] = {}
            for r in fails:
                by_reason.setdefault(first_text(r["reasons"], r.get("fps")), []).append(r["variant_id"].replace("cam-rec-", ""))
            add("미달 원인: " + "; ".join(f"{k} — {', '.join(v[:5])}{f' 외 {len(v) - 5}' if len(v) > 5 else ''}" for k, v in by_reason.items()) + ".", "산출")
        # tightest SW margin and DVFS headroom among spec-OK variants
        margins = [r for r in ok if r.get("sw_margin_pct") is not None]
        if margins:
            w = min(margins, key=lambda r: r["sw_margin_pct"])
            add(f"SW timing margin 최소 {w['sw_margin_pct']:.1f}% ({w['variant_id'].replace('cam-rec-', '')}, {str(w.get('sw_stage') or '').upper()}"
                       + (f", 병목 {w['sw_bottleneck']}" if w.get("sw_bottleneck") else "") + ")"
                       + (" → SW 증가 여유 부족, 차기 SW 성장 시 clock 상향 필요." if w["sw_margin_pct"] < 10 else "."), "가정 · SW timing")
        ids = {(r["scenario_id"], r["variant_id"]) for r in ok}
        dom = [d for d in domains if (d.get("scenario_id"), d["variant_id"]) in ids and d.get("headroom_pct") is not None]
        if dom:
            d = min(dom, key=lambda x: x["headroom_pct"])
            add(f"DVFS headroom 최소: {d['domain']} L{d['level']} {_f(d['speed_mhz'])} MHz, 필요 {_f(d['required_mhz'])} MHz (+{d['headroom_pct']:.0f}%, driver {d.get('driver') or '-'}).", dv)
        evidence = _evidence(rs, measured, sample_dvfs, avg_share)
        out.append({"category": cat, "title": title, "scope": scope, "variants": [r["variant_id"] for r in rs],
                    "spec_ok": len(ok), "count": len(rs), "power_range_mw": [min(tot), max(tot)] if tot else None,
                    "share_pct": {k: round(v, 1) for k, v in avg_share.items()}, "opinions": ops, "basis": basis,
                    "evidence": evidence,
                    "sections": _sections(cat, rs, ok, ops, basis, avg_share, dom, options or [], evidence, sample_dvfs)})
    return out


def _evidence(rs: list[dict[str, Any]], measured: set[tuple[str, str]], sample_dvfs: bool, share: dict[str, float]) -> dict[str, Any]:
    """Block-level evidence: how many variants have a real measurement and what data would firm it up."""
    n = sum(1 for r in rs if (r["scenario_id"], r["variant_id"]) in measured)
    needed = []
    if n == 0:
        needed.append("실측 rail power (최소 1개 variant)")
    if sample_dvfs:
        needed.append("사내 DVFS table")
    if share and max(share, key=lambda k: share[k]) == "CPU":
        needed.append("CPU profile (task별 cycle · cluster residency)")
    if any(r["cls"]["category"] == "highspeed" for r in rs):
        needed.append("HFR NRT batch 동작 정의")
    grade = "실측" if n else "산출"
    return {"measured_variants": n, "grade": grade, "needed": needed}


# ---------------------------------------------------------------- 4-part review (현재 검토 · Risk · 감소 방안 · 추가 최적화)
_RISK_HINT = ("미달 원인", "SW timing margin", "모델 밖", "contention", "과소 추정", "DVFS headroom 최소")


def _sections(cat: str, rs: list[dict[str, Any]], ok: list[dict[str, Any]], ops: list[str], basis: list[str],
              share: dict[str, float], dom: list[dict[str, Any]], options: list[dict[str, Any]],
              evidence: dict[str, Any], sample_dvfs: bool) -> dict[str, list[list[str]]]:
    """Regroup the category sentences into review / risk and derive mitigations and further optimisations.

    Each item = [text, basis]. Risk sentences are the existing fail / margin / assumption lines; the
    mitigation and optimisation lines are derived from the same frozen numbers (no new model output).
    """
    review: list[list[str]] = []
    risk: list[list[str]] = []
    for o, b in zip(ops, basis, strict=False):
        is_risk = any(h in o for h in _RISK_HINT) and not ("DVFS headroom 최소" in o and "+" in o and _headroom_ok(o))
        (risk if is_risk or b.startswith("가정 · 모델 밖") else review).append([o, b])
    if sample_dvfs:
        risk.append(["DVFS table이 SAMPLE — 전압·level 기반 power 수치는 상대 비교용.", "입력"])
    mitig: list[list[str]] = []
    fails = [r for r in rs if not r["spec_ok"]]
    if fails:
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in fails:
            d = diagnose(r.get("reasons_explained") or explain_all(r["reasons"], r.get("fps")), r.get("fps"))
            groups.setdefault(d["code"], []).append({**d, "variant": r["variant_id"].replace("cam-rec-", "")})
        for code, ds in groups.items():
            names = ", ".join(x["variant"] for x in ds[:4]) + (f" 외 {len(ds) - 4}" if len(ds) > 4 else "")
            first = ds[0]
            acts = " / ".join(first["actions"][:2]) if first["actions"] else first["focus"]
            mitig.append([f"[{first['label']}] {names}: {acts}.", "산출"])
    margins = [r for r in ok if r.get("sw_margin_pct") is not None and r["sw_margin_pct"] < 10]
    if margins:
        w = min(margins, key=lambda r: r["sw_margin_pct"])
        mitig.append([f"SW margin < 10% {len(margins)}개 (최소 {w['sw_margin_pct']:.1f}% {w['variant_id'].replace('cam-rec-', '')}): "
                      f"병목 {w.get('sw_bottleneck') or 'SW task'}의 runtime·latency 실측 확보 → Timing Budget의 SW 증가 ×1.1–1.2 what-if로 "
                      "필요 clock 상승 폭을 미리 확인하고, CPU what-if로 병목 task의 cluster 고정 효과 확인.", "가정 · SW timing"])
    tight = [d for d in dom if d.get("headroom_pct") is not None and d["headroom_pct"] < 5]
    if tight:
        d = min(tight, key=lambda x: x["headroom_pct"])
        mitig.append([f"DVFS headroom < 5% domain {len({x['domain'] for x in tight})}개 (예: {d['domain']} L{d['level']}, level 결정 IP {d.get('driver') or '-'}): "
                      "결정 IP의 처리 화소 축소(bcrop · EIS margin) 또는 domain 분리 시 한 단계 낮은 level 가능 여부 검토.", "산출"])
    for need in evidence.get("needed") or []:
        mitig.append([f"근거 보강: {need}.", "입력"])
    optim: list[list[str]] = []
    if share:
        top = max(share, key=lambda k: share[k])
        lever = {"BW": "BW 비중이 가장 큼 → 지원 DMA compression 확대(lossy 포함 IQ 평가), MIF/LLC 경로 절감이 1순위 lever",
                 "CPU": "CPU 비중이 가장 큼 → SW task 최적화 · CPU 배치(uclamp/cpuset) what-if가 1순위 lever",
                 "IP core": "IP core 비중이 가장 큼 → IP clock/DVFS level · IP mode(unit power) 조정이 1순위 lever"}[top]
        optim.append([f"구성 CPU {share['CPU']:.0f}% · IP {share['IP core']:.0f}% · BW {share['BW']:.0f}%: {lever}.", "산출"])
    saves = [(r["baseline_total_mw"] - r["power"]["total_mw"]) for r in ok
             if r.get("baseline_total_mw") is not None and r["power"].get("total_mw") is not None]
    if saves:
        comp_n = sum(1 for r in ok if r.get("compression"))
        optim.append([f"추천 조합(compression · DVFS) 적용 시 baseline 대비 평균 −{statistics.mean(saves):,.0f} mW "
                      f"(최대 −{max(saves):,.0f} mW) · compression 사용 {comp_n}/{len(ok)} variant.", "산출"])
    ids = {(r["scenario_id"], r["variant_id"]) for r in rs}
    best = [o for o in options if (o["scenario_id"], o["variant_id"]) in ids and o.get("best")]
    if best:
        best_option = min(best, key=lambda o: o["best"]["delta_mw"])
        avg = statistics.mean(o["best"]["delta_mw"] for o in best)
        optim.append([f"Power option(IQ 평가 대상) {len(best)}개 variant에서 추가 절감 — 평균 {avg:+,.0f} mW, 최대 {best_option['best']['delta_mw']:+,.0f} mW "
                      f"({' + '.join(best_option['best']['labels'])}, {best_option['variant_id'].replace('cam-rec-', '')}).", "산출"])
    if cat == "highspeed":
        optim.append(["고속 모드 전용 처리 경로(저해상도 NRT · RTA 간헐 실행) 정의 후 재탐색.", "가정 · 모델 밖"])
    if not risk:
        risk.append(["식별된 risk 없음 (이 snapshot 기준).", "산출"])
    return {"review": review, "risk": risk, "mitigation": mitig or [["추가 조치 불필요.", "산출"]],
            "optimize": optim or [["추가 최적화 후보 없음.", "산출"]]}


def _headroom_ok(text: str) -> bool:
    m = re.search(r"\(\+(\d+)%", text)
    return bool(m and int(m.group(1)) >= 10)
