"""Performance at the spec stage: frame drop on the final outputs, latency → buffer use, SW optimisation requests.

- Frame drop is judged on what the user sees: the preview and video output intervals must hold the target fps.
  For scenarios that hold it, the smallest NRT / Post SW margin says how close they are to a drop.
- Latency has rarely failed a project, but every frame in flight holds its M2M buffers: frames alive × DRAM per frame
  estimates the buffer use (``frame_buffer`` in each row).
- A timing concern becomes an SW optimisation request: per SW task on the critical path, how many scenarios it binds,
  how long it runs and how much it must shrink for a 10 % margin (and under the project's SW growth budget).
"""

from __future__ import annotations

import math
from html import escape
from typing import Any

TARGET_MARGIN_PCT = 10.0   # same as risk_rules.LOW_MARGIN_PCT: below this an SW stage is a timing risk
HIGH_FPS = 120.0           # ≥ this the NRT batch behaviour is not modelled (1 frame = 1 period): a cut there is an upper bound
_TOL = 0.001               # output interval within ±0.1 % of the period = fps held


def _short(v: str) -> str:
    return v.replace("cam-rec-", "")


def _f(v: Any, d: int = 1) -> str:
    return "—" if v is None else f"{float(v):,.{d}f}"


def _out_fps(interval_ms: Any, period: Any) -> tuple[float | None, bool | None]:
    if interval_ms is None or not period:
        return None, None
    iv = float(interval_ms)
    return (round(1000.0 / iv, 2) if iv > 0 else None), abs(iv - float(period)) <= float(period) * _TOL


def output_rows(snap: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for r in snap.get("scenarios") or []:
        iv, p = r.get("intervals") or {}, r.get("period_ms")
        pf, pok = _out_fps(iv.get("preview"), p)
        vf, vok = _out_fps(iv.get("video"), p)
        stages = [s for s in r.get("sw_stages") or [] if s.get("margin_pct") is not None]
        worst = min(stages, key=lambda s: s["margin_pct"], default=None)
        judged = [x for x in (pok, vok) if x is not None]
        # frame drop = an output interval off the target; without intervals (older snapshots) the spec verdict stands
        drop = (not all(judged)) if judged else not r.get("spec_ok")
        out.append({"scenario_id": r["scenario_id"], "variant_id": r["variant_id"], "fps": r.get("fps"),
                    "preview_fps": pf, "preview_ok": pok, "video_fps": vf, "video_ok": vok, "spec_ok": r.get("spec_ok"),
                    "drop": drop,
                    "margin_pct": worst["margin_pct"] if worst else r.get("sw_margin_pct"),
                    "stage": worst["stage"] if worst else r.get("sw_stage"),
                    "bottleneck": worst["bottleneck"] if worst else r.get("sw_bottleneck"),
                    "reasons": [x.get("text") if isinstance(x, dict) else str(x) for x in (r.get("reasons_explained") or r.get("reasons") or [])][:2]})
    # drops first, then other spec misses, then the closest to a drop
    out.sort(key=lambda o: (not o["drop"], bool(o["spec_ok"]), o["margin_pct"] if o["margin_pct"] is not None else 1e9))
    return out


def output_fps_block(snap: dict[str, Any], top: int = 10) -> str:
    rows = output_rows(snap)
    if not rows:
        return ""
    drops = [o for o in rows if o["drop"]]
    other = [o for o in rows if not o["drop"] and not o["spec_ok"]]
    near = [o for o in rows if o["spec_ok"] and o["margin_pct"] is not None and o["margin_pct"] < TARGET_MARGIN_PCT]

    def cell(fps: float | None, ok: bool | None) -> str:
        return "<td class=meta>—</td>" if fps is None else f"<td class='n {'ok' if ok else 'fail'}'>{fps:,.2f}</td>"

    def table(rs: list[dict[str, Any]]) -> str:
        h = ("<table><tr><th>Scenario</th><th>목표 fps</th><th>Preview 출력 fps</th><th>Video 출력 fps</th><th>판정</th>"
             "<th>최소 SW 여유</th><th>병목</th><th>사유</th></tr>")
        for o in rs:
            m = o["margin_pct"]
            mcls = "fail" if m is not None and m < 0 else "warn" if m is not None and m < TARGET_MARGIN_PCT else ""
            h += (f"<tr><td>{escape(_short(o['variant_id']))}</td><td class=n>{_f(o['fps'], 0)}</td>"
                  + cell(o["preview_fps"], o["preview_ok"]) + cell(o["video_fps"], o["video_ok"])
                  + ("<td class=fail>frame drop</td>" if o["drop"] else
                     "<td class=ok>충족</td>" if o["spec_ok"] else "<td class=warn>출력 fps 충족 · 기타 spec 미달</td>")
                  + f"<td class='n {mcls}'>{_f(m, 0) + '%' if m is not None else '—'}"
                  + (f" <span class=meta>{escape(str(o['stage']).upper())}</span>" if o.get("stage") else "") + "</td>"
                  f"<td class=mono>{escape(str(o['bottleneck'] or '—'))}</td>"
                  f"<td class=meta>{escape(' · '.join(o['reasons'])) if not o['spec_ok'] else ''}</td></tr>")
        return h + "</table>"

    h = ("<h3 style='margin:12px 0 4px'>Frame drop — 최종 출력 fps (preview · video)</h3>"
         f"<p class=meta>preview · video 출력 간격이 목표 주기 ±0.1% 안이면 fps 충족. frame drop {len(drops)}"
         + (f" · 출력은 충족하나 다른 spec(전력 · BW 예산 등) 미달 {len(other)}" if other else "")
         + f" · 충족했지만 SW 여유 &lt; {TARGET_MARGIN_PCT:.0f}% {len(near)} — drop 먼저, 다음은 여유 작은 순 "
         "(여유 = NRT · Post 중 최소, SW 증가 시 먼저 drop).</p>"
         + table(rows[:max(top, len(drops) + len(other))]))
    if len(rows) > max(top, len(drops) + len(other)):
        h += f"<details class='more'><summary>전체 {len(rows)} scenario ▸</summary>{table(rows)}</details>"
    return h


def buffer_rows(snap: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for r in snap.get("scenarios") or []:
        lat, fb = r.get("latency") or {}, r.get("frame_buffer")
        frames = max(float(lat.get("preview_frames") or 0), float(lat.get("video_frames") or 0))
        if not frames:
            continue
        alive = max(1, math.ceil(frames - 1e-9))
        out.append({"scenario_id": r["scenario_id"], "variant_id": r["variant_id"], "fps": r.get("fps"),
                    "video_ms": lat.get("video_ms"), "preview_ms": lat.get("preview_ms"), "frames": round(frames, 2),
                    "alive": alive, "frame_mb": (fb or {}).get("mb"),
                    "buffer_mb": round(alive * float(fb["mb"]), 1) if fb and fb.get("mb") is not None else None,
                    "spec_ok": r.get("spec_ok")})
    out.sort(key=lambda o: (-(o["buffer_mb"] or 0), -o["frames"]))
    return out


def latency_buffer_block(snap: dict[str, Any], top: int = 10) -> str:
    rows = buffer_rows(snap)
    if not rows:
        return ("<h3 style='margin:12px 0 4px'>Latency → buffer</h3>"
                "<p class=meta>latency 정보 없음 (이전 형식 snapshot) — 재생성하면 표시</p>")
    limit = (((snap.get("review_context") or {}).get("policy") or {}).get("max_latency_frames"))
    has_mb = any(o["buffer_mb"] is not None for o in rows)

    def table(rs: list[dict[str, Any]]) -> str:
        h = ("<table><tr><th>Scenario</th><th>fps</th><th>Video latency ms</th><th>Preview latency ms</th><th>latency (frame)</th>"
             "<th>동시 frame</th><th>frame당 buffer MB</th><th>추정 buffer MB</th></tr>")
        for o in rs:
            over = limit is not None and o["frames"] > float(limit)
            h += (f"<tr><td>{escape(_short(o['variant_id']))}</td><td class=n>{_f(o['fps'], 0)}</td>"
                  f"<td class=n>{_f(o['video_ms'])}</td><td class=n>{_f(o['preview_ms'])}</td>"
                  f"<td class='n {'warn' if over else ''}'>{o['frames']:.2f}</td><td class=n>{o['alive']}</td>"
                  f"<td class=n>{_f(o['frame_mb'])}</td><td class=n><b>{_f(o['buffer_mb'], 0)}</b></td></tr>")
        return h + "</table>"

    h = ("<h3 style='margin:12px 0 4px'>Latency → buffer 사용</h3>"
         "<p class=meta>latency가 문제된 적은 드물지만, 처리 중인 frame마다 M2M buffer를 잡는다. 동시 frame = ⌈latency ÷ 주기⌉, "
         "frame당 buffer = 조합 탐색 목적 slice의 DMA write 합 ÷ fps (plane · buffer마다 frame당 한 번 쓰는 양, 그 slice의 compression 반영 — "
         "보고 조합이 compression을 더 쓰면 그만큼 작아짐). 추정 buffer = 동시 frame × frame당 buffer — 할당기 값이 아닌 spec 단계 크기 추정 "
         "(frame 수만큼 모든 buffer가 살아 있다는 상한)."
         + (f" latency 한도 {limit} frame(review_policy.max_latency_frames) 초과는 주황." if limit is not None else "")
         + "</p>"
         + ("" if has_mb else "<p class=meta>frame당 buffer 미산정 — 이 run은 DMA write 집계 이전 계산. 조합 탐색 재실행 · 재등록 후 재생성하면 표시</p>")
         + table(rows[:top]))
    if len(rows) > top:
        h += f"<details class='more'><summary>전체 {len(rows)} scenario ▸</summary>{table(rows)}</details>"
    return h


def _stage_load(st: dict[str, Any]) -> tuple[float, float, float] | None:
    """(SW the cut applies to, time that must fit the period, fixed HW part) under the stage's own throughput rule:
    pipelined = the binding SW load (longest task or one CPU's sequential SW) alone; stage = HW + all the stage's SW."""
    if st.get("basis") == "stage":
        sw, hw = st.get("sw_ms"), st.get("hw_ms")
        if sw is None:
            return None
        return float(sw), float(sw) + float(hw or 0.0), float(hw or 0.0)
    load = st.get("binding_ms") or st.get("bottleneck_ms")
    return None if load is None else (float(load), float(load), 0.0)


def sw_requests(snap: dict[str, Any]) -> list[dict[str, Any]]:
    """Per SW task that binds an NRT / Post stage: scenarios, longest load, smallest margin, the cut for a 10 % margin
    and the margin left under the project's SW growth budget. Rows are keyed by (scenario, variant)."""
    budget = float((((snap.get("review_context") or {}).get("policy") or {}).get("sw_growth_budget")) or 1.0)
    tasks: dict[str, dict[str, Any]] = {}
    for r in snap.get("scenarios") or []:
        p = r.get("period_ms")
        if not p:
            continue
        key = (r["scenario_id"], r["variant_id"])
        for st in r.get("sw_stages") or []:
            name, ld = st.get("bottleneck"), _stage_load(st)
            if not name or ld is None or st.get("margin_pct") is None:
                continue
            sw, used, hw = ld
            p = float(p)
            need = max(0.0, used - (1 - TARGET_MARGIN_PCT / 100) * p)
            grown = 100.0 * (p - hw - sw * budget) / p
            share = 100.0 * float(st.get("bottleneck_ms") or sw) / float(st["chain_ms"]) if st.get("chain_ms") else None
            t = tasks.setdefault(str(name), {"task": str(name), "stages": set(), "variants": [], "low": [], "grown_low": [],
                                              "max_ms": 0.0, "min_margin": None, "worst": None, "need_ms": 0.0,
                                              "need_variant": None, "need_fps": None, "share_pct": None, "binding": set(),
                                              "need_model_fps": None, "basis": set()})
            t["stages"].add(str(st.get("stage")))
            t["binding"].add(str(st.get("binding") or "task"))
            t["basis"].add(str(st.get("basis") or "pipelined"))
            for lst, on in ((t["variants"], True), (t["low"], float(st["margin_pct"]) < TARGET_MARGIN_PCT),
                            (t["grown_low"], grown < TARGET_MARGIN_PCT)):
                if on and key not in lst:
                    lst.append(key)
            t["max_ms"] = max(t["max_ms"], sw)
            if t["min_margin"] is None or float(st["margin_pct"]) < t["min_margin"]:
                t["min_margin"], t["worst"] = float(st["margin_pct"]), r["variant_id"]
            if need > t["need_ms"]:
                t["need_ms"], t["need_variant"], t["need_fps"] = round(need, 2), r["variant_id"], r.get("fps")
            # the largest cut among scenarios the model represents (below the unmodelled high-fps batch range)
            if need > 0 and float(r.get("fps") or 0) < HIGH_FPS and need > (t["need_model_fps"] or 0.0):
                t["need_model_fps"] = round(need, 2)
            if share is not None:
                t["share_pct"] = max(t["share_pct"] or 0.0, round(share, 0))
    out = []
    for t in tasks.values():
        t["stages"], t["binding"], t["basis"] = sorted(t["stages"]), sorted(t["binding"]), sorted(t["basis"])
        t["budget"] = budget
        out.append(t)
    out.sort(key=lambda t: (-len(t["low"]), -t["need_ms"], -len(t["grown_low"]), t["min_margin"] if t["min_margin"] is not None else 1e9))
    return out


def _advice(t: dict[str, Any]) -> str:
    if t["need_ms"] > 0:
        hfr = float(t.get("need_fps") or 0) >= HIGH_FPS
        note = ""
        if hfr:
            note = (f" · {HIGH_FPS:.0f} fps 이상 batch 미모델 — 상한값, batch 동작 정의 후 재판정"
                    + (f" (그 외 최대 {t['need_model_fps']:.1f} ms)" if t.get("need_model_fps") else " (그 외 scenario는 단축 불필요)"))
        return (f"{t['need_ms']:.1f} ms 이상 단축 필요 ({_short(str(t['need_variant']))}){note} — task 분할(thread 병렬) · HW offload · "
                "상위 cluster 배치 · 고속 mode 간헐 실행")
    if t["grown_low"]:
        return f"현재 여유 있음, SW ×{t['budget']:.1f} 증가 시 {len(t['grown_low'])}개 여유 < {TARGET_MARGIN_PCT:.0f}% — 차기 SW 최적화 목표에 포함"
    return "여유 충분 — 감시"


def sw_request_block(snap: dict[str, Any], top: int = 8) -> str:
    reqs = sw_requests(snap)
    if not reqs:
        return ""
    act = [t for t in reqs if t["low"] or t["grown_low"]]
    budget = reqs[0]["budget"]

    def table(ts: list[dict[str, Any]]) -> str:
        h = ("<table><tr><th>SW task</th><th>stage</th><th>병목인 scenario</th><th>여유 &lt; 10%</th>"
             f"<th>SW ×{budget:.1f} 시 &lt; 10%</th><th>최장 ms</th><th>최소 여유</th><th>stage chain 중 비중</th><th>요청</th></tr>")
        for t in ts:
            m = t["min_margin"]
            h += (f"<tr><td class=mono><b>{escape(t['task'])}</b>"
                  + (" <span class=meta>(CPU 공유 load)</span>" if any(b != "task" for b in t["binding"]) else "") + "</td>"
                  f"<td>{escape(' · '.join(s.upper() for s in t['stages']))}</td><td class=n>{len(t['variants'])}</td>"
                  f"<td class='n {'fail' if t['low'] else ''}'>{len(t['low'])}</td><td class='n {'warn' if t['grown_low'] else ''}'>{len(t['grown_low'])}</td>"
                  f"<td class=n>{t['max_ms']:.1f}</td><td class='n {'fail' if m is not None and m < 0 else 'warn' if m is not None and m < TARGET_MARGIN_PCT else ''}'>"
                  f"{_f(m, 0)}% <span class=meta>{escape(_short(str(t['worst'])))}</span></td>"
                  f"<td class=n>{_f(t['share_pct'], 0)}%</td><td>{escape(_advice(t))}</td></tr>")
        return h + "</table>"

    h = ("<h3 style='margin:12px 0 4px'>SW 최적화 요청 — critical path SW task</h3>"
         f"<p class=meta>NRT · Post stage를 묶는 SW task별 집계 — pipelined 판정은 최장 task 또는 같은 CPU의 순차 load, stage 판정은 "
         f"HW + stage SW 전체가 주기 안에 들어야 함. 필요 단축 = 여유 {TARGET_MARGIN_PCT:.0f}%를 "
         f"만드는 runtime 감소량, SW ×{budget:.1f} = 과제 SW 증가 예산(review_policy.sw_growth_budget) 적용 시. "
         "stage chain 중 비중이 크면 latency(= buffer)도 같이 줄어든다. SW timing이 가정값이면 전과제 Perfetto runtime으로 먼저 확인.</p>"
         + (f"<p><b>요청 {len(act)}건</b>: " + escape(", ".join(t["task"] for t in act[:5])) + "</p>" if act else
            "<p class=meta>여유 &lt; 10% 또는 SW 증가 시 &lt; 10%인 task 없음</p>")
         + table(reqs[:top]))
    if len(reqs) > top:
        h += f"<details class='more'><summary>전체 {len(reqs)} task ▸</summary>{table(reqs)}</details>"
    return h
