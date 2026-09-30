"""Structured per-variant failure records for fleet / exploration runs.

A run over many variants keeps going when one variant fails; the failure is
reported with enough detail to act on it without re-running with a debugger:
the pipeline stage, the exception type, the full message, the code location
that raised it, a coarse category and a hint.
"""
from __future__ import annotations

import traceback
from typing import Any

_MESSAGE_LIMIT = 4000

# (category, substrings, hint) — first match wins; matched on the lower-cased message.
_RULES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("sw_stage_budget", ("included hardware needs positive ppc",),
     "SW task의 sw_timing.includes_hw_nodes에 포함된 HW의 sim.ppc 또는 해당 statistic(min/mean/max)의 "
     "time budget(ms)이 0/누락입니다. IP catalog sim block과 variant sw_timing을 확인하세요."),
    ("sw_timing", ("min_ms <= mean_ms", "timing must satisfy", "unknown timeline task", "not a sw task",
                   "ip_overhead target"),
     "variant sw_timing(min/mean/max ms)이 min ≤ mean ≤ max를 만족하지 않거나, task_latency/ip_overhead "
     "옵션이 없는 task를 가리킵니다. 실측 import 후 sw_timing 값과 task id를 확인하세요."),
    ("buffer", ("comp_ratio", "history requires", "compression ratio"),
     "buffer compression(comp_ratio 숫자/0~1) 또는 history buffer(frame_offset=-1) 정의를 확인하세요."),
    ("sensor", ("sensor", "readout", "vvalid", "v_valid", "mipi"),
     "sensor mode 선택/DT binding/readout timing을 확인하세요 (selected_mode, sensor catalog)."),
    ("dvfs", ("dvfs", "asv"),
     "DVFS table 연결(dvfs_table_ref / soc_ref)과 domain 이름(dvfs_group)을 확인하세요."),
    ("power_params", ("power_model_params", "power params", "ip_model"),
     "power_model_params 문서의 soc_ref/version/ip_model을 확인하세요."),
    ("measured_profile", ("timing profile", "measured replay", "baseline"),
     "measured timing profile의 baseline이 바뀌었거나 fps/sensor exploration과 충돌합니다."),
    ("shape", ("shape", "size_ref", "width", "height", "resolution"),
     "buffer size_ref / size_overrides / node sim width·height 정의를 확인하세요."),
    ("scope_limit", ("exceeds", "too many", "limit"),
     "탐색 범위(case 수, variant 수)가 상한을 넘었습니다. 축을 줄이거나 scope를 나누세요."),
    ("reference", ("not found", "unknown", "no such", "missing"),
     "DB에 없는 id를 참조합니다(ip_ref, sw profile, DVFS, evidence). ETL 적재 여부를 확인하세요."),
)


def variant_failure(
    exc: BaseException,
    *,
    variant_id: str,
    scenario_id: str | None = None,
    stage: str,
) -> dict[str, Any]:
    """One failure row: stage, type, full message, raising location, category, hint."""
    message = str(exc) or exc.__class__.__name__
    lowered = message.lower()
    category, hint = "other", None
    if not isinstance(exc, (LookupError, ValueError)):
        category = "internal"
        hint = "입력 검증에서 걸러지지 않은 예외입니다(코드 결함 가능). location과 message를 첨부해 보고해 주세요."
    else:
        for name, needles, rule_hint in _RULES:
            if any(needle in lowered for needle in needles):
                category, hint = name, rule_hint
                break
    frames = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
    location = None
    if frames:
        last = frames[-1]
        path = last.filename.replace("\\", "/")
        short = path.split("/src/", 1)[-1] if "/src/" in path else path.rsplit("/", 1)[-1]
        location = f"{short}:{last.lineno} ({last.name})"
    row: dict[str, Any] = {
        "variant_id": variant_id,
        "stage": stage,
        "error_type": exc.__class__.__name__,
        "category": category,
        "error": message[:_MESSAGE_LIMIT],
        "location": location,
        "hint": hint,
    }
    if scenario_id is not None:
        row = {"scenario_id": scenario_id, **row}
    return row
