"""Noncamera review guidance; explicit DB conditions remain authoritative."""
from __future__ import annotations

from typing import Any

from dashboard.components.camera_review import is_camera

Item = dict[str, Any]

PROJECT_CONTEXT = (
    "M1S = Galaxy26, M2S = GalaxyS26+ · 기본 모델과 Plus 모델 모두 Exynos2600을 사용합니다. "
    "시나리오의 세부 하드웨어 구성과 동작 조건은 선택한 과제 기준으로 표시됩니다."
)

CATEGORY_GUIDES = {
    "video_playback": {
        "title": "영상 재생 · Local / YouTube",
        "purpose": "압축 영상을 읽고 디코딩한 뒤 화면에 표시하는 지속 부하를 검토합니다. 원본 해상도·fps·코덱과 패널 출력 조건을 분리해서 비교하세요.",
        "flow": "로컬 파일은 UFS → 메모리 → MFC 또는 APV, 스트리밍은 Network / CPU demux → MFC가 검토 경로입니다. 디코딩 결과는 DPU로 직접 전달하거나 GPU 합성 / MSCL 변환을 거쳐 패널로 나갑니다. 실제 활성 경로는 선택 variant의 Pipeline Viewer에서 확인하세요.",
        "review": "동일 해상도·fps에서 코덱과 bit depth를 먼저 비교하고, HDR·PiP·DRM·합성 경로를 하나씩 바꿔 봅니다. 압축 비트스트림 bitrate와 복원된 영상 surface 대역폭은 서로 다릅니다. 영상 30 fps와 패널 60 Hz도 별도 조건입니다. 버퍼링·네트워크 지연, 프레임 드롭, 지속 발열은 실측 증거와 함께 검토하세요.",
        "driver": "UFS는 bitrate 기반 I/O, DPU는 surface read와 BTS 요청, MSCL은 변환에 필요한 읽기·쓰기를 설명합니다. MFC/APV의 커널 선언이나 모드 등록만으로 실행 가능한 BW·전력 모델이 확보되는 것은 아닙니다. 현재 noncamera-driver-v1의 코덱 계산 범위에는 MFC/APV가 포함되지 않습니다.",
    },
    "display": {
        "title": "디스플레이 · Gallery / Composition",
        "purpose": "이미지와 UI 레이어를 패널에 합성·출력하는 비용을 검토합니다. 정지 이미지라도 패널 갱신과 레이어 읽기 조건을 별도로 확인해야 합니다.",
        "flow": "등록된 이미지 / UI surface → DPU(DECON / DPP) → 패널이 기본 검토 경로입니다. 포맷·블렌딩·스케일 조건에 따라 GPU 사전 합성 또는 MSCL 색공간 / 크기 변환이 추가될 수 있습니다.",
        "review": "원본 크기와 패널 크기, 레이어 수, layer별 포맷과 bpp, 스케일·회전·압축, HDR transfer와 metadata를 함께 봅니다. DPU_DIRECT / GPU / M2M 경로가 바뀌면 중간 surface와 메모리 왕복도 달라집니다. 레이어 수만으로 실제 fallback이나 성능을 단정하지 말고 등록된 구성과 드라이버 제약을 대조하세요.",
        "driver": "DPU의 BTS vote는 자원 확보 요청이며 실제 DRAM traffic과 다릅니다. 60 Hz vote floor 때문에 30/60 Hz의 요청값이 같아도 surface traffic은 달라질 수 있습니다. v1 계산은 비회전·비압축 레이어를 대상으로 하며 RCD, bus/customer overhead, writeback을 포함하지 않습니다. DSC slice count 등 가정 입력을 실측 사실로 읽지 마세요.",
    },
    "game": {
        "title": "게임 · Local rendering / Cloud streaming",
        "purpose": "단말이 직접 렌더링하는 게임과 원격 렌더링 영상을 수신하는 게임의 병목을 구분합니다. target_fps는 목표이며 달성된 실측 fps가 아닙니다.",
        "flow": "로컬 게임은 CPU 게임 로직 → GPU 렌더링 → 필요 시 MSCL → DPU / 패널, 스트리밍 게임은 Network / demux → MFC 디코딩 → 합성 / DPU 경로를 검토합니다. NPU는 사용 조건과 활성 노드가 명시된 경우에만 포함합니다.",
        "review": "render_resolution, source_resolution, panel_resolution을 분리하고 target_fps / decode fps / panel Hz를 비교합니다. governor, HDR, UI 레이어, 업스케일링 유무가 부하를 바꿉니다. 스트리밍은 입력→서버→전송→디코딩→표시의 전체 지연을 봐야 하며 low_latency_mode 플래그 하나로 지연 목표 통과를 판단할 수 없습니다.",
        "driver": "DPU·MSCL 모델은 표시 및 변환 경로를 설명하지만 GPU shader / texture / cache traffic이나 NPU 연산량을 대신하지 않습니다. GPU/NPU BW는 커널 선언만으로 산출되지 않으며 v1 계산 범위 밖입니다. GPU 사용률·frame time·발열은 실제 workload 측정으로 보완하세요.",
    },
    "audio": {
        "title": "오디오 · 재생 / Streaming / Offload",
        "purpose": "CPU 디코딩과 ABOX(AUDSP) offload, speaker와 Bluetooth, 화면 켜짐·꺼짐 조건을 비교합니다. 작은 대역폭이라도 지속 동작과 저전력 상태 진입에 영향을 줄 수 있습니다.",
        "flow": "로컬 파일은 UFS, 스트리밍은 Network에서 시작해 CPU decoder 또는 DSP offload → ABOX 재생 경로 → 출력 장치로 이어집니다. 캡처는 별도 WDMA 경로입니다. 논리 endpoint 여러 개를 모두 독립 스트림으로 더하지 마세요.",
        "review": "압축 bitrate와 PCM sample rate × channels × bytes/sample × stream count를 분리합니다. sample bit depth와 실제 메모리 저장 폭도 다를 수 있습니다. offload 여부, screen_on, output / codec_bt, AUD 동작점을 대조하고 buffer underrun·wakeup·화면 꺼짐 전력을 측정하세요. 누락된 채널 수나 sample rate를 이름으로 채우지 않습니다.",
        "driver": "ABOX의 구성과 AUD QoS 단계는 s5e9965-audio.dtsi / devfreq.dtsi에 근거합니다. offload PCM 요구량과 실제 SRAM refill의 MIF traffic은 같지 않으며 후자는 미확인으로 남습니다. AUD clock 선택 검증은 전력 산출이 아닙니다. 전력 계수가 없으면 uncalibrated / null로 읽습니다.",
    },
    "voice_call": {
        "title": "통화 · Voice / Video call",
        "purpose": "음성 송수신의 연속 동작과 영상 통화의 동시 카메라·인코딩·디코딩·표시를 구분합니다. 통화 종류와 카메라 활성 여부를 먼저 확인하세요.",
        "flow": "음성은 modem / network와 ABOX 재생·캡처 경로를, 영상은 Sensor / ISP / MCSC → MFC encode → Network와 수신 decode → DPU를 함께 검토합니다. 양방향 경로가 어떤 버퍼와 자원을 공유하는지 Pipeline Viewer에서 확인하세요.",
        "review": "call_type, camera_active, sensor_place, resolution / fps와 VT DVFS 시나리오를 비교합니다. 음성 지연, A/V sync, 동시 encode/decode의 자원 경합, 지속 발열이 검토 항목입니다. 음성 통화에 VT 식별자가 있어도 camera_active=false이면 카메라 실행 근거로 해석하지 않습니다.",
        "driver": "ABOX의 PCM / AUD 모델로 오디오 endpoint를 검토할 수 있지만 modem RF 전력과 네트워크 지연은 이 계산 범위가 아닙니다. fixture에서 modem/network가 CPU IP로 표현돼 있어도 실제 modem HW가 모델링됐다는 뜻은 아닙니다. 영상 통화의 누락된 bitrate·패널·음성 조건은 별도 확인이 필요합니다.",
    },
    "video": {
        "title": "Video · 재생과 영상 통화",
        "purpose": "Video는 영상 재생과 영상 통화를 함께 포함하는 분류입니다. 재생은 decode / 표시, 통화는 카메라 송신과 수신의 동시 처리라는 차이가 있습니다.",
        "flow": "선택한 시나리오가 Local / YouTube인지 Video Call인지 먼저 확인하고, 압축 입력 → decode → display 또는 capture → encode → network 경로를 구분하세요.",
        "review": "공통으로 해상도·fps·코덱과 출력 조건을 확인하되 통화의 왕복 지연과 재생의 버퍼링을 같은 KPI로 비교하지 않습니다. 아래 시나리오별 상세 안내를 기준으로 조건을 선택하세요.",
        "driver": "영상 분류에 속한다는 이유만으로 UFS·ABOX·MSCL·DPU가 모두 활성화되지는 않습니다. 실제 variant의 활성 노드와 Driver Models 보고서에서 계산 지원 여부를 확인하세요.",
    },
}

SCENARIO_PURPOSES = {
    "uc-video-playback-local": "로컬 영상 재생: UFS 파일 입력과 MFC/APV 디코딩을 분리해 봅니다. DRM, PiP, HDR, APV chroma format에 따라 복호화·합성·포맷 변환 경로가 달라질 수 있습니다.",
    "uc-youtube-playback": "YouTube 재생: 네트워크 수신·demux·MFC 디코딩·화면 합성을 검토합니다. 등록된 codec/bitrate는 검토 조건이며 실제 서비스의 적응형 화질 선택이나 네트워크 성능을 보장하지 않습니다.",
    "uc-gallery-display": "갤러리 표시: 이미지 크기, 색공간, HDR, 레이어와 합성 경로를 비교합니다. 갤러리라는 이름만으로 JPEG 디코더나 모든 UI 동작이 모델링됐다고 가정하지 않습니다.",
    "uc-game-play": "로컬 게임: CPU/GPU 렌더링과 패널 출력 사이의 frame pacing, 해상도 및 목표 fps를 검토합니다. NPU 사용 여부와 render_resolution은 명시된 조건으로만 판단합니다.",
    "uc-game-streaming": "게임 스트리밍: 원격 렌더링 영상의 수신·decode·표시가 중심입니다. 로컬 게임의 GPU 부하와 구분하고 bitrate, low latency 설정, 디코딩 fps와 패널 Hz를 대조합니다.",
    "uc-audio-mp3-playback": "로컬 오디오 재생: UFS 파일 읽기, CPU decode와 DSP offload, speaker/Bluetooth 출력을 비교합니다. 시나리오 이름보다 variant의 실제 format과 offload 조건을 우선하세요.",
    "uc-audio-streaming": "오디오 스트리밍: 네트워크 입력과 압축 오디오 decode, ABOX 출력을 검토합니다. 화면 상태와 출력 장치별 지속 동작을 비교하며 네트워크 비용을 PCM BW로 대체하지 않습니다.",
    "uc-voice-call": "음성 통화: call_type별 송수신 오디오와 ABOX 경로를 비교합니다. camera_active=false와 함께 등록된 VT flag는 카메라 부하를 증명하지 않으며 modem RF는 별도 검토 대상입니다.",
    "uc-video-call": "영상 통화: 전면/후면 Sensor 입력, 인코딩 송신과 디코딩 수신이 동시에 진행되는 조건입니다. VT DVFS 값과 해상도·fps를 대조하고 음성·네트워크·패널 조건의 누락을 확인하세요.",
}

# Descriptions explain stored values, never supply absent defaults.
CONDITION_HELP = {
    "resolution": "콘텐츠의 등록 해상도입니다. 패널 해상도와 구분합니다.",
    "source_resolution": "입력 surface 크기입니다. 변환 / 스케일 비용의 출발점입니다.",
    "render_resolution": "GPU가 렌더링하는 크기입니다. 출력 크기와 다르면 스케일 경로를 확인합니다.",
    "panel_resolution": "이 variant의 패널 출력 조건입니다. 다른 과제의 패널 사양으로 일반화하지 않습니다.",
    "fps": "콘텐츠 처리 fps입니다. 패널 Hz나 실측 달성 fps와 다를 수 있습니다.",
    "target_fps": "렌더링 목표 fps입니다. 실측 결과가 아닙니다.",
    "panel_fps_hz": "패널 갱신 주파수(Hz)입니다. 콘텐츠 처리 fps와 별도로 비교합니다.",
    "codec_mfc": "등록된 MFC 코덱 / 방향입니다. 코덱별 BW 계산 지원을 뜻하지 않습니다.",
    "codec_apv": "등록된 APV 모드입니다. MFC와 경로 및 출력 포맷을 분리해서 봅니다.",
    "apv_chroma_format": "APV chroma sampling 조건입니다. 출력 surface 크기와 DPU 입력 호환성을 확인합니다.",
    "apv_chroma_format_idc": "APV chroma 형식 식별자입니다. format 표기 및 활성 변환 경로와 대조합니다.",
    "bit_depth": "성분당 bit depth입니다. 실제 surface의 저장 bpp와 동일하지 않을 수 있습니다.",
    "bitrate_mbps": "압축 데이터 Mbps입니다. UFS 입력 계산은 Mbps × 1,000,000 / 8 bytes/s입니다.",
    "bitrate_kbps": "압축 오디오 kbps입니다. 복원된 PCM 대역폭과 구분합니다.",
    "bitrate_value_source": "bitrate의 출처입니다. assumed는 계산 입력 가정이며 측정치가 아닙니다.",
    "hdr": "콘텐츠 HDR 조건입니다. bit depth, transfer 및 metadata와 함께 읽습니다.",
    "hdr_dpu": "DPU HDR 처리 조건입니다. 콘텐츠 HDR과 표시 경로의 일치를 확인합니다.",
    "dynamic_metadata": "동적 HDR metadata 조건입니다. metadata 등록만으로 출력 품질 검증을 대신하지 않습니다.",
    "transfer": "전달 함수 조건입니다. 입력 색공간과 출력 HDR 설정을 함께 봅니다.",
    "color_mode": "화면 색 모드입니다. surface format이나 bit depth와 구분합니다.",
    "dpu_layer_count": "등록 레이어 수입니다. GPU / MSCL 사전 합성 후의 실제 DPU 입력과 대조합니다.",
    "dpu_composer": "직접 합성 / GPU / M2M 경로 선택입니다. 중간 버퍼와 메모리 왕복을 확인합니다.",
    "input_format": "입력 포맷입니다. DPP 지원 및 포맷 변환 필요성을 확인합니다.",
    "blend_mode": "레이어 혼합 방식입니다. DPP 지원 여부와 GPU fallback 조건을 확인합니다.",
    "drm_protected": "보호 콘텐츠 조건입니다. 복호화 및 secure 경로를 별도로 확인합니다.",
    "pip_active": "Picture-in-Picture 조건입니다. 추가 stream / layer 활성 상태를 확인합니다.",
    "screen_on": "화면 켜짐 조건입니다. false만으로 다른 모든 IP가 꺼졌다고 판단하지 않습니다.",
    "audio": "오디오 동반 처리 조건입니다. ABOX 경로 및 stream 입력이 실제 등록됐는지 확인합니다.",
    "format": "오디오 등 콘텐츠 형식입니다. 시나리오 이름보다 이 등록값이 우선입니다.",
    "offload": "DSP offload 조건입니다. CPU decode와 SRAM refill 경로를 구분합니다.",
    "output": "speaker / Bluetooth 등 출력 장치입니다. 출력 경로와 지속 전력을 함께 봅니다.",
    "codec_bt": "Bluetooth 코덱 조건입니다. PCM 처리와 무선 전송 비용은 별개입니다.",
    "sample_rate_khz": "오디오 sample rate(kHz)입니다. PCM 계산 시 Hz로 변환하고 채널·저장 폭·stream 수를 확인합니다.",
    "gpu_governor": "등록된 GPU 정책입니다. 실제 clock이나 성능 달성 여부를 나타내지는 않습니다.",
    "npu_used": "NPU 사용 선언입니다. 실제 활성 노드와 모델·측정 근거를 확인합니다.",
    "low_latency_mode": "저지연 모드 설정입니다. 전체 end-to-end 지연의 실측값이 아닙니다.",
    "call_type": "통화 종류입니다. modem / network와 양방향 오디오 조건을 확인합니다.",
    "camera_active": "카메라 활성 선언입니다. VT flag의 존재만으로 이 값을 뒤집어 해석하지 않습니다.",
    "dvfs_sn": "카메라 DVFS 시나리오 식별자입니다. 실제 clock·전력 값이 아닙니다.",
    "sensor_place": "전면 / 후면 센서 위치입니다. 선택 과제의 센서 구성과 대조합니다.",
    "sensor_scenario": "센서 동작 시나리오입니다. 구체적인 mode / timing은 별도 근거가 필요합니다.",
    "extend_mode": "추가 동작 모드입니다. 해당 variant의 topology와 조건을 함께 확인합니다.",
    "mfc_format_flag": "MFC 포맷 flag입니다. bit depth와 메모리 포맷의 대응을 확인합니다.",
    "sw_timing_source": "SW 시간의 근거입니다. assumed이면 실측 latency로 해석하지 않습니다.",
    "design_review": "작성자가 남긴 설계 검토 사항입니다. 등록만으로 검토가 완료되지는 않습니다.",
    "note": "작성자의 조건 / 한계 메모입니다. 다른 필드와 함께 읽습니다.",
}

DRIVER_REFERENCE = """
**Exynos2600 / S5E9965 드라이버 보강 근거와 계산 범위**

저장소의 IP fixture에 기록된 드라이버 검토 출처입니다. 현재 기기에서 측정한 결과가 아닙니다.

| IP | 기록된 커널 근거 | 해석과 계산 한계 |
| --- | --- | --- |
| UFS | `s5e9965-ufs.dtsi` | storage를 CPU와 분리. bitrate 기반 bytes/s이며 UFS→DRAM 쓰기와 consumer 읽기의 소유권을 구분합니다. clock / 전력 계수는 미확인입니다. |
| ABOX | `s5e9965-audio.dtsi`, `s5e9965-devfreq.dtsi` | audio를 CPU와 분리. PCM 요구량과 AUD QoS 선택 검증을 지원하며 offload SRAM refill traffic과 절대 전력은 미확인입니다. |
| MSCL | `s5e9965-scaler.dtsi` | M2M 변환을 CPU와 분리. source / destination 크기·bpp·fps·PPC·회전·압축·vOTF 조건을 사용합니다. MIF reference BW scaling은 단위 검증 전까지 보류합니다. |
| DPU | `exynos/soc-series/common/drivers/dpu/exynos_drm_bts.c`의 `__get_bts_margin`, `__get_resol_clock_internal`, `dpu_bts_calc_dpp_bw` | surface traffic, BTS vote, DISP clock을 구분합니다. v1은 비회전·비압축 레이어 범위이며 GPU 사전 합성 traffic을 대신 계산하지 않습니다. |

DTS 경로의 기준 디렉터리는 `exynos/soc-series/t-android16/arch/arm64/boot/dts/exynos/`입니다.
검토 원본 정보는 `db_fixtures_Exynos2600_S26Plus/00_hw/`의 각 IP YAML,
현재 계산 계약은 `docs/guides/driver-models.md`에서 확인합니다.

**결과 읽기:** `calculated`는 입력 가정에 따른 계산, `missing_input`은 입력 부족,
`infeasible`은 제공된 QoS 단계로 요구량을 만족하지 못함을 뜻합니다.
`power_mw: null` / `uncalibrated`는 전력 미확인이며 0 mW가 아닙니다.
MFC/APV/GPU/NPU는 이 v1 계산 범위 밖입니다.

**단위와 합산:** 기준은 bytes/s입니다. UFS의 KB/s는 1000, audio/scaler의 원본 KB/s는
1024 기준(KiB/s)이며 DPU BTS는 kHz 기반 kB/s 요청입니다.
endpoint 보고서를 기존 DMA / 전력 총합에 그대로 더하면 중복될 수 있습니다.
Driver Models 페이지에서 선택 scenario / variant의 입력·출처·상태를 확인하세요.
"""


def guide_keys(item: Item) -> list[str]:
    if is_camera(item):
        return []
    labels = item.get("category") or []
    if isinstance(labels, str):
        labels = [labels]
    keys = list(dict.fromkeys(str(label).lower() for label in labels if str(label).lower() in CATEGORY_GUIDES))
    # Video is an umbrella; prefer the more specific registered category.
    return [key for key in keys if key != "video"] if len(keys) > 1 else keys


def is_exynos2600(item: Item) -> bool:
    return str(item.get("soc_ref") or "").lower() == "soc-exynos2600"


def scenario_purpose(item: Item) -> str:
    keys = guide_keys(item)
    if not keys:
        return ""
    if is_exynos2600(item) and item.get("scenario_id") in SCENARIO_PURPOSES:
        return SCENARIO_PURPOSES[str(item["scenario_id"])]
    return " ".join(CATEGORY_GUIDES[key]["purpose"] for key in keys)


def condition_rows(item: Item) -> list[dict[str, str]]:
    return [
        {"조건": key, "등록값": str(value), "해설": CONDITION_HELP.get(key, "추가 등록 조건입니다. 원본 정의와 Pipeline Viewer에서 의미를 확인하세요.")}
        for key, value in (item.get("design_conditions") or {}).items()
    ]
