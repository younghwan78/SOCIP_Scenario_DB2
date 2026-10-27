"""Natural-language What-if through an in-house OpenAI-compatible LLM (chat completions).

The LLM only turns a question into the *same conditions the builder produces* — a question kind
(``what_if`` / ``search_limit`` / ``diagnose``) and registered change kinds against this variant's own
targets (DVFS domains with their OPP ladder, IPs, outputs, FPS). It never computes results: every number in
the answer comes from the Timing Budget engine. Its output is validated like builder input; anything that
does not match a target is dropped with a reason. When the endpoint is not configured or fails, the caller
reports why and the UI continues with the condition builder (no regex fallback).
"""
from __future__ import annotations

import json
import re
import time
import math
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from scenario_db.config import get_settings

ASKS = ("what_if", "combine", "search_limit", "diagnose")
FOCUS = ("power", "clock", "bw", "timing", "feasible")
CODE_RE = re.compile(r"\b(?:select|insert|delete|drop\s+table|update\s+\w+\s+set|exec|eval)\b|[;`{}]", re.I)


class LlmUnavailable(Exception):
    """Endpoint not configured, unreachable, or the reply was unusable — the reason is shown to the user."""


class _LlmPlan(BaseModel):
    ask: str = "what_if"
    changes: list[Any] = Field(default_factory=list, max_length=8)
    search_domains: list[str] = Field(default_factory=list, max_length=8)
    focus: list[str] = Field(default_factory=list, max_length=5)
    unsupported: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    notes: list[str] = Field(default_factory=list, max_length=5)
    clarification: dict[str, Any] | None = None


def llm_status() -> dict[str, Any]:
    s = get_settings()
    configured = bool(s.whatif_llm_base_url and s.whatif_llm_model)
    return {"available": configured, "model": s.whatif_llm_model if configured else None}


# ------------------------------------------------------------------ prompt
SYSTEM = """You turn an SoC multimedia engineer's What-if question (Korean or English) into a JSON plan for ONE scenario variant.
You never compute or guess results. Use only the targets listed in CATALOG; never invent ids.

Return ONLY a JSON object:
{
  "ask": "what_if" | "combine" | "search_limit" | "diagnose",
  "changes": [ ... ],            // what_if / combine only, at most 8
  "search_domains": ["..."],     // search_limit only: DVFS domain ids to lower step by step
  "focus": ["power"|"clock"|"bw"|"timing"|"feasible"],
  "clarification": null | {"message": "...", "choices": [{"label": "...", "change": {...}}]},
  "unsupported": [{"text": "part of the question", "reason": "why it cannot be modelled"}],
  "notes": ["short Korean note on how you read the question"]
}
Change forms (pick the ones the question asks for; leave everything else unchanged):
  {"target":"dvfs_level","domain":D,"shift":-1}      // one OPP level down (+1 = up)
  {"target":"dvfs_level","domain":D,"level":N}       // pin to level N (must be in the ladder)
  {"target":"dvfs_level","domain":D,"pin":"min"|"max"}
  {"target":"node_clock_mhz","node_id":IP,"value":MHz} | {"target":"node_clock_mhz","node_id":IP,"scale":0.8}
  {"target":"output_size","anchor_id":A,"width":W,"height":H}
  {"target":"fps","value":F}
  {"target":"node_size","node_id":IP,"width":W,"height":H} | {"target":"stream_size","stream_id":S,"width":W,"height":H}
  {"target":"sensor_mode","node_id":SENSOR,"option":ID}          // another sensor / DT mode (ids in levers.sensors)
  {"target":"chain_size","node_id":IP,"width":W,"height":H}      // crop/downscale at IP (bayer crop at BYRP, YUV downscale at YUVSC)
  {"target":"power_knob","param":KNOB,"option":VALUE}            // declared power option, e.g. pyramid_l0=skip (MTNR L0 bypass)
  {"target":"history_interval","value":N} | {..., "buffer_id":B} // previous-frame DMA once every N frames (30fps -> 15fps = 2)
  {"target":"ip_mode","node_id":IP,"option":MODE}
  {"target":"compression","buffer_id":B,"option":MODE}           // COMP_OFF or a listed SBWC mode (lossless / lossy …)
  {"target":"llc_alloc","buffer_id":B,"option":"on"|"off"}       // LLC allocation of a DMA buffer (optional "value" = llc_weight 0-1)
Rules:
- "level/단계/OPP 낮추면" on a domain = dvfs_level shift. "어디까지/몇 단계까지/한계" = search_limit. "병목/어디가 빡빡/여유가 제일 적은" = diagnose.
- Sizes: FHD 1920x1080, UHD/4K 3840x2160, QHD 2560x1440, HD 1280x720, 8K 7680x4320. A bare size in a recording scenario means the record output.
- If a needed value or target is genuinely ambiguous, return a clarification whose every choice carries a complete change.
- "N개 조합 비교 / 같이 적용하면 vs 각각" = ask "combine" with the levers as changes.
- Codec/bitrate, feature on/off (EIS, HDR), voltage and CPU placement are NOT changes: list them in "unsupported".
"""


def catalog(targets: dict[str, Any]) -> dict[str, Any]:
    """Compact, model-readable view of the variant's targets."""
    return {
        "fps": targets.get("fps"),
        "dvfs_domains": [{"id": d["id"], "current_level": d["level"], "current_mhz": d["mhz"], "ips": d["ips"],
                          "ladder_slow_to_fast": [f"L{lv['level']}={lv['mhz']:g}MHz" for lv in d["ladder"]]}
                         for d in targets.get("domains") or []],
        "ips": [{"id": n["id"], "ip": n.get("ip"), "category": n.get("category"), "clock_mhz": n.get("clock_mhz"),
                 "clock_change": n.get("clock_supported"), "size_change": n.get("size_supported")} for n in targets.get("nodes") or []],
        "outputs": [{"id": a["id"], "size": a["size"], "role": a.get("role")} for a in targets.get("anchors") or []
                    if a.get("kind") == "output" and a.get("supported")],
        "streams": [{"id": st["id"], "size": st["size"], "primary": st.get("primary")} for st in targets.get("streams") or []],
        "levers": {
            "sensors": [{"node": r["node_id"], "current": r["options"][0]["id"] if r["options"] else None,
                         "options": [o["id"] for o in r["options"][:12]]} for r in targets.get("sensors") or []],
            "crop_downscale_at": [{"node": r["id"], "size": r["size"], "downstream": r["downstream"]} for r in targets.get("chains") or []],
            "power_knobs": [{"param": r["param"], "current": r["current"], "options": [o["id"] for o in r["options"]]} for r in targets.get("knobs") or []],
            "history_buffers": [r["id"] for r in targets.get("history") or []],
            "ip_modes": [{"node": r["id"], "current": r["mode"], "options": [o["id"] for o in r["options"]]} for r in targets.get("ip_modes") or []],
            "compression": [{"buffer": r["id"], "current": r["current"], "options": [o["id"] for o in r["options"] if o["supported"] is not False]}
                            for r in targets.get("buffers") or [] if r["declared"]],
            "llc": [{"buffer": r["id"], "current": r["current"], "default_weight": r["options"][1].get("weight")}
                    for r in targets.get("llc") or []][:40],
        },
    }


def _chat(messages: list[dict[str, str]]) -> tuple[str, float]:
    s = get_settings()
    if not (s.whatif_llm_base_url and s.whatif_llm_model):
        raise LlmUnavailable("사내 LLM이 설정되지 않았습니다 (SCENARIO_DB_WHATIF_LLM_BASE_URL / _MODEL)")
    url = s.whatif_llm_base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if s.whatif_llm_api_key:
        headers["Authorization"] = f"Bearer {s.whatif_llm_api_key.get_secret_value()}"
    body: dict[str, Any] = {"model": s.whatif_llm_model, "messages": messages, "temperature": 0}
    if s.whatif_llm_json_mode:
        body["response_format"] = {"type": "json_object"}
    started = time.monotonic()
    try:
        with httpx.Client(timeout=s.whatif_llm_timeout_s, trust_env=False) as client:
            res = client.post(url, json=body, headers=headers)
            if res.status_code in (400, 422) and "response_format" in body:   # server without JSON mode
                body.pop("response_format")
                res = client.post(url, json=body, headers=headers)
            res.raise_for_status()
            content = res.json()["choices"][0]["message"]["content"]
    except httpx.TimeoutException as exc:
        raise LlmUnavailable(f"사내 LLM 응답 시간 초과 ({s.whatif_llm_timeout_s:g} s)") from exc
    except httpx.HTTPStatusError as exc:
        raise LlmUnavailable(f"사내 LLM 오류 HTTP {exc.response.status_code}") from exc
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise LlmUnavailable(f"사내 LLM 호출 실패: {type(exc).__name__}") from exc
    return str(content or ""), round((time.monotonic() - started) * 1000)


def _json(text: str) -> dict[str, Any]:
    text = re.sub(r"^\s*```(?:json)?|```\s*$", "", text.strip(), flags=re.I | re.M).strip()
    try:
        data = json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise LlmUnavailable("사내 LLM 응답이 JSON이 아닙니다") from None
        try:
            data = json.loads(m.group(0))
        except ValueError:
            raise LlmUnavailable("사내 LLM 응답이 JSON이 아닙니다") from None
    if not isinstance(data, dict):
        raise LlmUnavailable("사내 LLM 응답 형식이 올바르지 않습니다")
    return data


# ------------------------------------------------------------------ normalization (same rules as the builder)
def resolve_change(raw: Any, targets: dict[str, Any]) -> tuple[dict | None, str | None, str | None]:
    """(concrete change, problem, boundary message). Relative forms (shift / pin / scale) become values."""
    from scenario_db.api.schemas.scenario_whatif import WhatIfChange

    if not isinstance(raw, dict):
        return None, "조건 형식이 아닙니다", None
    change = {k: v for k, v in raw.items() if v is not None}
    target = change.get("target")
    if target == "dvfs_level":
        domains = {d["id"]: d for d in targets.get("domains") or []}
        d = domains.get(str(change.get("domain")))
        if d is None:
            return None, f"이 variant에 없는 DVFS domain: {change.get('domain')} (있는 domain: {', '.join(domains) or '없음'})", None
        ladder, idx = d["ladder"], d["index"]
        if "shift" in change or "pin" in change:
            if sum(k in change for k in ("shift", "pin", "level")) != 1:
                return None, "DVFS level·shift·pin 중 하나만 지정하세요", None
            if "pin" in change:
                pin = change.pop("pin")
                if pin not in ("min", "max"):
                    return None, "pin은 min 또는 max여야 합니다", None
                j = 0 if pin == "min" else len(ladder) - 1
            else:
                shift = change.pop("shift")
                if not isinstance(shift, int) or isinstance(shift, bool):
                    return None, "DVFS shift는 정수여야 합니다", None
                j = idx + shift
            if not 0 <= j < len(ladder):
                edge = ladder[0] if j < 0 else ladder[-1]
                return None, None, (f"{d['id']}는 이미 {'최저' if j < 0 else '최고'} OPP L{edge['level']} ({edge['mhz']:g} MHz)라 "
                                    f"더 {'낮출' if j < 0 else '올릴'} level이 없습니다")
            if j == idx:
                return None, None, f"{d['id']}는 이미 L{d['level']} ({d['mhz']:g} MHz)입니다"
            change["level"] = ladder[j]["level"]
    if target == "node_clock_mhz" and "scale" in change:
        node = next((n for n in targets.get("nodes") or [] if n["id"] == change.get("node_id")), None)
        if node is None or not node.get("clock_mhz"):
            return None, f"{change.get('node_id')}: 기준 clock이 없어 상대값을 MHz로 바꾸지 못했습니다", None
        scale = change.pop("scale")
        try:
            numeric_scale = float(scale) if isinstance(scale, (int, float)) and not isinstance(scale, bool) else float('nan')
        except OverflowError:
            numeric_scale = float('nan')
        if not math.isfinite(numeric_scale) or numeric_scale <= 0 or "value" in change:
            return None, "clock scale은 양의 유한수여야 하며 value와 함께 지정할 수 없습니다", None
        change["value"] = round(float(node["clock_mhz"]) * numeric_scale, 1)
    try:
        change = WhatIfChange(**change).model_dump(exclude_none=True)
    except (ValueError, TypeError) as exc:
        return None, f"조건 검증 실패: {str(exc).splitlines()[-1][:160]}", None
    if target == "dvfs_level" and change.get("level") not in {lv["level"] for lv in d["ladder"]}:
        return None, f"{d['id']}에 없는 OPP level", None
    ids = {"anchor_id": {a["id"] for a in targets.get("anchors") or []},
           "node_id": {n["id"] for n in targets.get("nodes") or []} | {r["node_id"] for r in targets.get("sensors") or []},
           "stream_id": {st["id"] for st in targets.get("streams") or []},
           "buffer_id": {r["id"] for r in (targets.get("buffers") or []) + (targets.get("history") or [])}}
    for key, known in ids.items():
        if change.get(key) is not None and change[key] not in known:
            return None, f"이 variant에 없는 대상: {change[key]}", None
    return change, None, None


def interpret(query: str, targets: dict[str, Any]) -> dict[str, Any]:
    """Question -> {ask, changes, search_domains, focus, clarification, ignored, notes, boundaries, meta}."""
    if CODE_RE.search(query):
        raise LlmUnavailable("SQL·코드는 해석하지 않습니다")
    content, latency = _chat([{"role": "system", "content": SYSTEM},
                              {"role": "user", "content": "CATALOG:\n" + json.dumps(catalog(targets), ensure_ascii=False)
                               + "\n\nQUESTION:\n" + query.strip()}])
    try:
        data = _LlmPlan.model_validate(_json(content)).model_dump()
        if data["ask"] not in ASKS:
            raise LlmUnavailable("사내 LLM이 지원하지 않는 질문 종류를 반환했습니다")
        if (data["ask"] not in ("what_if", "combine") and data["changes"]) or (data["ask"] != "search_limit" and data["search_domains"]):
            raise LlmUnavailable("사내 LLM 응답의 질문 종류와 조건이 일치하지 않습니다")
        cl = data.get("clarification")
        if cl is not None and (not isinstance(cl.get("choices"), list) or not cl["choices"] or len(cl["choices"]) > 12):
            raise LlmUnavailable("사내 LLM 확인 질문 형식이 올바르지 않습니다")
    except ValidationError as exc:
        raise LlmUnavailable("사내 LLM 응답 조건 형식이 올바르지 않습니다") from exc
    out: dict[str, Any] = {"ask": data.get("ask") if data.get("ask") in ASKS else "what_if", "changes": [], "search_domains": [],
                           "focus": [f for f in data.get("focus") or [] if f in FOCUS], "clarification": None,
                           "ignored": [], "notes": [str(n)[:300] for n in data.get("notes") or [] if n][:5], "boundaries": [],
                           "meta": {"used": "llm", "model": get_settings().whatif_llm_model, "latency_ms": latency}}
    for item in data.get("unsupported") or []:
        if isinstance(item, dict) and item.get("text"):
            out["ignored"].append({"text": str(item["text"])[:300], "reason": str(item.get("reason") or "모델 범위 밖")[:300]})
    seen: dict[tuple, dict] = {}
    for raw in (data.get("changes") or [])[:8]:
        change, problem, boundary = resolve_change(raw, targets)
        if boundary:
            out["boundaries"].append(boundary)
        elif problem:
            out["ignored"].append({"text": json.dumps(raw, ensure_ascii=False)[:200], "reason": problem})
        elif change is not None:
            key = tuple(change.get(k) for k in ("target", "anchor_id", "node_id", "stream_id", "param", "domain", "buffer_id"))
            if key in seen and seen[key] != change:
                raise LlmUnavailable("같은 대상에 서로 다른 조건이 있습니다. 조건 편집기에서 하나를 선택하세요")
            if key not in seen:
                seen[key] = change
                out["changes"].append(change)
    domain_ids = {d["id"] for d in targets.get("domains") or []}
    if any(d not in domain_ids for d in data.get("search_domains") or []):
        raise LlmUnavailable("사내 LLM이 이 variant에 없는 탐색 domain을 반환했습니다")
    out["search_domains"] = [d for d in data.get("search_domains") or [] if d in domain_ids]
    cl = data.get("clarification")
    if isinstance(cl, dict) and cl.get("choices"):
        choices = []
        for ch in cl["choices"][:12]:
            if not isinstance(ch, dict):
                continue
            change, _, _boundary = resolve_change(ch.get("change"), targets)
            if change:
                choices.append({"label": str(ch.get("label") or change.get("target"))[:120], "change": change})
        if choices:
            out["clarification"] = {"message": str(cl.get("message") or "선택이 필요합니다")[:300], "choices": choices}
        else:
            raise LlmUnavailable("사내 LLM 확인 질문에 유효한 선택지가 없습니다")
    if out["ask"] == "search_limit" and not out["search_domains"]:
        out["notes"].append("탐색할 DVFS domain을 찾지 못해 모든 domain을 탐색합니다.")
    return out
