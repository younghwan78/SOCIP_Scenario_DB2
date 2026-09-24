// Scenario descriptions (ported from dashboard/components/category_review.py and
// camera_review.py). Review lenses only — never severity or feasibility verdicts.
import { recordingMode, type Mode } from './conditions'
import type { VariantRow } from './api'

export const SCENARIO_PURPOSES: Record<string, string> = {
  'uc-camera-recording': '동영상 녹화 · 기본 KPI와 고속 / 인물 / 동시 녹화의 지속 성능을 비교합니다.',
  'uc-camera-recording-apv': '동영상 녹화 (APV) · 기본 KPI와 Pro video의 지속 성능을 비교합니다.',
  'uc-camera-capture': '정지 촬영 · 셔터 응답, 고해상도 처리와 연속 촬영의 순간 부하를 확인합니다.',
  'uc-camera-preview': '미리보기 · 촬영 전 화면 응답성과 상시 Sensor / ISP / 화면 표시 부하를 확인합니다.',
  'uc-video-playback-local': '로컬 영상 재생: UFS 파일 입력과 MFC/APV 디코딩을 분리해 봅니다. DRM, PiP, HDR, APV chroma format에 따라 복호화·합성·포맷 변환 경로가 달라질 수 있습니다.',
  'uc-youtube-playback': 'YouTube 재생: 네트워크 수신·demux·MFC 디코딩·화면 합성을 검토합니다. 등록된 codec/bitrate는 검토 조건이며 실제 서비스의 적응형 화질 선택이나 네트워크 성능을 보장하지 않습니다.',
  'uc-gallery-display': '갤러리 표시: 이미지 크기, 색공간, HDR, 레이어와 합성 경로를 비교합니다. 갤러리라는 이름만으로 JPEG 디코더나 모든 UI 동작이 모델링됐다고 가정하지 않습니다.',
  'uc-game-play': '로컬 게임: CPU/GPU 렌더링과 패널 출력 사이의 frame pacing, 해상도 및 목표 fps를 검토합니다. NPU 사용 여부와 render_resolution은 명시된 조건으로만 판단합니다.',
  'uc-game-streaming': '게임 스트리밍: 원격 렌더링 영상의 수신·decode·표시가 중심입니다. 로컬 게임의 GPU 부하와 구분하고 bitrate, low latency 설정, 디코딩 fps와 패널 Hz를 대조합니다.',
  'uc-audio-mp3-playback': '로컬 오디오 재생: UFS 파일 읽기, CPU decode와 DSP offload, speaker/Bluetooth 출력을 비교합니다. 시나리오 이름보다 variant의 실제 format과 offload 조건을 우선하세요.',
  'uc-audio-streaming': '오디오 스트리밍: 네트워크 입력과 압축 오디오 decode, ABOX 출력을 검토합니다. 화면 상태와 출력 장치별 지속 동작을 비교하며 네트워크 비용을 PCM BW로 대체하지 않습니다.',
  'uc-voice-call': '음성 통화: call_type별 송수신 오디오와 ABOX 경로를 비교합니다. camera_active=false와 함께 등록된 VT flag는 카메라 부하를 증명하지 않으며 modem RF는 별도 검토 대상입니다.',
  'uc-video-call': '영상 통화: 전면/후면 Sensor 입력, 인코딩 송신과 디코딩 수신이 동시에 진행되는 조건입니다. VT DVFS 값과 해상도·fps를 대조하고 음성·네트워크·패널 조건의 누락을 확인하세요.',
}

export const MODE_FOCUS: Record<Mode, string[]> = {
  kpi: ['Sensor / ISP 처리량', '메모리 대역폭', '인코더', '지속 기록 / 발열'],
  slow: ['Sensor 입력 fps', 'ISP 처리 시간', '메모리 대역폭', '프레임 누락'],
  portrait: ['분할 / 합성 지연', 'GPU / NPU / VPS / CPU 배치', '메모리 왕복'],
  pro: ['CPU 통계 / 제어', 'Histogram 갱신 주기', 'UI 합성', '프레임 지연'],
  none: ['사용 목적', '누락된 조건', '개별 파이프라인'],
}

export function scenarioPurpose(scenarioId: string): string {
  return SCENARIO_PURPOSES[scenarioId] ?? '등록된 설명이 없습니다. 조건과 파이프라인으로 목적을 확인하세요.'
}

export function modeBreakdown(rows: VariantRow[]): { mode: Mode; count: number }[] {
  const counts = new Map<Mode, number>()
  rows.forEach((r) => { const m = recordingMode(r); counts.set(m, (counts.get(m) ?? 0) + 1) })
  const order: Mode[] = ['kpi', 'slow', 'portrait', 'pro', 'none']
  return order.filter((m) => counts.get(m)).map((m) => ({ mode: m, count: counts.get(m)! }))
}

export function focusFor(rows: VariantRow[]): string[] {
  const seen = new Set<string>()
  modeBreakdown(rows).forEach(({ mode }) => MODE_FOCUS[mode].forEach((f) => seen.add(f)))
  return [...seen]
}

export const CATEGORY_ORDER = ['camera', 'voice_call', 'video', 'audio', 'game', 'display'] as const
export const CATEGORY_LABEL: Record<string, string> = {
  camera: 'Camera', video: 'Video', video_playback: 'Video', audio: 'Audio', game: 'Game', voice_call: 'Voice · Video call', display: 'Display',
}

/** Primary browse category (video_playback folds into video). */
export function primaryCategory(categories: string[] | undefined): string {
  const cats = (categories ?? []).map((c) => (c === 'video_playback' ? 'video' : c))
  for (const c of CATEGORY_ORDER) if (cats.includes(c)) return c
  return cats[0] ?? 'other'
}
