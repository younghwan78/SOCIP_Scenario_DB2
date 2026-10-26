// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { WhatIfSweep } from './WhatIfSweep'
import { readExperimentContext, updateExperimentContext } from '../lib/experimentContext'
import { whatIfApi, type SweepJob, type SweepResult, type WhatIfTargets } from '../lib/scenarioWhatIf'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
afterEach(() => { sessionStorage.clear(); vi.restoreAllMocks() })
const scope = { project_ref: 'project', scenario_id: 'recording', variant_id: 'rear' }
const changes = [{ target: 'fps', value: 30 }]
const targets: WhatIfTargets = { ...scope, baseline_hash: 'baseline', analysis_hash: 'analysis', anchors: [], nodes: [], output_targets: [], supported_changes: ['fps'], limitations: [], change_kinds: [
  { target: 'fps', label: 'FPS', shape: 'value', selector: null, selector_optional: false, needs_param: false, unit: 'fps', max_value: 240, description: '', choices: [] },
] }
const metrics = { modeled_power_mw: 200, total_power_mw: null, cpu_power_mw: 50, ip_power_mw: 100, memory_power_mw: 50, bw_mbs: 500, fps: 30, period_ms: 33.33, feasible: true }
const coverage = { complete: false, scope: 'CPU + IP + memory', missing_components: [], excluded_components: ['sensor'], cpu_model: 'flat', assumptions: [] }
const preview = { ...scope, changes: [{ target: 'fps', value: 15 }], config: { power_model: 'v1-vfps' }, basis_ref: 'basis-1', comparison: 'fixed_opp' as const, expected_baseline_hash: 'baseline', expected_analysis_hash: 'analysis' }
const result: SweepResult = { scope, baseline_hash: 'baseline', analysis_hash: 'analysis', baseline: { metrics, coverage }, rows: [{ id: 'case-1', label: 'FPS=15', changes: preview.changes, preview_request: preview, metrics: { ...metrics, fps: 15 }, delta: { modeled_power_mw: -10 }, feasible: true, eligible: true, reasons: [], iq_required: [], condition_hash: 'condition', min_slack_ms: 10, latency_ms: 5 }], pareto_ids: ['case-1'], best_id: 'case-1', total_cases: 2, completed_cases: 2, cancelled: false, assumptions: [] }
const button = (host: HTMLElement, text: string) => [...host.querySelectorAll('button')].find((item) => item.textContent?.startsWith(text))!
const input = (el: HTMLTextAreaElement | HTMLInputElement, value: string) => { Object.getOwnPropertyDescriptor(el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })) }
async function mount(onLoad = vi.fn()) {
  const host = document.createElement('div'), root = createRoot(host)
  await act(async () => root.render(<WhatIfSweep scope={scope} targets={targets} changes={changes} settings={{}} onLoad={onLoad} />))
  return { host, root, onLoad }
}
it('submits bounded values and constraints, cancels, resumes, and opens the exact fixed-OPP candidate', async () => {
  let server: SweepJob = { id: 'job-1', status: 'running', completed_cases: 0, total_cases: 2, resumable: false }
  const start = vi.spyOn(whatIfApi, 'startJob').mockImplementation(async () => server)
  vi.spyOn(whatIfApi, 'job').mockImplementation(async () => server)
  const cancel = vi.spyOn(whatIfApi, 'cancelJob').mockImplementation(async () => { server = { ...server, status: 'cancelled', completed_cases: 1, resumable: true }; return server })
  const resume = vi.spyOn(whatIfApi, 'resumeJob').mockImplementation(async () => { server = { ...server, status: 'completed', completed_cases: 2, resumable: false, result }; return server })
  const mounted = await mount()
  try {
    await act(async () => button(mounted.host, '탐색 항목 추가').click())
    act(() => { input(mounted.host.querySelector<HTMLTextAreaElement>('[aria-label="탐색 축 1 값"]')!, '15,30'); input(mounted.host.querySelector<HTMLInputElement>('[aria-label="모델 전력 상한 mW"]')!, '250') })
    act(() => { const select = mounted.host.querySelector<HTMLSelectElement>('[aria-label="전력 비교 방식"]')!; select.value = 'fixed_opp'; select.dispatchEvent(new Event('change', { bubbles: true })) })
    await act(async () => button(mounted.host, '범위 탐색 실행').click())
    expect(start).toHaveBeenCalledWith({ ...scope, expected_baseline_hash: 'baseline', expected_analysis_hash: 'analysis', changes: [], axes: [{ label: 'FPS', values: [{ target: 'fps', value: 15 }, { target: 'fps', value: 30 }] }], constraints: { allow_iq_required: false, max_power_mw: 250 }, comparison: 'fixed_opp' })
    expect(readExperimentContext(scope)?.job_id).toBe('job-1')
    await act(async () => button(mounted.host, '탐색 중단').click())
    expect(cancel).toHaveBeenCalledWith('job-1')
    await act(async () => button(mounted.host, '남은 계산 재개').click())
    expect(resume).toHaveBeenCalledWith('job-1')
    expect(mounted.host.textContent).toContain('절충 후보')
    await act(async () => button(mounted.host, '상세 조건 불러오기').click())
    expect(mounted.onLoad).toHaveBeenCalledWith(preview)
    act(() => input(mounted.host.querySelector<HTMLTextAreaElement>('[aria-label="탐색 축 1 값"]')!, '15,60'))
    expect(mounted.host.textContent).toContain('이전 조건 결과 · 재계산 필요')
    expect(button(mounted.host, '상세 조건 불러오기').disabled).toBe(true)
  } finally { act(() => mounted.root.unmount()) }
})
it('recovers a checkpoint by job id after navigation and rejects stale model results', async () => {
  updateExperimentContext(scope, { job_id: 'existing' })
  const job = vi.spyOn(whatIfApi, 'job').mockResolvedValue({ id: 'existing', status: 'completed', completed_cases: 2, total_cases: 2, resumable: false, result: { ...result, analysis_hash: 'old-analysis' } })
  const mounted = await mount()
  try {
    expect(job).toHaveBeenCalledWith('existing')
    expect(mounted.host.textContent).toContain('이전 조건 결과 · 재계산 필요')
    expect(button(mounted.host, '상세 조건 불러오기').disabled).toBe(true)
  } finally { act(() => mounted.root.unmount()) }
})
