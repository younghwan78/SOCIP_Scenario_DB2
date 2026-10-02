"""Spec-fail reasons in reviewer language (R3): what failed, by how much, and what change would fix it.

Inputs are the strings produced by ``sim.timing_budget._verdict`` / ``arch_exploration`` and the
already-grouped clock lines of ``arch_report.compact_reasons``. Unknown strings pass through.
"""

from __future__ import annotations

import re
from typing import Any

_SW = re.compile(r"^(?P<stage>.+?): SW (?P<sw>[\d.]+) ms leaves no HW budget$")
_RT = re.compile(r"^RT HW (?P<hw>[\d.]+) ms > (?P<pct>\d+)% budget (?P<budget>[\d.]+) ms$")
_IV = re.compile(r"^(?P<which>preview|video) interval (?P<got>[\d.]+) ms != (?P<target>[\d.]+) ms$")
_CLK_GROUP = re.compile(r"^(?P<nodes>[\w, ]+): 필요 clock (?P<req>[\d.]+) MHz > DVFS max (?P<max>[\d.]+) MHz$")
_IP_MAX = re.compile(r"^(?P<node>\w+): required_clock (?P<req>[\d.]+)MHz exceeds ip max_clock (?P<max>[\d.]+)MHz$")
_SET_LOW = re.compile(r"^(?P<node>\w+): set_clock (?P<set>[\d.]+)MHz < required_clock (?P<req>[\d.]+)MHz$")


def explain(reason: str, period_ms: float | None = None) -> dict[str, str]:
    """{code, text, action, raw} for one reason string."""
    m = _SW.match(reason)
    if m:
        sw = float(m["sw"])
        stage = m["stage"].strip()
        if period_ms:
            need = sw - period_ms
            return {"code": "sw_budget", "raw": reason,
                    "text": f"{stage} SW {sw:.1f} ms ≥ frame 주기 {period_ms:.2f} ms → HW 처리 시간이 남지 않음",
                    "action": (f"SW {need:.1f} ms 이상 단축, 또는 {max(2, int(sw // period_ms) + 1)}-frame batch / SW 병렬화"
                               if need >= 0 else "SW 단축 또는 batch / 병렬화")}
        return {"code": "sw_budget", "raw": reason, "text": f"{stage} SW {sw:.1f} ms가 frame 예산을 모두 사용",
                "action": "SW 단축 또는 batch / 병렬화"}
    m = _RT.match(reason)
    if m:
        hw, budget = float(m["hw"]), float(m["budget"])
        return {"code": "rt_budget", "raw": reason,
                "text": f"RT HW {hw:.2f} ms > {m['pct']}% 예산 {budget:.2f} ms ({100 - int(m['pct'])}% SW margin rule)",
                "action": f"RT 경로 {hw - budget:.2f} ms 단축 — RT clock ×{hw / budget:.2f} 이상 또는 처리량(ppc) 증가"}
    m = _IV.match(reason)
    if m:
        got, target = float(m["got"]), float(m["target"])
        return {"code": "interval", "raw": reason,
                "text": f"{m['which']} 출력 간격 {got:.2f} ms (목표 {target:.2f} ms, {1000 / got:.1f} fps 달성)",
                "action": "위 stage 예산 초과가 원인 — 해당 원인 해소 시 함께 해결"}
    m = _CLK_GROUP.match(reason)
    if m:
        req, mx = float(m["req"]), float(m["max"])
        return {"code": "ip_clock", "raw": reason,
                "text": f"{m['nodes']}: 필요 clock {req:.0f} MHz > DVFS 최고 {mx:.0f} MHz (×{req / mx:.2f})",
                "action": f"처리량 ×{req / mx:.2f} 필요 — ppc 증가, 상위 DVFS level 추가, 또는 처리 해상도/fps 축소"}
    m = _IP_MAX.match(reason)
    if m:
        req, mx = float(m["req"]), float(m["max"])
        return {"code": "ip_clock", "raw": reason,
                "text": f"{m['node']}: 필요 clock {req:.0f} MHz > IP 최대 {mx:.0f} MHz",
                "action": f"IP 처리량 ×{req / mx:.2f} 필요 (ppc · instance 수)"}
    m = _SET_LOW.match(reason)
    if m:
        return {"code": "ip_clock", "raw": reason,
                "text": f"{m['node']}: 지정 DVFS level clock {float(m['set']):.0f} MHz < 필요 {float(m['req']):.0f} MHz",
                "action": "override level 상향"}
    if reason == "recommended case failed re-simulation verification":
        return {"code": "verify", "raw": reason, "text": "추천 조합이 재시뮬레이션 검증에서 불일치",
                "action": "조합 탐색 결과 수동 검토 (analytic ↔ timeline 차이)"}
    if reason == "clock above the 25% rule is not allowed":
        return {"code": "constraint", "raw": reason, "text": "25% rule을 넘는 clock 상향이 제약으로 금지됨",
                "action": "constraint 완화(clock 상향 허용) 또는 처리량 증가"}
    if reason == "timing fail":
        return {"code": "other", "raw": reason, "text": "timing 판정 실패 (세부 사유 미기록)", "action": "Timing Budget 화면에서 확인"}
    if reason.startswith("IP core power 미모델"):
        return {"code": "model", "raw": reason, "text": "일부 IP의 power 계수 없음 (unit_power=0) — power 비교 불가",
                "action": "IP catalog에 power 계수 입력"}
    if reason == "no eligible combination":
        return {"code": "no_case", "raw": reason, "text": "제약을 만족하는 조합 없음",
                "action": "constraint 완화 또는 HW/SW 변경"}
    return {"code": "other", "raw": reason, "text": reason, "action": "—"}


def explain_all(reasons: list[str], fps: float | None) -> list[dict[str, str]]:
    """Explain each reason; preview and video interval lines become one."""
    period = 1000.0 / fps if fps else None
    out: list[dict[str, str]] = []
    intervals: list[re.Match[str]] = []
    off_target = False
    for r in reasons:
        if r == "preview/video interval off target":
            off_target = True  # summary line of the per-stream interval reasons
            continue
        m = _IV.match(r)
        if m:
            intervals.append(m)
            continue
        out.append(explain(r, period))
    if intervals:
        which = "·".join(m["which"] for m in intervals)
        got = max(float(m["got"]) for m in intervals)
        target = float(intervals[0]["target"])
        out.append({"code": "interval", "raw": "; ".join(m.string for m in intervals),
                    "text": f"{which} 출력 간격 {got:.2f} ms (목표 {target:.2f} ms, {1000 / got:.1f} fps 달성)",
                    "action": "위 stage 예산 초과가 원인 — 해당 원인 해소 시 함께 해결"})
    elif off_target:
        out.append({"code": "interval", "raw": "preview/video interval off target",
                    "text": "preview/video 출력 간격이 목표 period를 벗어남", "action": "위 stage 예산 초과가 원인 — 해당 원인 해소 시 함께 해결"})
    return out


def first_text(reasons: list[str], fps: float | None) -> str:
    ex = explain_all(reasons, fps)
    return ex[0]["text"] if ex else "원인 미기록"


def summarize(ex: list[dict[str, Any]]) -> str:
    return " · ".join(e["text"] for e in ex)


# ---------------------------------------------------------------- R3+: what to focus on, what to do
_PRIORITY = ("sw_budget", "rt_budget", "ip_clock", "constraint", "no_case", "verify", "model", "interval", "other")
_X = re.compile(r"×([\d.]+)")
_NODES = re.compile(r"^([\w, ]+):")

CAUSE_LABEL = {
    "sw_budget": "SW 시간 병목 — NRT/Post SW가 frame 주기를 다 씀",
    "rt_budget": "RT 경로 HW 시간 초과",
    "ip_clock": "IP 처리량 병목 — 필요 clock > DVFS 최고",
    "interval": "출력 간격 미달 (결과 지표)",
    "constraint": "탐색 제약으로 해 없음",
    "no_case": "만족 조합 없음",
    "verify": "추천 조합 검증 불일치",
    "model": "power 모델 계수 누락",
    "other": "기타",
}


def _ratio(e: dict[str, str]) -> float | None:
    m = _X.search(e.get("text", ""))
    return float(m.group(1)) if m else None


def diagnose(explained: list[dict[str, str]], fps: float | None) -> dict[str, Any]:
    """Primary cause of a spec fail, how severe it is, what to review first and ranked optimisations.

    ``explained`` = ``explain_all`` output (frozen in the report snapshot, so old reports work too).
    """
    if not explained:
        return {"code": "other", "label": CAUSE_LABEL["other"], "severity": "—", "focus": "원인 미기록 — Timing Budget 화면에서 확인",
                "actions": [], "ratio": None, "nodes": []}
    ranked = sorted(explained, key=lambda e: _PRIORITY.index(e.get("code", "other")) if e.get("code") in _PRIORITY else 99)
    p = ranked[0]
    code = p.get("code", "other")
    clocks = [e for e in explained if e.get("code") == "ip_clock"]
    worst_clock = max((r for r in (_ratio(e) for e in clocks) if r), default=None)
    nodes = sorted({n.strip() for e in clocks for n in ((_NODES.match(e["text"]) or [None, ""])[1] or "").split(",") if n.strip()})
    period = 1000.0 / fps if fps else None
    high_fps = bool(fps and fps >= 100)
    actions: list[str] = []
    if code == "sw_budget":
        m = re.search(r"SW ([\d.]+) ms", p["text"])
        sw = float(m.group(1)) if m else None
        frames = int(sw // period) + 1 if sw and period else None
        sev = f"SW {sw:.1f} ms = 주기 {period:.2f} ms의 {sw / period:.1f}배" if sw and period else "SW > 주기"
        focus = ("NRT 경로 SW(RTA·EIS 등 runtime + latency)가 한 frame 주기 안에 끝나는 구조인지 — "
                 + ("고속 recording은 1 frame = 1 period 가정 밖이므로 batch 처리 설계가 먼저" if high_fps else "SW 순차 실행 구간과 latency 비중"))
        actions = [f"{frames}-frame batch (NRT를 {frames} frame 단위로 묶어 처리) 또는 SW pipeline 병렬화" if frames else "SW batch / 병렬화",
                   "SW 병목 task(EIS·RTA)의 HW offload 또는 처리 축소 (예: 고속 모드에서 RTA 간헐 실행)",
                   "CPU what-if로 병목 task를 상위 cluster에 고정했을 때 runtime 단축량 확인"]
        if worst_clock:
            actions.append(f"SW 해소 후에도 IP 처리량 ×{worst_clock:.2f} 부족 — 아래 IP 처리량 조치 병행")
    elif code == "rt_budget":
        r = _ratio(p) or None
        sev = p["text"]
        focus = "RT(OTF) 경로는 sensor readout에 동기 — RT IP clock·ppc와 sensor 출력 크기(binning/crop)"
        actions = ["RT IP clock 상향 또는 ppc 증가", "sensor binning / bayer crop(bcrop)으로 RT 처리 화소 축소", "SW margin rule 재확인 (Timing Budget에서 margin 조정)"]
        if r:
            sev = f"RT HW 예산 대비 ×{r:.2f}"
    elif code == "ip_clock":
        x = worst_clock or 1.0
        sev = f"처리량 ×{x:.2f} 부족" + (" (근소)" if x < 1.05 else " (중간)" if x < 1.3 else " (구조적)")
        focus = (f"{', '.join(nodes[:6])}{' 외' if len(nodes) > 6 else ''}: 처리 화소/s(해상도 × fps) 대비 ppc × DVFS 최고 clock")
        if x < 1.05:
            actions = ["근소 초과 — 처리 화소 수 % 단위 축소로 해소: EIS margin 축소 · bcrop · pyramid L0 skip (Power option)",
                       "DVFS 최고 level clock 소폭 상향 (OD level) 가능 여부 확인", "h-blank / sensor valid time 가정 재확인 (필요 clock 과대 여부)"]
        elif x < 1.3:
            actions = [f"처리량 ×{x:.2f}: 상위 DVFS level 추가 또는 ppc 증가 검토", "bcrop · EIS margin 축소로 처리 화소 축소", "동일 domain IP의 level 공유 영향 확인 (domain 분리 검토)"]
        else:
            actions = [f"구조적 부족 ×{x:.2f}: IP instance 병렬화 / ppc 상향 (차기 IP spec)", "처리 해상도 또는 fps 축소 (예: 고속 모드 전용 저해상도 경로)",
                       "spec 요구 자체 재확인 (해당 scenario가 KPI 대상인지)"]
    else:
        sev = p["text"]
        focus = p.get("action") or "—"
        actions = [p["action"]] if p.get("action") and p["action"] != "—" else []
    return {"code": code, "label": CAUSE_LABEL.get(code, code), "severity": sev, "focus": focus, "actions": actions,
            "ratio": worst_clock, "nodes": nodes}
