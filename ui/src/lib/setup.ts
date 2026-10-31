// First-run checklist of a 과제 (Home · G-03): 예측 기준 → 조합 탐색 → 예측 등록 → 실측 → 보고서.
// A new project DB starts with every count at 0; the first unfinished step is the one to do next.
import type { Page } from './route'

export interface SetupCounts {
  /** model bases (draft or active) of the project; null = not loaded */
  bases: number | null
  activeBasis: string | null
  runs: number
  predictions: number
  variants: number
  measurements: number
  synthetic: number
  reports: number
}
export type StepState = 'done' | 'next' | 'todo'
export interface SetupStep { key: string; no: string; label: string; value: string; state: StepState; href: string; hint: string }

export function setupSteps(c: SetupCounts, href: (page: Page, extra?: string) => string): SetupStep[] {
  const steps: Omit<SetupStep, 'state'>[] = [
    { key: 'basis', no: '①', label: '예측 기준', value: c.bases === null ? '…' : c.activeBasis ? `${c.activeBasis} active` : c.bases ? `${c.bases}개 (active 없음)` : '0',
      href: href('predictions', 'bp=1'), hint: 'config profile · power params · DVFS table을 고정한 기준 (예측 현황 › 예측 기준)' },
    { key: 'explore', no: '②', label: '조합 탐색', value: `run ${c.runs}`, href: href('explore'), hint: 'KPI scenario 일괄 탐색 · keep / trade 추천' },
    { key: 'register', no: '③', label: '예측 등록', value: `${c.predictions} / ${c.variants}`, href: href('predictions'), hint: '탐색 결과를 variant의 current 예측으로 등록 (고객 보고 숫자)' },
    { key: 'measure', no: '④', label: '실측', value: `실측 ${c.measurements}${c.synthetic ? ` · 합성 ${c.synthetic}` : ''}`, href: href('calibration'), hint: '실측 import 후 rail 그룹별 오차 확인 (합성은 검증 근거 아님)' },
    { key: 'report', no: '⑤', label: '보고서', value: `${c.reports}`, href: href('reports'), hint: '고객 기준 · risk register를 포함한 과제 보고서' },
  ]
  const done = [!!c.activeBasis, c.runs > 0, c.predictions > 0, c.measurements > 0, c.reports > 0]
  const next = done.indexOf(false)
  return steps.map((s, i) => ({ ...s, state: done[i] ? 'done' : i === next ? 'next' : 'todo' }))
}
