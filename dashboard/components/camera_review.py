"""Camera review guidance derived from the filtered Explorer response.

These are review lenses, never severity scores or hardware feasibility verdicts.
Keep explicit design conditions authoritative; IDs must not supply missing KPIs.
"""
from __future__ import annotations

import math
import re
from typing import Any

Item = dict[str, Any]
BASIC_KPIS = ("FHD30", "FHD60", "UHD30", "UHD60", "8K30")
SLOW_KPIS = ("FHD120", "FHD240", "UHD120")
REVIEW_GROUPS = {
    "recording": {
        "title": "Video recording · 기본 KPI",
        "why": "일상 녹화 품질과 지속 성능의 기준점입니다. FHD30부터 해상도와 fps를 높여 비교합니다.",
        "focus": "Sensor / ISP 처리량 · 메모리 대역폭 · 인코더 · 지속 기록 / 발열",
        "badge": "기본 검토",
    },
    "slow": {
        "title": "Slow motion · 고속 촬영",
        "why": "FHD120 / FHD240 / UHD120에서 짧아진 프레임 처리 시간과 HW 처리 한계를 검토합니다.",
        "focus": "Sensor 입력 fps · ISP 처리 시간 · 메모리 대역폭 · 프레임 누락",
        "badge": "HW 부하",
    },
    "portrait": {
        "title": "Portrait video · 인물 동영상",
        "why": "인물 분리와 배경 흐림 처리가 녹화와 동시에 실행됩니다. 솔루션 연산 비용을 비교합니다.",
        "focus": "분할 / 합성 지연 · GPU / NPU / VPS / CPU 실제 배치 · 메모리 왕복",
        "badge": "솔루션 부하",
    },
    "dual": {
        "title": "Dual recording · 동시 녹화",
        "why": "두 카메라 입력이 자원을 공유합니다. 단일 녹화 대비 동기화와 합성 비용을 검토합니다.",
        "focus": "동시 Sensor 경로 · 공유 ISP / 메모리 · PIP 합성 · 인코더 스트림",
        "badge": "동시 처리",
    },
    "pro": {
        "title": "Pro video · 수동 제어 / 분석 UI",
        "why": "Histogram 분포 표시와 수동 제어 UI가 녹화 중에도 갱신됩니다. CPU 작업과 UI 응답성을 검토합니다.",
        "focus": "CPU 통계 / 제어 작업 · Histogram 갱신 주기 · UI 합성 · 프레임 지연",
        "badge": "CPU / UI 부하",
    },
    "other": {
        "title": "기타 Camera · Preview / Capture / 확장 모드",
        "why": "미리보기, 정지 촬영, 추가 녹화 조건과 분류가 불명확한 항목을 확인합니다.",
        "focus": "사용 목적 · 누락된 조건 · 개별 파이프라인",
        "badge": "추가 검토",
    },
}
SEVERITY_LABELS = {
    "light": "낮은 부하 등급",
    "medium": "중간 부하 등급",
    "heavy": "높은 부하 등급",
    "critical": "최고 부하 등급",
}
SEVERITY_EXPLANATION = (
    "Severity는 시나리오 작성자가 variant에 저장한 부하 등급입니다. "
    "공통 수치 임계값이나 자동 산정식은 제공되지 않습니다. "
    "light → medium → heavy → critical 순으로 읽되, 과제와 조건을 함께 비교하세요. "
    "오류 심각도, 실측 사용률 또는 KPI 통과 여부를 뜻하지 않습니다. "
    "아래 부하 요인은 등록 조건의 해설이며 등급을 산정한 공식 근거는 아닙니다."
)


def is_camera(item: Item) -> bool:
    labels = [*(item.get("category") or []), *(item.get("domain") or [])]
    return "camera" in {str(label).lower() for label in labels}


def scenario_intro(item: Item) -> str:
    if not is_camera(item):
        return ""
    name = f"{item.get('scenario_id', '')} {item.get('scenario_name', '')}".lower()
    if "preview" in name:
        return "미리보기 · 촬영 전 화면 응답성과 상시 Sensor / ISP / 화면 표시 부하를 확인합니다."
    if "capture" in name:
        return "정지 촬영 · 셔터 응답, 고해상도 처리와 연속 촬영의 순간 부하를 확인합니다."
    if "recording" in name or "video" in name:
        return "동영상 녹화 · 기본 KPI와 고속 / 인물 / 동시 녹화의 지속 성능을 비교합니다."
    return "카메라 동작의 조건과 파이프라인을 확인하고 과제의 검토 목적에 맞는 variant를 선택하세요."


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def enabled(value: Any) -> bool:
    return value is not None and str(value).strip().lower() not in {
        "", "false", "0", "none", "off", "no", "disabled", "sdr",
    }


def kpi_label(item: Item) -> str:
    design = item.get("design_conditions") or {}
    resolution = str(design.get("resolution") or "").upper().replace(" ", "")
    resolution = {"1920X1080": "FHD", "3840X2160": "UHD", "4K": "UHD", "7680X4320": "8K"}.get(resolution, resolution)
    fps = number(design.get("fps"))
    if not resolution or fps is None:
        return "KPI 조건 미상"
    return f"{resolution}{fps:g}"


def review_groups(item: Item) -> tuple[str, ...]:
    if not is_camera(item):
        return ()
    design = item.get("design_conditions") or {}
    # Mode names can help navigation, but may never turn missing conditions into a KPI.
    mode = " ".join(str(design.get(key) or "") for key in (
        "camera_mode", "subscenario", "sensor_mode", "is_scenario",
    )).lower()
    identity = " ".join(str(item.get(key) or "") for key in (
        "scenario_id", "scenario_name", "variant_id",
    )).lower()
    # Shared PRO_VIDEO driver flags also occur in still capture and preview.
    # The scenario purpose takes precedence over those reusable mode constants.
    if re.search(r"\b(capture|preview)\b", re.sub(r"[-_]+", " ", identity)):
        return ("other",)
    text = re.sub(r"[-_]+", " ", mode + " " + identity)
    recording = bool(re.search(r"\b(recording|rec|video)\b", text))
    if not recording:
        return ("other",)
    groups = []
    if enabled(design.get("portrait")) or re.search(r"\b(portrait|bokeh)\b", text):
        groups.append("portrait")
    if re.search(r"\b(dual|rdual|pip|rcv)\b", text):
        groups.append("dual")
    if enabled(design.get("pro_video")) or re.search(r"\bpro (video|mode)\b", text) or any(
        enabled(design.get(key)) for key in ("histogram", "histogram_enabled", "focus_peaking")
    ):
        groups.append("pro")
    fps = number(design.get("fps"))
    if (fps is not None and fps >= 120) or re.search(r"\b(slow motion|slowmo|high speed)\b", text):
        groups.append("slow")
    if groups:
        return tuple(groups)
    if re.search(r"\b(triple|rtriple|3rd|iq eval)\b", text):
        return ("other",)
    return ("recording",)


def scenario_variants(scenario: Item, items: list[Item]) -> list[Item]:
    return [item for item in items if (
        item.get("project_id"), item.get("scenario_id")
    ) == (scenario.get("project_id"), scenario.get("scenario_id"))]


def coverage(items: list[Item], group: str, kpis: tuple[str, ...]) -> dict[str, int]:
    return {kpi: sum(group in review_groups(item) and kpi_label(item) == kpi for item in items) for kpi in kpis}


def review_sort_key(item: Item) -> tuple[Any, ...]:
    groups = review_groups(item)
    rank = min((list(REVIEW_GROUPS).index(group) for group in groups), default=99)
    kpi = kpi_label(item)
    kpis = BASIC_KPIS + SLOW_KPIS
    return (rank, kpis.index(kpi) if kpi in kpis else 99, str(item.get("project_id")), str(item.get("scenario_id")), str(item.get("variant_id")))


def workload_factors(item: Item) -> list[tuple[str, str]]:
    """Explain observed conditions without claiming to reproduce stored severity."""
    design = item.get("design_conditions") or {}
    groups = review_groups(item)
    factors: list[tuple[str, str]] = []
    kpi = kpi_label(item)
    if kpi != "KPI 조건 미상":
        factors.append(("출력 KPI", f"{kpi} · 해상도와 fps를 함께 보고 ISP / 인코더 처리량을 비교합니다."))
    else:
        factors.append(("조건 확인", "resolution 또는 fps가 없어 KPI 커버리지에 포함하지 않았습니다."))
    fps = number(design.get("fps"))
    if fps:
        factors.append(("프레임 간격", f"{1000 / fps:.2f} ms @ {fps:g} fps · 목표 fps의 간격이며 실측 처리 시간이 아닙니다."))
    sensor_fps = number(design.get("sensor_input_fps"))
    if sensor_fps and fps and sensor_fps != fps:
        factors.append(("입력 / 출력 차이", f"Sensor {sensor_fps:g} fps / 목표 {fps:g} fps · 센서 모드와 프레임 생성 / 누락 정책 확인이 필요합니다."))
    if "slow" in groups:
        factors.append(("HW", "고속 입력의 Sensor / ISP 처리 시간과 메모리 대역폭을 확인하세요."))
    if "portrait" in groups:
        source = design.get("portrait_hw_source")
        factors.append(("솔루션", f"등록된 처리 가정: {source}" if source else "인물 분할 / 배경 합성의 실제 GPU / NPU / VPS / CPU 배치를 Viewer에서 확인하세요."))
    if "dual" in groups:
        factors.append(("동시 처리", "복수 입력의 동기화, 공유 자원과 합성 비용을 확인하세요."))
    if "pro" in groups:
        if not any(enabled(design.get(key)) for key in ("histogram", "histogram_enabled")):
            factors.append(("Histogram 조건", "Pro 모드는 분류되지만 Histogram 활성화 / 갱신 주기는 등록 조건에서 확인되지 않습니다."))
        factors.append(("CPU / UI", "Histogram / 분석 UI 갱신과 녹화 제어의 CPU 시간, 프레임 지연을 확인하세요."))
    for key, label in (("hdr", "HDR"), ("stabilization", "손떨림 보정"), ("npu_used", "NPU"), ("gpu_ui", "GPU UI")):
        if enabled(design.get(key)):
            factors.append((label, f"{key}={design[key]} · 해당 기능의 추가 처리 비용을 비교하세요."))
    if design.get("record_bitrate_mbps"):
        factors.append(("저장", f"목표 {design['record_bitrate_mbps']} Mbps · 지속 쓰기 성능과 저장 모델 가정을 확인하세요."))
    return factors


def evidence_notes(item: Item) -> list[str]:
    design = item.get("design_conditions") or {}
    tags = {str(tag).lower() for tag in item.get("tags") or []}
    notes = []
    if "assumed-sw-timing" in tags or design.get("sw_timing_source") == "assumed":
        notes.append("SW 시간: 가정값")
    if "uncalibrated-power" in tags:
        notes.append("전력: 미보정")
    if "exploration-only" in tags:
        notes.append("탐색용 조건")
    if "requires-multi-sensor-routing-verification" in tags:
        notes.append("다중 센서 경로 확인 필요")
    if enabled(design.get("sensor_runtime_confirmation")):
        notes.append("Sensor 런타임 확인 필요")
    return notes
