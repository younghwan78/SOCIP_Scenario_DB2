"""Spec-fail reasons in reviewer language (R3): what failed, by how much, and what change would fix it.

Inputs are the strings produced by ``sim.timing_budget._verdict`` / ``arch_exploration`` and the
already-grouped clock lines of ``arch_report.compact_reasons``. Unknown strings pass through.
"""

from __future__ import annotations

import re
from typing import Any

_SW = re.compile(r"^(?P<stage>.+?): SW (?P<sw>[\d.]+) ms leaves no HW budget$")
_RT = re.compile(r"^RT HW (?P<hw>[\d.]+) ms > 75% budget (?P<budget>[\d.]+) ms$")
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
                "text": f"RT HW {hw:.2f} ms > 75% 예산 {budget:.2f} ms (25% SW margin rule)",
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
