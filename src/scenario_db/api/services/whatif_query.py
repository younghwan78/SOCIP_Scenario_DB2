"""A bounded Korean/English grammar produces conditions, never executable code."""
from __future__ import annotations

import re
from typing import Any

SIZE_NAMES = {"FHD": (1920, 1080), "UHD": (3840, 2160), "4K": (3840, 2160), "8K": (7680, 4320)}
SIZE_PATTERN = r"(?<!\d)(\d{2,5})\s*[x×]\s*(\d{2,5})(?!\d)|(?<![A-Za-z0-9_])(?:FHD|UHD|4K|8K)(?![A-Za-z])"
FPS_PATTERN = r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:fps|프레임|frame(?:s)?\s*(?:/s|per\s+second))|(?:fps|프레임)\s*(?:를|을|=|:|to)?\s*(\d+(?:\.\d+)?)"
ACTION = r"변경|바꿔|낮춰|높여|줄여|늘려|끄|켜|\b(?:change|set|reduce|increase|disable|enable|turn)\b"
PRESERVE = r"유지|unchanged|\b(?:keep|retain)\b"
UNSUPPORTED = r"codec|코덱|compression|압축|sbwc|llc|eis|vdis|bitrate|비트레이트|전압|voltage|sw_margin|thermal|온도|밝기|brightness|contrast|팬|fan"
METRIC = r"clock|power|bw|timing|latency|cadence|클럭|전력|대역폭|처리시간|출력간격"
SUBJECT = r"sensor|input|output|record|preview|size|fps|clock|baseline|센서|입력|출력|녹화|미리보기|크기|프레임|클럭|기준"
ENGLISH_GRAMMAR = (
    r"(?<![A-Za-z0-9_])(?:change|changes|changed|changing|set|reduce|increase|keep|retain|unchanged|"
    r"sensor|input|output|record|recording|video|preview|size|resolution|anchor|node|buffer|"
    r"clock|clocks|power|bw|timing|latency|cadence|fps|scenario|variant|project|target|baseline|"
    r"from|to|the|a|an|this|that|same|at|in|of|for|with|into|by|as|it|its|"
    r"how|what|would|will|does|do|is|are|be|if|then|happen|happens|affect|affects|effect|"
    r"impact|compare|comparison|please|show|tell|me)(?![A-Za-z0-9_])"
)
KOREAN_GRAMMAR = (
    r"소비전력|처리시간|출력간격|미리보기|시나리오|대역폭|프레임|해상도|버퍼|"
    r"변하는지|바뀌는지|달라지는지|어떻게|얼마나|변경|변화|바꿔|줄여|늘려|낮춰|높여|유지|클럭|전력|센서|입력|"
    r"출력|녹화|중간|노드|크기|조건|기준|목표|결과|예측|영향|비교|알려줘|보여줘|"
    r"되는|되면|되고|하면|한다면|경우|어떤|으로|에서|은|는|을|를|로|의|가|과|와|에|도|다|줘"
)


def _mentions(query: str, value: str) -> bool:
    return re.search(r"(?<![A-Za-z0-9_-])" + re.escape(value) + r"(?![A-Za-z0-9_-])", query, re.I) is not None


def _transition(clause: str) -> bool:
    return bool(re.search(r"\bfrom\b.*\bto\b|에서.*(?:으로|로)", clause, re.I))


def _unmatched(clause: str, targets: dict[str, Any]) -> str:
    """Consume only supported condition values/selectors and explicit grammar.

    Any remaining word or value is an unhandled part of the request, including
    directives that appear in the same clause as a valid FHD/FPS/clock change.
    """
    remaining = clause
    identifiers = [r["id"] for group in ("anchors", "nodes") for r in targets[group]]
    identifiers += [targets[key] for key in ("scenario_id", "variant_id", "project_ref") if key in targets]
    for value in sorted(set(identifiers), key=len, reverse=True):
        remaining = re.sub(r"(?<![A-Za-z0-9_-])" + re.escape(value) + r"(?![A-Za-z0-9_-])", " ", remaining, flags=re.I)
    for pattern in (SIZE_PATTERN, FPS_PATTERN, r"(?<!\d)(\d+(?:\.\d+)?)\s*mhz"):
        remaining = re.sub(pattern, " ", remaining, flags=re.I)
    remaining = re.sub(ENGLISH_GRAMMAR, " ", remaining, flags=re.I)
    remaining = re.sub(KOREAN_GRAMMAR, " ", remaining)
    return re.sub(r"[\s?.!():=\-/]", "", remaining)


def plan_query(query: str, targets: dict[str, Any]) -> dict[str, Any]:
    """Only explicitly supported clauses run; preservation and ambiguity never become changes."""
    q = query.strip()
    out: dict[str, Any] = {"query": q, "status": "ready", "changes": [], "clarifications": [],
           "warnings": ["지원 문법으로 조건을 해석했습니다. 실행 전에 대상과 변경값을 확인하세요."]}

    def unsupported(message):
        return {**out, "status": "unsupported", "changes": [], "warnings": [message]}

    def clarify(field, message, values=()):
        out["clarifications"].append({"field": field, "message": message,
            "choices": [{"label": v, "value": v} for v in values]})

    if re.search(r"\b(?:select|insert|delete|drop|update|exec|eval|python|javascript)\b|[;\x60{}]", q, re.I):
        return unsupported("SQL·코드 실행은 지원하지 않습니다. 크기·FPS·노드 clock 변경을 요청하세요.")
    # Separate clauses prevent unchanged sensor dimensions or a clock node
    # from overwriting a different output condition.
    clauses = [c.strip() for c in re.split(r",|\band\b|그리고|하고", q, flags=re.I) if c.strip()]
    for clause in clauses:
        preserve = bool(re.search(PRESERVE, clause, re.I))
        action = bool(re.search(ACTION, clause, re.I))
        if _unmatched(clause, targets):
            return unsupported("지원 문법으로 해석하지 못한 요청 부분이 있습니다. 크기·FPS·노드 clock 변경과 영향 질문만 지원합니다.")
        if preserve:
            if not re.search(SUBJECT, clause, re.I):
                return unsupported("유지할 대상을 명확히 지정하세요.")
            if action:
                clarify("condition", "유지 조건과 변경 조건을 각각 분리해 지정하세요.")
            continue
        if re.search(UNSUPPORTED, clause, re.I):
            return unsupported("지원하지 않는 추가 조건이 있습니다. 현재 크기·FPS·노드 clock 변경만 지원합니다.")
        sizes = list(re.finditer(SIZE_PATTERN, clause, re.I))
        fps = list(re.finditer(FPS_PATTERN, clause, re.I))
        clocks = list(re.finditer(r"(?<!\d)(\d+(?:\.\d+)?)\s*mhz", clause, re.I))
        if not (sizes or fps or clocks):
            if not re.search(METRIC, clause, re.I) or action:
                return unsupported("해석할 수 없는 추가 조건이 있습니다. 변경 대상과 값을 명시하세요.")
            continue
        if action and not (sizes or fps or clocks):
            return unsupported("지원 문법으로 해석할 수 없는 추가 변경이 있습니다. 각 변경 대상과 값을 명시하세요.")
        if sizes:
            if re.search(r"센서|sensor", clause, re.I):
                return unsupported("센서 크기는 Sensor Explore에서 검증된 catalog mode로 선택하세요.")
            if len(sizes) > 1 and not _transition(clause):
                clarify("size", "변경할 크기를 하나 지정하거나 'UHD에서 FHD로'처럼 기준과 목표를 구분하세요.")
                continue
            match = sizes[-1]
            size = (int(match[1]), int(match[2])) if match[1] else SIZE_NAMES[match[0].upper()]
            if any(v < 16 or v > 16384 for v in size):
                return unsupported("크기 각 축은 16~16384 범위여야 합니다.")
            anchors = [r for r in targets["anchors"] if _mentions(clause, r["id"])]
            nodes = [r for r in targets["nodes"] if _mentions(clause, r["id"])]
            change: dict[str, Any] = {"width": size[0], "height": size[1]}
            if anchors:
                if len(anchors) != 1:
                    clarify("size_target", "변경할 anchor를 하나 지정하세요.", [r["id"] for r in anchors if r["supported"]])
                    continue
                if not anchors[0]["supported"]:
                    return unsupported("센서 크기는 Sensor Explore에서 catalog mode로 선택하세요.")
                change.update(target="anchor_size", anchor_id=anchors[0]["id"])
            elif re.search(r"녹화|record(?:ing)?|video\s+output", clause, re.I):
                candidates = [a for a in targets["output_targets"] if "record" in a or "video" in a]
                if len(candidates) != 1:
                    clarify("output_target", "변경할 녹화 출력을 지정하세요.", candidates)
                    continue
                change.update(target="output_size", anchor_id=candidates[0])
            elif re.search(r"미리보기|preview", clause, re.I):
                candidates = [a for a in targets["output_targets"] if "preview" in a]
                if len(candidates) != 1:
                    clarify("output_target", "변경할 미리보기 출력을 지정하세요.", candidates)
                    continue
                change.update(target="output_size", anchor_id=candidates[0])
            elif nodes:
                if len(nodes) != 1 or not nodes[0]["size_supported"]:
                    return unsupported("다중 포트/RT/복수 노드 크기는 변경할 anchor를 명확히 지정하세요.")
                change.update(target="node_size", node_id=nodes[0]["id"])
            else:
                clarify("size_target", "size가 센서·출력·중간 buffer·노드 중 무엇인지 지정하세요.",
                        [r["id"] for r in targets["anchors"] if r["supported"]])
                continue
            out["changes"].append(change)
        if fps:
            if len(fps) > 1 and not _transition(clause):
                clarify("fps", "변경할 FPS를 하나 지정하세요.")
                continue
            value = float(fps[-1][1] or fps[-1][2])
            if value <= 0 or value > 240:
                return unsupported("FPS는 0보다 크고 240 이하여야 합니다.")
            out["changes"].append({"target": "fps", "value": value})
        if clocks:
            if len(clocks) > 1 and not _transition(clause):
                clarify("clock", "변경할 clock을 하나 지정하세요. 복수 clock 비교는 구조화 조건으로 실행하세요.")
                continue
            value = float(clocks[-1][1])
            if value <= 0 or value > 5000:
                return unsupported("clock은 0보다 크고 5000 MHz 이하여야 합니다.")
            nodes = [r for r in targets["nodes"] if _mentions(clause, r["id"]) and r["clock_supported"]]
            if len(nodes) != 1:
                clarify("node_id", "clock을 변경할 노드를 지정하세요.", [r["id"] for r in targets["nodes"] if r["clock_supported"]])
                continue
            out["changes"].append({"target": "node_clock_mhz", "node_id": nodes[0]["id"], "value": value})
    if out["clarifications"]:
        out["status"] = "clarification"
        out["changes"] = []
    elif not out["changes"]:
        return unsupported("해석할 변경 조건이 없습니다. 예: '센서 입력은 유지하고 녹화 출력을 FHD로 변경', 'FPS를 60으로 변경', 'mfc_enc clock 600 MHz'.")
    keys = [(c["target"], c.get("anchor_id"), c.get("node_id")) for c in out["changes"]]
    if len(keys) != len(set(keys)) or len(keys) > 8:
        clarify("condition", "같은 대상의 여러 값이나 8개를 넘는 조건은 구조화 조건으로 나눠 실행하세요.")
        out.update(status="clarification", changes=[])
    return out
