"""Free-form Korean/English What-if questions -> explicit, reviewable conditions (never executable code).

The parser is extractive rather than all-or-nothing:
* supported conditions (output/anchor/IP size, FPS, IP clock — absolute or relative) become ``changes``;
* parts it cannot model are returned in ``ignored`` with the reason and the page that handles them;
* ambiguity becomes a ``clarification`` whose every choice already carries the complete change, so the
  UI resolves it with one click instead of asking for a rewritten sentence;
* ``focus`` lists the metrics the question asks about so the answer can lead with them.
Relative IP clocks are returned with ``scale`` and resolved to MHz by the service against the baseline.
Nothing is executed here; the caller previews the normalized changes explicitly.
"""
from __future__ import annotations

import re
from typing import Any

# ASCII word boundaries: "BW랑", "EIS를" must still match (Korean particles are \\w in Unicode mode)
F = re.I | re.A

SIZE_NAMES = {"8K": (7680, 4320), "4320P": (7680, 4320), "UHD": (3840, 2160), "4K": (3840, 2160), "2160P": (3840, 2160),
              "QHD": (2560, 1440), "1440P": (2560, 1440), "FHD": (1920, 1080), "1080P": (1920, 1080),
              "HD": (1280, 720), "720P": (1280, 720)}
_NAMED = r"8K|4K|UHD|QHD|FHD|HD|4320p|2160p|1440p|1080p|720p"
# "UHD60", "4K@30", "1080p60" carry an FPS with the size
SIZE_RE = re.compile(r"(?<!\d)(?P<w>\d{2,5})\s*[x×*]\s*(?P<h>\d{2,5})(?!\d)"
                     r"|(?<![A-Za-z0-9_])(?P<name>" + _NAMED + r")(?:\s*@?\s*(?P<rate>\d{2,3})(?!\d|\s*(?:%|퍼센트|배|mhz|ghz|[x×*]\s*\d)))?(?![A-Za-z0-9])", F)
FPS_RE = re.compile(r"(?<![\d.])(?P<a>\d+(?:\.\d+)?)\s*(?:fps|프레임|frames?\s*(?:/\s*s|per\s+second))"
                    r"|(?:fps|프레임\s*레이트|frame\s*rate|프레임|초당)\s*(?:을|를|은|는|이|가|=|:|to)?\s*(?P<b>\d+(?:\.\d+)?)(?!\s*(?:%|퍼센트|배|mhz|ghz|\d))", F)
CLOCK_RE = re.compile(r"(?<![\d.])(?P<v>\d+(?:\.\d+)?)\s*(?P<u>mhz|ghz)", F)
PCT_RE = re.compile(r"(?<![\d.])(?P<p>\d+(?:\.\d+)?)\s*(?:%|퍼센트|percent)", F)
TIMES_RE = re.compile(r"(?<![\d.])(?P<x>\d+(?:\.\d+)?)\s*(?:배|times)(?![A-Za-z])", F)
HALF_RE = re.compile(r"절반|반으로|1/2|\bhalf\b", F)
DOWN_RE = re.compile(r"낮|줄|내리|내려|감소|축소|\b(?:down|lower|reduce|decrease|cut|drop)\b", F)
UP_RE = re.compile(r"높|올리|올려|늘|증가|확대|\b(?:up|raise|increase|boost)\b", F)
CHANGE_VERB = re.compile(r"변경|바꾸|바꿔|바뀌|낮|높|줄|늘|올리|올려|내리|내려|켜|끄|\b(?:change|set|turn|enable|disable|switch)\b", F)
PRESERVE_RE = re.compile(r"유지|그대로|고정|unchanged|\b(?:keep|retain|fixed)\b", F)
TRANSITION = re.compile(r"\bfrom\b.*\bto\b|에서.*(?:으로|로)|→|->", F)
CLOCK_WORD = re.compile(r"clock|클럭|클록|주파수|\bfreq", F)
FPS_WORD = re.compile(r"fps|프레임|frame\s*rate|초당", F)
SIZE_WORD = re.compile(r"해상도|크기|사이즈|\bsize\b|resolution", F)
RECORD_WORD = re.compile(r"녹화|레코딩|record(?:ing)?|video|동영상|인코딩|encod", F)
PREVIEW_WORD = re.compile(r"미리\s*보기|프리뷰|preview|viewfinder|뷰파인더", F)
SENSOR_WORD = re.compile(r"센서|sensor|binning|비닝|readout", F)
CODE_RE = re.compile(r"\b(?:select|insert|delete|drop\s+table|update\s+\w+\s+set|exec|eval|python|javascript)\b|[;\x60{}]", F)

# topic -> (reason, where it is handled). A clause that only carries these never becomes a change.
UNSUPPORTED_TOPICS: list[tuple[str, str, str | None]] = [
    (r"codec|코덱|\bapv\b|hevc|h\.?26[45]|\bavc\b|bit\s*-?rate|비트\s*레이트|mbps", "코덱·bitrate는 조건 비교 대상이 아닙니다",
     "Scenario에서 해당 코덱/bitrate variant 선택"),
    (r"compression|압축|sbwc|afbc|\bllc\b|votf|캐시|\bcache", "메모리 절감 옵션은 조건 비교 대상이 아닙니다", "조합 탐색의 memory lever"),
    (r"\beis\b|vdis|\bhdr\b|portrait|인물|supersteady|손떨림|stabiliz", "기능 on/off는 다른 variant입니다", "Scenario에서 기능이 다른 variant 선택"),
    (r"전압|voltage|\bmv\b|dvfs\s*table|\bopp\b", "전압·DVFS table 변경은 지원하지 않습니다", "Timing Budget의 DVFS what-if"),
    (r"\bcpu\b|코어|\bcores?\b|cluster|클러스터|\blf\d?\b|\bhf\b|\bbig\b|schedul|스케줄", "CPU 배치·주파수는 별도 화면입니다", "CPU what-if"),
    (r"thermal|온도|발열|throttl|밝기|brightness|contrast|sharpen|rotate|회전|\bfan\b|화질|\biq\b", "모델에 없는 항목입니다", None),
]
# words -> IP catalog category (SoC-agnostic: any IP of that category in the variant matches)
CATEGORY_WORDS = {"codec": r"인코더|encoder|디코더|decoder", "display": r"디스플레이|display|패널|panel",
                  "camera": r"\bisp\b|카메라\s*ip", "compute": r"\bgpu\b|\bnpu\b"}
REFRESH_RE = re.compile(r"(?<![\d.])(?P<v>\d+(?:\.\d+)?)\s*hz\b|(?:주사율|refresh(?:\s*rate)?)\s*(?:을|를|은|는|=|:|to)?\s*(?P<w>\d+(?:\.\d+)?)", re.I | re.A)
FOCUS = {"power": r"power|전력|소모|소비|\bmw\b|와트|watt|배터리|battery",
         "clock": r"clock|클럭|클록|주파수|\bfreq|dvfs",
         "bw": r"\bbw\b|대역폭|bandwidth|메모리|memory|traffic|트래픽",
         "timing": r"latency|지연|timing|타이밍|처리\s*시간|budget|예산|여유|slack|cadence|출력\s*간격",
         "feasible": r"가능|feasib|충족|되나|될까|되는지|돌아가|버티|버틸|문제\s*없|괜찮|\bdrop\b|\bfail|미달"}
FILLER = re.compile(
    r"(?<![A-Za-z0-9_])(?:change|changes|changed|set|to|from|the|a|an|this|that|it|its|and|or|if|then|what|how|would|will|does|do|is|are|be|"
    r"happen|happens|affect|affects|effect|impact|compare|please|show|tell|me|when|with|at|in|of|for|by|on|output|input|value|"
    r"keep|make|go|goes|going|about|much|many|new|current|baseline|recording|record|preview|size|resolution)(?![A-Za-z0-9_])", F)


def _mentions(text: str, value: str) -> bool:
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(value) + r"(?![A-Za-z0-9])", text, F) is not None


def _clauses(query: str) -> list[str]:
    # Korean connective "…하고/바꾸고/끄고 " ends a clause as well
    query = re.sub(r"(바꾸|바꿔|낮추|낮춰|올리|올려|줄이|줄여|늘리|늘려|내리|내려|변경하|끄|켜|두)고\s+", r"\1, ", query)
    parts = re.split(r"[,;\n]|\band\b|\bthen\b|그리고|하고|이고|면서|및|그\s*다음|\s&\s|또한", query, flags=F)
    return [p.strip() for p in parts if p and p.strip()]


def _even(v: float) -> int:
    return int(round(v / 2.0)) * 2


def _fmt(v: float) -> str:
    return f"{v:g}"


def _factor(half, pct, times, down: bool) -> float | None:
    if half:
        return 0.5
    if pct:
        p = float(pct["p"]) / 100
        return 1 - p if down else 1 + p
    if times:
        return float(times["x"])
    return None


def _find_nodes(clause: str, targets: dict[str, Any]) -> list[dict]:
    """Nodes named in the clause: id, label, IP stem (ip-gdc-… -> gdc), id prefix (mfc_enc -> mfc), aliases."""
    text = clause
    exact = [n for n in targets["nodes"] if _mentions(text, n["id"])]
    if exact:
        return exact
    hits: dict[str, dict] = {}
    for node in targets["nodes"]:
        names = {str(node.get("label") or ""), str(node.get("ip") or ""), str(node.get("hw_name") or ""),
                 re.split(r"[_\-]", node["id"])[0]}
        if any(len(n) >= 2 and _mentions(text, n) for n in names):
            hits[node["id"]] = node
    if not hits:
        for category, words in CATEGORY_WORDS.items():
            if re.search(words, text, F):
                hits.update({n["id"]: n for n in targets["nodes"] if n.get("category") == category})
        # "디코더" vs "인코더" inside the codec category
        if re.search(r"디코더|decoder", text, F):
            hits = {k: v for k, v in hits.items() if not re.search(r"enc", k, F)} or hits
        elif re.search(r"인코더|encoder", text, F):
            hits = {k: v for k, v in hits.items() if not re.search(r"dec", k, F)} or hits
    if not hits and re.search(r"(?<![A-Za-z])nr(?![A-Za-z])|노이즈|denoise", text, F):
        hits = {n["id"]: n for n in targets["nodes"] if n["id"].endswith("nr")}
    return list(hits.values())


def _output_target(clause: str, targets: dict[str, Any], query: str) -> tuple[str | None, list[str], str | None]:
    """Which output a size without an anchor id refers to: (anchor, choices if ambiguous, assumption note)."""
    outs = list(targets["output_targets"])
    roles = {a["id"]: a.get("role") for a in targets["anchors"]}
    record = [a for a in outs if roles.get(a) == "record" or (roles.get(a) is None and re.search(r"record|video|enc", a, F))]
    preview = [a for a in outs if roles.get(a) == "preview" or (roles.get(a) is None and re.search(r"preview|disp", a, F))]
    if PREVIEW_WORD.search(clause):
        return (preview[0], [], None) if len(preview) == 1 else (None, preview or outs, None)
    if RECORD_WORD.search(clause):
        return (record[0], [], None) if len(record) == 1 else (None, record or outs, None)
    if len(outs) == 1:
        return outs[0], [], None
    # a bare resolution in a recording use case means the recorded stream; preview has to be named
    if len(record) == 1 and not PREVIEW_WORD.search(query):
        return record[0], [], f"크기 대상을 지정하지 않아 녹화 출력({record[0]})으로 해석했습니다. 미리보기는 '미리보기'로 지정하세요."
    return None, outs, None


def _size_value(match: re.Match) -> tuple[int, int]:
    if match["w"]:
        return int(match["w"]), int(match["h"])
    return SIZE_NAMES[match["name"].upper()]


def plan_query(query: str, targets: dict[str, Any]) -> dict[str, Any]:
    q = query.strip()
    out: dict[str, Any] = {"query": q, "status": "ready", "changes": [], "sources": [], "clarifications": [],
                           "ignored": [], "kept": [], "focus": [], "notes": [], "warnings": []}
    if CODE_RE.search(q):
        out.update(status="unsupported", warnings=["SQL·코드 실행은 지원하지 않습니다. 크기·FPS·IP clock 변경을 질문하세요."])
        return out
    out["focus"] = [k for k, pat in FOCUS.items() if re.search(pat, q, F)]
    base_fps = float(targets.get("fps") or 0) or None
    anchors_by_id = {a["id"]: a for a in targets["anchors"]}
    clock_nodes_all = [n for n in targets["nodes"] if n["clock_supported"]]

    def add(change: dict, source: str) -> None:
        current = anchors_by_id.get(change.get("anchor_id") or "", {}).get("size")
        if change["target"] in ("output_size", "anchor_size") and current == [change["width"], change["height"]]:
            out["notes"].append(f"{change['anchor_id']}는 이미 {current[0]}x{current[1]}입니다 — 크기 조건은 넣지 않았습니다.")
            return
        if change["target"] == "fps" and base_fps and change["value"] == base_fps:
            out["notes"].append(f"FPS는 이미 {base_fps:g}입니다 — FPS 조건은 넣지 않았습니다.")
            return
        out["changes"].append(change)
        out["sources"].append(source.strip())

    def clarify(field: str, message: str, choices: list[tuple[str, dict]], source: str) -> None:
        if not choices:   # nothing in this variant can take the value: say so instead of an empty question
            ignore(source, "이 variant에는 해당 조건을 바꿀 대상이 없습니다", "다른 scenario/variant 선택")
            return
        out["clarifications"].append({"field": field, "message": message, "source": source.strip(),
                                      "choices": [{"label": label, "value": label, "change": change} for label, change in choices]})

    def ignore(text: str, reason: str, hint: str | None = None) -> None:
        out["ignored"].append({"text": text.strip(), "reason": reason, "hint": hint})

    def output_choices(choices: list[str], size: tuple[int, int] | None = None, factor: float | None = None):
        rows = []
        for anchor in choices:
            cur = anchors_by_id[anchor]["size"]
            w, h = size if size else (_even(cur[0] * factor), _even(cur[1] * factor))
            rows.append((f"{anchor} → {w}x{h}", {"target": "output_size", "anchor_id": anchor, "width": w, "height": h}))
        return rows

    streams = list(targets.get("streams") or [])
    main_stream = next((st for st in streams if st.get("primary")), streams[0] if streams else None)

    def stream_change(size: tuple[int, int], clause: str) -> bool:
        """Scenarios without size anchors (playback, call, game): change the main stream surfaces together."""
        if targets["output_targets"] or main_stream is None:
            return False
        if list(size) == main_stream["size"]:
            out["notes"].append(f"스트림은 이미 {main_stream['id']}입니다 — 크기 조건은 넣지 않았습니다.")
            return True
        add({"target": "stream_size", "stream_id": main_stream["id"], "width": size[0], "height": size[1]}, clause)
        where = ", ".join(main_stream.get("where") or []) or "design 해상도"
        out["notes"].append(f"{main_stream['id']} 스트림을 {size[0]}x{size[1]}로 변경 — 같이 바뀌는 설정: {where}")
        return True

    refresh_params = [r for r in targets.get("params") or [] if r["param"] == "refresh_hz"]
    modeled_refresh = [r for r in refresh_params if r.get("modeled")]

    for clause in _clauses(q):
        topic = next(((r, h) for pat, r, h in UNSUPPORTED_TOPICS if re.search(pat, clause, F)), None)
        sizes = list(SIZE_RE.finditer(clause))
        fps_hits = list(FPS_RE.finditer(clause))
        clocks = list(CLOCK_RE.finditer(clause))
        pct, times, half = PCT_RE.search(clause), TIMES_RE.search(clause), HALF_RE.search(clause)
        down, up = bool(DOWN_RE.search(clause)), bool(UP_RE.search(clause))
        relative = bool(pct or times or half)
        nodes = _find_nodes(clause, targets)
        clock_nodes = [n for n in nodes if n["clock_supported"]]
        produced = False

        if PRESERVE_RE.search(clause) and not (down or up or re.search(r"변경|바꾸|바꿔|\bchange\b|\bset\b", clause, F)):
            out["kept"].append(clause)
            if topic:
                ignore(clause, topic[0], topic[1])
            continue
        refresh = REFRESH_RE.search(clause)
        if refresh:
            value = float(refresh["v"] or refresh["w"])
            if not refresh_params:
                ignore(clause, "이 variant에는 주사율 설정이 없습니다")
            elif not any(r.get("modeled") for r in refresh_params):
                ignore(clause, "주사율은 현재 Timing Budget 전력 모델에 반영되지 않습니다 (DPU driver·panel은 모델 범위 밖)",
                       "Scenario에서 주사율이 다른 variant 선택")
            elif not 0 < value <= 240:
                ignore(clause, "주사율은 0보다 크고 240 Hz 이하여야 합니다")
            else:
                named = [r for r in modeled_refresh if r["node_id"] in {n["id"] for n in nodes}]
                if len(named) == 1:
                    add({"target": "node_param", "node_id": named[0]["node_id"], "param": "refresh_hz", "value": value}, clause)
                else:   # display chain refresh moves together (DPU + panel)
                    add({"target": "node_param", "param": "refresh_hz", "value": value}, clause)
                    out["notes"].append(f"주사율 {value:g} Hz를 {', '.join(r['node_id'] for r in modeled_refresh)}에 함께 적용합니다.")
            clause = REFRESH_RE.sub(" ", clause)
            if not re.search(r"\d", clause):
                continue
            sizes, fps_hits, clocks = list(SIZE_RE.finditer(clause)), list(FPS_RE.finditer(clause)), list(CLOCK_RE.finditer(clause))
        modeled = sizes or fps_hits or clocks or (relative and (CLOCK_WORD.search(clause) or FPS_WORD.search(clause) or SIZE_WORD.search(clause)))
        if topic and not modeled:
            ignore(clause, topic[0], topic[1])
            continue
        if topic:
            ignore(clause, topic[0] + " — 같은 문장에서 크기·FPS·clock만 해석했습니다", topic[1])

        # ---- size: absolute
        if sizes:
            produced = True
            values = [_size_value(m) for m in sizes]
            if SENSOR_WORD.search(clause) and (len(values) > 1 or not (RECORD_WORD.search(clause) or PREVIEW_WORD.search(clause))):
                # which size belongs to the sensor is not decidable here; never move a sensor value onto an output
                ignore(clause, "센서 입력 크기는 catalog mode로만 바꿀 수 있습니다. 출력 크기는 별도 문장으로 지정하세요.", "Sensor Explore")
                continue
            if len(set(values)) > 1 and not TRANSITION.search(clause):
                anchor, choices, _ = _output_target(clause, targets, q)
                clarify("size", "어느 크기로 바꿀지 고르세요.",
                        [row for v in values for row in output_choices([anchor] if anchor else choices, size=v)], clause)
                continue
            m = sizes[-1]
            w, h = values[-1]
            named = [a for a in targets["anchors"] if _mentions(clause, a["id"])]
            size_nodes = [n for n in nodes if n["size_supported"]]
            if named:
                if not named[0]["supported"]:
                    ignore(clause, "센서 입력 크기는 catalog mode로만 바꿀 수 있습니다", "Sensor Explore")
                    continue
                add({"target": "anchor_size", "anchor_id": named[0]["id"], "width": w, "height": h}, clause)
            elif len(size_nodes) == 1 and not (RECORD_WORD.search(clause) or PREVIEW_WORD.search(clause)):
                add({"target": "node_size", "node_id": size_nodes[0]["id"], "width": w, "height": h}, clause)
            elif stream_change((w, h), clause):
                pass
            else:
                anchor, choices, note = _output_target(clause, targets, q)
                if anchor:
                    add({"target": "output_size", "anchor_id": anchor, "width": w, "height": h}, clause)
                    if note:
                        out["notes"].append(note)
                else:
                    clarify("output_target", "어느 출력의 크기인지 고르세요.", output_choices(choices, size=(w, h)), clause)
            if m["rate"] and not fps_hits:
                add({"target": "fps", "value": float(m["rate"])}, clause)
        # ---- size: relative ("녹화 해상도 절반", "출력 크기 30% 줄이면") or direction only
        elif SIZE_WORD.search(clause) and not (CLOCK_WORD.search(clause) or FPS_WORD.search(clause)) and (relative or down or up):
            produced = True
            anchor, choices, note = _output_target(clause, targets, q)
            factor = _factor(half, pct, times, down)
            if pct and not (down or up):
                clarify("direction", f"{pct['p']}%를 줄일지 늘릴지 고르세요.",
                        [row for f in (1 - float(pct["p"]) / 100, 1 + float(pct["p"]) / 100)
                         for row in output_choices([anchor] if anchor else choices, factor=f)], clause)
            elif factor and not targets["output_targets"] and main_stream:
                cur = main_stream["size"]
                stream_change((_even(cur[0] * factor), _even(cur[1] * factor)), clause)
            elif factor:
                if anchor:
                    cur = anchors_by_id[anchor]["size"]
                    add({"target": "output_size", "anchor_id": anchor, "width": _even(cur[0] * factor), "height": _even(cur[1] * factor)}, clause)
                    out["notes"].append(f"{anchor} {cur[0]}x{cur[1]} × {factor:g} (가로·세로 각각)" + (f" · {note}" if note else ""))
                else:
                    clarify("output_target", "어느 출력의 크기인지 고르세요.", output_choices(choices, factor=factor), clause)
            else:
                outs = [anchor] if anchor else choices
                opts = []
                if not targets["output_targets"] and main_stream:
                    cur = main_stream["size"]
                    for name in ("8K", "UHD", "QHD", "FHD", "HD"):
                        sw, sh = SIZE_NAMES[name]
                        if (sw * sh < cur[0] * cur[1]) if down else (sw * sh > cur[0] * cur[1]):
                            opts.append((f"{main_stream['id']} → {name} {sw}x{sh}",
                                         {"target": "stream_size", "stream_id": main_stream["id"], "width": sw, "height": sh}))
                for a in outs:
                    cur = anchors_by_id[a]["size"]
                    for name in ("8K", "UHD", "QHD", "FHD", "HD"):
                        sw, sh = SIZE_NAMES[name]
                        if (sw * sh < cur[0] * cur[1]) if down else (sw * sh > cur[0] * cur[1]):
                            opts.append((f"{a} → {name} {sw}x{sh}", {"target": "output_size", "anchor_id": a, "width": sw, "height": sh}))
                clarify("size", "어느 크기로 바꿀지 고르세요.", opts, clause)

        # ---- FPS
        if fps_hits:
            produced = True
            values = [float(hit["a"] or hit["b"]) for hit in fps_hits]
            if len(set(values)) > 1 and not TRANSITION.search(clause):
                clarify("fps", "어느 FPS로 바꿀지 고르세요.", [(f"{_fmt(v)} fps", {"target": "fps", "value": v}) for v in values], clause)
            elif not 0 < values[-1] <= 240:
                ignore(clause, "FPS는 0보다 크고 240 이하여야 합니다")
            else:
                add({"target": "fps", "value": values[-1]}, clause)
        elif FPS_WORD.search(clause) and not CLOCK_WORD.search(clause) and (relative or down or up):
            produced = True
            factor = _factor(half, pct, times, down)
            if base_fps and factor and not (pct and not (down or up)):
                value = round(base_fps * factor, 3)
                if 0 < value <= 240:
                    add({"target": "fps", "value": value}, clause)
                    out["notes"].append(f"FPS {base_fps:g} × {factor:g} = {value:g}")
                else:
                    ignore(clause, "계산한 FPS가 0~240 범위를 벗어납니다")
            else:
                opts = [v for v in (15, 24, 30, 60, 120, 240) if base_fps is None or (v < base_fps if not up else v > base_fps)]
                clarify("fps", "몇 FPS로 바꿀지 고르세요.", [(f"{v} fps", {"target": "fps", "value": float(v)}) for v in opts], clause)

        # ---- IP clock: absolute MHz/GHz or relative (resolved by the service)
        clock_relative = bool(CLOCK_WORD.search(clause) and relative and not clocks)
        if clocks or clock_relative or (CLOCK_WORD.search(clause) and (down or up) and (clock_nodes or nodes)):
            produced = True
            if clocks:
                values = [float(c["v"]) * (1000 if c["u"].lower() == "ghz" else 1) for c in clocks]
                if len(set(values)) > 1 and not TRANSITION.search(clause):
                    pool = clock_nodes if len(clock_nodes) == 1 else (clock_nodes or clock_nodes_all)
                    clarify("clock", "어느 clock으로 바꿀지 고르세요.",
                            [(f"{n['id']} {_fmt(v)} MHz", {"target": "node_clock_mhz", "node_id": n["id"], "value": v}) for n in pool for v in values], clause)
                    continue
                if not 0 < values[-1] <= 5000:
                    ignore(clause, "clock은 0보다 크고 5000 MHz 이하여야 합니다")
                    continue
                spec: dict[str, Any] = {"value": values[-1]}
                label = f"{_fmt(values[-1])} MHz"
            elif clock_relative and not (pct and not (down or up)):
                factor = _factor(half, pct, times, down)
                spec, label = {"scale": round(factor, 4)}, f"× {factor:g}"
            else:
                steps = [float(pct["p"])] if pct else [10.0, 20.0, 30.0]
                dirs = [down] if (down or up) else [True, False]
                pool = clock_nodes or clock_nodes_all
                clarify("clock", "clock을 얼마나 바꿀지 고르세요.",
                        [(f"{n['id']} {'−' if d else '+'}{_fmt(s)}%", {"target": "node_clock_mhz", "node_id": n["id"], "scale": round(1 - s / 100 if d else 1 + s / 100, 4)})
                         for n in pool for d in dirs for s in steps], clause)
                continue
            if len(clock_nodes) == 1:
                add({"target": "node_clock_mhz", "node_id": clock_nodes[0]["id"], **spec}, clause)
            else:
                pool = clock_nodes or clock_nodes_all
                clarify("node_id", "같은 이름의 IP가 여러 개입니다. 하나를 고르세요." if clock_nodes else "clock을 바꿀 IP를 고르세요.",
                        [(f"{n['id']} {label}", {"target": "node_clock_mhz", "node_id": n["id"], **spec}) for n in pool], clause)

        if not produced and not topic:
            leftover = FILLER.sub(" ", clause)
            for pat in FOCUS.values():
                leftover = re.sub(pat, " ", leftover, flags=F)
            if SENSOR_WORD.search(clause):
                ignore(clause, "센서 mode·크기는 catalog에서 검증된 mode로만 바꿀 수 있습니다", "Sensor Explore")
            elif re.search(r"\d", leftover) or CHANGE_VERB.search(clause):
                ignore(clause, "변경할 대상과 값을 찾지 못했습니다", "예: '녹화 FHD', 'FPS 60', 'mfc clock 20% 낮추면'")

    # Plans and one-click choices must satisfy the same bounds as preview.
    from scenario_db.api.schemas.scenario_whatif import WhatIfChange

    def valid(change: dict) -> bool:
        if "scale" in change:
            return change["scale"] > 0
        try:
            WhatIfChange(**change)
        except ValueError:
            return False
        return True

    keep = []
    for i, change in enumerate(out["changes"]):
        if valid(change):
            keep.append(i)
        else:
            ignore(out["sources"][i], "계산한 조건이 허용 범위를 벗어납니다")
    out["changes"], out["sources"] = [out["changes"][i] for i in keep], [out["sources"][i] for i in keep]
    for cl in out["clarifications"]:
        cl["choices"] = [ch for ch in cl["choices"] if valid(ch["change"])]
        if not cl["choices"]:
            ignore(cl["source"], "선택할 조건이 허용 범위를 벗어납니다")
    out["clarifications"] = [cl for cl in out["clarifications"] if cl["choices"]]

    # one value per target: keep the alternatives as a choice instead of silently picking one
    keys = [(c["target"], c.get("anchor_id"), c.get("node_id"), c.get("stream_id"), c.get("param")) for c in out["changes"]]
    for key in [k for i, k in enumerate(keys) if keys.count(k) > 1 and keys.index(k) == i]:
        idx = [i for i, k in enumerate(keys) if k == key]
        clarify("duplicate", "같은 대상에 값이 여러 개입니다. 하나를 고르세요.",
                [(out["sources"][i], out["changes"][i]) for i in idx], " / ".join(out["sources"][i] for i in idx))
        keep = [i for i in range(len(out["changes"])) if i not in idx]
        out["changes"], out["sources"] = [out["changes"][i] for i in keep], [out["sources"][i] for i in keep]
        keys = [keys[i] for i in keep]
    if len(out["changes"]) > 8:
        out["changes"], out["sources"] = out["changes"][:8], out["sources"][:8]
        out["warnings"].append("조건은 최대 8개까지 계산합니다. 앞의 8개만 사용했습니다.")

    if out["clarifications"]:
        out["status"] = "clarification"
    elif not out["changes"] and out["notes"] and not out["ignored"]:
        out["status"] = "no_change"
    elif not out["changes"]:
        out["status"] = "unsupported"
        if not out["ignored"]:
            out["warnings"].append("변경할 조건을 찾지 못했습니다. 예: '녹화를 FHD로 바꾸면 전력은?', 'FPS 절반', 'mfc clock 20% 낮추면 timing은?'")
    elif out["ignored"]:
        out["status"] = "partial"
    return out
