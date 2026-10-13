// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { ScenarioWhatIfPage } from './ScenarioWhatIf'
import type { Ctx } from '../App'
import { whatIfApi, type WhatIfExperiment, type WhatIfPlan, type WhatIfResult, type WhatIfTargets } from '../lib/scenarioWhatIf'
import type { TimingReport } from '../lib/timingBudget'
import { setApiCredential } from '../lib/auth'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
afterEach(() => { setApiCredential(null); vi.restoreAllMocks() })
const scope = { project_ref: 'project', scenario_id: 'scenario', variant_id: 'variant' }
const hash = 'a'.repeat(64)
const targets: WhatIfTargets = { ...scope, baseline_hash: hash, anchors: [{ id: 'record_out', size: [3840, 2160], kind: 'output', supported: true }], nodes: [{ id: 'mfc', label: 'MFC', size: [3840, 2160], size_supported: true, clock_supported: true }], output_targets: ['record_out'], supported_changes: ['output_size', 'fps'], limitations: ['Sensor input remains fixed'] }
const plan: WhatIfPlan = { status: 'ready', query: '녹화 출력 FHD', changes: [{ target: 'output_size', anchor_id: 'record_out', width: 1920, height: 1080 }], clarifications: [], warnings: [], baseline_hash: hash }
const report = { ips: [{ node: 'mfc', required_clock_mhz: 200, set_clock_mhz: 400, power_mw: 100, clock_reason: 'DVFS' }], stages: [{ id: 'nrt', name: 'NRT', hw_ms: 5, budget_ms: 20, sw_ms: 2 }], verdict: { reasons: [] } } as unknown as TimingReport
const metrics = { modeled_power_mw: 200, total_power_mw: null, cpu_power_mw: 50, ip_power_mw: 100, memory_power_mw: 50, bw_mbs: 500, fps: 60, period_ms: 16.67, feasible: true }
const coverage = { complete: false, scope: 'modeled CPU + IP + memory', missing_components: [], excluded_components: ['sensor', 'display'], cpu_model: 'flat', assumptions: ['SW runtime fixed'] }
const result: WhatIfResult = { baseline_hash: hash, condition_hash: 'b'.repeat(64), normalized_condition: { scope, changes: plan.changes, config: {}, options: {} }, baseline: { report, metrics, coverage }, candidate: { report, metrics: { ...metrics, modeled_power_mw: 150 }, coverage }, delta: { metrics: {}, ips: [{ node: 'mfc', required_clock_mhz: 0, set_clock_mhz: 0, power_mw: 0, explanation: 'shared domain' }] }, warnings: [], model_lineage: { engine: 'timing-budget' } }
const ctx = { project: 'project', scenario: 'scenario', variant: 'variant', params: {} } as Ctx
const edit = (input: HTMLTextAreaElement, value: string) => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })) }
const button = (host: HTMLElement, label: string) => [...host.querySelectorAll('button')].find((item) => item.textContent === label)!
function mocks() {
  vi.spyOn(whatIfApi, 'targets').mockResolvedValue(targets)
  vi.spyOn(whatIfApi, 'experiments').mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0, has_next: false })
}

it('requires explicit preview after interpreting and saves the reviewed result and visibility', async () => {
  mocks()
  const interpret = vi.spyOn(whatIfApi, 'plan').mockResolvedValue(plan)
  const preview = vi.spyOn(whatIfApi, 'preview').mockResolvedValue(result)
  const save = vi.spyOn(whatIfApi, 'save').mockResolvedValue({ id: 'experiment', title: 'output check', visibility: 'shared' } as WhatIfExperiment)
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<ScenarioWhatIfPage ctx={ctx} />))
    act(() => edit(host.querySelector<HTMLTextAreaElement>('[aria-label="변경 조건 질문"]')!, '녹화 출력 FHD'))
    await act(async () => button(host, '변경 조건 해석').click())
    expect(interpret).toHaveBeenCalledWith(scope, '녹화 출력 FHD')
    expect(preview).not.toHaveBeenCalled()
    await act(async () => { button(host, '조건 비교 계산').click(); button(host, '조건 비교 계산').click() })
    expect(preview).toHaveBeenCalledTimes(1)
    expect(preview).toHaveBeenCalledWith({ ...scope, changes: plan.changes, expected_baseline_hash: hash })
    expect(host.textContent).toContain('모델 합계')
    expect(host.textContent).toContain('제외·미모델 항목으로 계산되지 않음')
    expect(host.textContent).toContain('개인 구분은 서버 사용자 인증이 활성화된 환경에서 적용됩니다')
    expect(host.textContent).toContain('공유 · 인증된 사용자 열람')
    act(() => { edit(host.querySelector<HTMLTextAreaElement>('[aria-label="실험 제목"]')!, 'output check'); const select = host.querySelector<HTMLSelectElement>('[aria-label="실험 공개 범위"]')!; select.value = 'shared'; select.dispatchEvent(new Event('change', { bubbles: true })) })
    await act(async () => button(host, '실험 저장').click())
    expect(save).toHaveBeenCalledWith(expect.objectContaining({ changes: plan.changes }), result, expect.objectContaining({ title: 'output check', visibility: 'shared' }), '녹화 출력 FHD')
    expect(host.textContent).toContain('실험 저장됨')
  } finally { act(() => root.unmount()) }
})
it('clears private drafts and ignores late preview results when the authenticated account changes', async () => {
  mocks()
  vi.spyOn(whatIfApi, 'plan').mockResolvedValue(plan)
  let finish!: (value: WhatIfResult) => void
  vi.spyOn(whatIfApi, 'preview').mockImplementation(() => new Promise((resolve) => { finish = resolve }))
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<ScenarioWhatIfPage ctx={ctx} />))
    act(() => edit(host.querySelector<HTMLTextAreaElement>('[aria-label="변경 조건 질문"]')!, '녹화 출력 FHD'))
    await act(async () => button(host, '변경 조건 해석').click())
    await act(async () => button(host, '조건 비교 계산').click())
    await act(async () => setApiCredential({ keyId: 'new-analyst', secret: 'secret' }))
    await act(async () => finish(result))
    expect(host.querySelector<HTMLTextAreaElement>('[aria-label="변경 조건 질문"]')!.value).toBe('')
    expect(host.textContent).not.toContain('기준 대비 조건 변경 결과')
    expect(host.querySelector('[aria-label="실험 제목"]')).toBeNull()
  } finally { act(() => root.unmount()) }
})
it('discards a late interpretation when the question changes and isolates context switching', async () => {
  mocks()
  let finish!: (value: WhatIfPlan) => void
  const interpret = vi.spyOn(whatIfApi, 'plan').mockImplementation(() => new Promise((resolve) => { finish = resolve }))
  const preview = vi.spyOn(whatIfApi, 'preview').mockResolvedValue(result)
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<ScenarioWhatIfPage ctx={ctx} />))
    act(() => edit(host.querySelector<HTMLTextAreaElement>('[aria-label="변경 조건 질문"]')!, '녹화 출력 FHD'))
    await act(async () => button(host, '변경 조건 해석').click())
    expect(interpret).toHaveBeenCalledTimes(1)
    act(() => edit(host.querySelector<HTMLTextAreaElement>('[aria-label="변경 조건 질문"]')!, 'FPS 30'))
    await act(async () => finish(plan))
    expect(host.textContent).not.toContain('해석 완료')
    expect(button(host, '조건 비교 계산').disabled).toBe(true)
    expect(preview).not.toHaveBeenCalled()
    await act(async () => root.render(<ScenarioWhatIfPage ctx={{ ...ctx, scenario: 'new-scenario', variant: 'new-variant' }} />))
    expect(host.querySelector<HTMLTextAreaElement>('[aria-label="변경 조건 질문"]')!.value).toBe('')
    expect(button(host, '조건 비교 계산').disabled).toBe(true)
  } finally { act(() => root.unmount()) }
})
it('loads experiment conditions without automatically running and preserves saved model settings', async () => {
  mocks()
  const record = { ...scope, id: 'saved', title: 'saved experiment', purpose: 'comparison', description: null, assumptions: null, conclusion: null, baseline_hash: hash, condition_hash: hash, created_by: 'analyst', created_at: '2026-10-13T00:00:00Z', visibility: 'private', query: '녹화 출력 FHD', preview_request: { ...scope, changes: plan.changes, expected_baseline_hash: 'old', config: { power_model: 'v1-vfps' }, options: { statistic: 'mean' } } } as WhatIfExperiment
  vi.spyOn(whatIfApi, 'experiments').mockResolvedValue({ items: [record], total: 1, limit: 20, offset: 0, has_next: false })
  vi.spyOn(whatIfApi, 'experiment').mockResolvedValue(record)
  const preview = vi.spyOn(whatIfApi, 'preview').mockResolvedValue(result)
  const host = document.createElement('div'), root = createRoot(host)
  try {
    await act(async () => root.render(<ScenarioWhatIfPage ctx={ctx} />))
    await act(async () => button(host, '조건 불러오기 · 재실행').click())
    expect(preview).not.toHaveBeenCalled()
    await act(async () => button(host, '조건 비교 계산').click())
    expect(preview).toHaveBeenCalledWith({ ...scope, changes: plan.changes, expected_baseline_hash: hash, config: { power_model: 'v1-vfps' }, options: { statistic: 'mean' } })
  } finally { act(() => root.unmount()) }
})
