// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { ScenarioWhatIfPage } from './ScenarioWhatIf'
import type { Ctx } from '../App'
import { whatIfApi, type AskResponse, type WhatIfExperiment, type WhatIfResult, type WhatIfTargets } from '../lib/scenarioWhatIf'
import type { TimingReport } from '../lib/timingBudget'
import { setApiCredential } from '../lib/auth'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
afterEach(() => { setApiCredential(null); vi.restoreAllMocks() })
const scope = { project_ref: 'project', scenario_id: 'scenario', variant_id: 'variant' }
const hash = 'a'.repeat(64)
const ladder = [{ level: 5, mhz: 133 }, { level: 4, mhz: 200 }, { level: 3, mhz: 400 }, { level: 2, mhz: 533 }]
const intcam = { id: 'INTCAM', level: 3, mhz: 400, ips: ['msnr', 'mtnr'], stages: ['nrt'], ladder, index: 2 }
const targets: WhatIfTargets = {
  ...scope, baseline_hash: hash, anchors: [{ id: 'record_out', size: [3840, 2160], kind: 'output', supported: true, role: 'record' }],
  nodes: [{ id: 'mfc', label: 'MFC', size: [3840, 2160], size_supported: true, clock_supported: true, clock_mhz: 133, dvfs_group: 'INT' }],
  output_targets: ['record_out'], supported_changes: ['output_size', 'dvfs_level'], limitations: ['Sensor input remains fixed'], fps: 30,
  domains: [intcam],
  change_kinds: [
    { target: 'output_size', label: '출력 크기', shape: 'size', selector: 'anchor_id', selector_optional: true, needs_param: false, unit: '', max_value: null, description: '', choices: [{ id: 'record_out', size: [3840, 2160], role: 'record' }] },
    { target: 'node_clock_mhz', label: 'IP clock 하한', shape: 'value', selector: 'node_id', selector_optional: false, needs_param: false, unit: 'MHz', max_value: 5000, description: '', choices: [{ id: 'mfc', ip: 'mfc' }] },
    { target: 'dvfs_level', label: 'DVFS level', shape: 'level', selector: 'domain', selector_optional: false, needs_param: false, unit: 'L', max_value: null, description: '', choices: [{ id: 'INTCAM', level: 3, mhz: 400, ips: ['msnr', 'mtnr'], ladder }] },
  ],
  llm: { available: false, model: null },
}
const report = { ips: [{ node: 'mtnr', required_clock_mhz: 110, set_clock_mhz: 200, power_mw: 10, clock_reason: 'DVFS' }], stages: [{ id: 'nrt', name: 'NRT', hw_ms: 5, budget_ms: 20, sw_ms: 2 }], verdict: { reasons: [] } } as unknown as TimingReport
const metrics = { modeled_power_mw: 200, total_power_mw: null, cpu_power_mw: 50, ip_power_mw: 100, memory_power_mw: 50, bw_mbs: 500, fps: 30, period_ms: 33.33, feasible: true }
const coverage = { complete: false, scope: 'modeled CPU + IP + memory', missing_components: [], excluded_components: ['sensor'], cpu_model: 'flat', assumptions: ['SW runtime fixed'] }
const level4 = { target: 'dvfs_level', domain: 'INTCAM', level: 4 }
const result: WhatIfResult = { baseline_hash: hash, condition_hash: 'b'.repeat(64), normalized_condition: { scope, changes: [level4], config: {}, options: {} }, baseline: { report, metrics, coverage }, candidate: { report, metrics: { ...metrics, modeled_power_mw: 195 }, coverage }, delta: { metrics: {}, ips: [] }, warnings: [], model_lineage: { engine: 'timing-budget' } }
const answered = (over: Partial<AskResponse> = {}): AskResponse => ({ scope, baseline_hash: hash, interpretation: null, plan: { ask: 'what_if', changes: [level4], search_domains: [], focus: [] },
  answer: { verdict: 'ok', headline: 'INTCAM L3→L4 (200 MHz): timing 충족, 최소 여유 NRT 3.74 ms (기준 NRT 4.10 ms)', facts: ['모델 전력 200.0 → 195.0 mW (-5.0 mW)'], actions: [{ label: 'INTCAM 어디까지 낮출 수 있나', ask: 'search_limit', search_domains: ['INTCAM'] }] },
  result, search: null, diagnose: null, ...over })
const ctx = { project: 'project', scenario: 'scenario', variant: 'variant', params: {} } as Ctx
const edit = (input: HTMLTextAreaElement, value: string) => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })) }
const button = (host: HTMLElement, label: string) => [...host.querySelectorAll('button')].find((item) => item.textContent === label)!
const select = (el: HTMLSelectElement, value: string) => { el.value = value; el.dispatchEvent(new Event('change', { bubbles: true })) }
function mocks(t: WhatIfTargets = targets) {
  vi.spyOn(whatIfApi, 'targets').mockResolvedValue(t)
  vi.spyOn(whatIfApi, 'experiments').mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0, has_next: false })
}
async function mount(c: Ctx = ctx) {
  const host = document.createElement('div'), root = createRoot(host)
  await act(async () => root.render(<ScenarioWhatIfPage ctx={c} />))
  return { host, root }
}

it('builds a DVFS level condition from the ladder and answers first, then saves the computed result', async () => {
  mocks()
  const ask = vi.spyOn(whatIfApi, 'ask').mockResolvedValue(answered())
  const save = vi.spyOn(whatIfApi, 'save').mockResolvedValue({ id: 'e', title: 'intcam', visibility: 'shared' } as WhatIfExperiment)
  const { host, root } = await mount()
  try {
    expect(host.querySelector('[aria-label="자연어 질문"]')).toBeNull()                     // no LLM: builder only
    expect(host.textContent).toContain('자연어 질문은 사내 LLM 연결 시 사용할 수 있습니다')
    expect(button(host, '답 보기').disabled).toBe(true)
    await act(async () => button(host, '+ DVFS level').click())
    const level = host.querySelector<HTMLSelectElement>('[aria-label="INTCAM level"]')!
    expect([...level.options].map((o) => o.textContent)).toEqual(['L5 · 133 MHz (−2)', 'L4 · 200 MHz (−1)', 'L3 · 400 MHz (현재)', 'L2 · 533 MHz (+1)'])
    expect(level.value).toBe('4')                                                             // one level down by default
    await act(async () => button(host, '답 보기').click())
    expect(ask).toHaveBeenCalledWith({ ...scope, ask: 'what_if', changes: [level4] })
    expect(host.querySelector('.wi-headline')!.textContent).toBe('가능 INTCAM L3→L4 (200 MHz): timing 충족, 최소 여유 NRT 3.74 ms (기준 NRT 4.10 ms)')
    expect(host.textContent).toContain('기준 대비 조건 변경 결과')
    act(() => { edit(host.querySelector<HTMLTextAreaElement>('[aria-label="실험 제목"]')!, 'intcam'); select(host.querySelector<HTMLSelectElement>('[aria-label="실험 공개 범위"]')!, 'shared') })
    await act(async () => button(host, '실험 저장').click())
    expect(save).toHaveBeenCalledWith({ ...scope, changes: [level4], expected_baseline_hash: hash }, result, expect.objectContaining({ title: 'intcam', visibility: 'shared' }), 'INTCAM → L4')
    // a follow-up action runs the next question directly
    ask.mockResolvedValue(answered({ plan: { ask: 'search_limit', changes: [], search_domains: ['INTCAM'], focus: [] }, result: null,
      answer: { verdict: 'info', headline: 'INTCAM (현재 L3, 400 MHz): L5 (133 MHz)까지 2단계 가능', facts: [], actions: [] },
      search: [{ domain: 'INTCAM', level: 3, mhz: 400, ips: ['msnr', 'mtnr'], at_min: false, rows: [{ level: 4, mhz: 200, feasible: true, delta_mw: -5, min_slack_ms: 3.7, tight_stage: 'NRT', reason: null }, { level: 5, mhz: 133, feasible: true, delta_mw: -7, min_slack_ms: 3.1, tight_stage: 'NRT', reason: null }], lowest: null, first_fail: null }] }))
    await act(async () => button(host, 'INTCAM 어디까지 낮출 수 있나').click())
    expect(ask).toHaveBeenLastCalledWith({ ...scope, ask: 'search_limit', search_domains: ['INTCAM'] })
    expect(host.textContent).toContain('Level 한계 탐색')
    expect(host.querySelector<HTMLInputElement>('.wi-chip input')!.checked).toBe(true)        // the builder follows what ran
  } finally { act(() => root.unmount()) }
})
it('marks the answer as outdated when conditions change and warns that a clock floor below the applied clock does nothing', async () => {
  mocks()
  vi.spyOn(whatIfApi, 'ask').mockResolvedValue(answered())
  const { host, root } = await mount()
  try {
    await act(async () => button(host, '+ IP clock 하한').click())
    expect(host.querySelector<HTMLInputElement>('[aria-label="변경 clock MHz"]')!.value).toBe('133')
    expect(host.textContent).toContain('현재 133 MHz · 하한이므로 현재보다 낮추면 효과 없음 (낮추려면 DVFS level INT)')
    await act(async () => button(host, '-20%').click())
    expect(host.querySelector<HTMLInputElement>('[aria-label="변경 clock MHz"]')!.value).toBe('106.4')
  } finally { act(() => root.unmount()) }
  const again = await mount()
  try {
    await act(async () => button(again.host, '+ DVFS level').click())
    await act(async () => button(again.host, '답 보기').click())
    act(() => select(again.host.querySelector<HTMLSelectElement>('[aria-label="INTCAM level"]')!, '5'))
    expect(again.host.textContent).toContain('조건이 바뀌었습니다')
  } finally { act(() => again.root.unmount()) }
})
it('runs bottleneck and limit questions without any condition rows', async () => {
  mocks()
  const ask = vi.spyOn(whatIfApi, 'ask').mockResolvedValue(answered({ plan: { ask: 'diagnose', changes: [], search_domains: [], focus: [] }, result: null,
    answer: { verdict: 'ok', headline: '가장 빠듯한 구간 NRT — 여유 3.74 ms (frame 33.33 ms)', facts: [], actions: [] },
    diagnose: { verdict: 'ok', reasons: [], notes: [], period_ms: 33.33, stages: [{ id: 'nrt', name: 'NRT', slack_ms: 3.74, fill_pct: 89, hw_ms: 18.5, sw_ms: 11 }], tight: { id: 'nrt', name: 'NRT', slack_ms: 3.74 },
      top_ips: [], domains: [{ id: 'INTCAM', level: 3, mhz: 400, down: 2, up: 1, ips: ['msnr', 'mtnr'] }] } }))
  const { host, root } = await mount()
  try {
    await act(async () => button(host, '병목 찾기').click())
    expect(button(host, '답 보기').disabled).toBe(false)
    await act(async () => button(host, '답 보기').click())
    expect(ask).toHaveBeenCalledWith({ ...scope, ask: 'diagnose' })
    expect(host.querySelector('.wi-headline')!.textContent).toBe('timing 충족 가장 빠듯한 구간 NRT — 여유 3.74 ms (frame 33.33 ms)')
    expect(host.textContent).toContain('구간별 여유 · 병목')
    expect(host.textContent).toContain('2단계')
    await act(async () => button(host, '어디까지 낮출 수 있나').click())
    expect(host.textContent).toContain('INTCAM · L3 400 MHz · 2단계 아래까지')
    expect(host.textContent).toContain('선택하지 않으면 모든 domain을 탐색합니다')
  } finally { act(() => root.unmount()) }
})
it('with the in-house LLM, a question fills the builder, shows what was not modelled and resolves a choice in one click', async () => {
  mocks({ ...targets, llm: { available: true, model: 'in-house-7b' } })
  const ask = vi.spyOn(whatIfApi, 'ask').mockResolvedValue(answered({
    interpretation: { status: 'ready', used: 'llm', model: 'in-house-7b', latency_ms: 812, notes: ['INTCAM 한 단계 낮춤'], ignored: [{ text: 'EIS 끄면', reason: '기능 on/off는 다른 variant' }], boundaries: [], clarification: null } }))
  const { host, root } = await mount()
  try {
    act(() => edit(host.querySelector<HTMLTextAreaElement>('[aria-label="자연어 질문"]')!, 'INTCAM level을 하나 낮추면 timing에 문제가 없어?'))
    await act(async () => button(host, '질문하기').click())
    expect(ask).toHaveBeenCalledWith({ ...scope, query: 'INTCAM level을 하나 낮추면 timing에 문제가 없어?' })
    expect(host.querySelector<HTMLSelectElement>('[aria-label="INTCAM level"]')!.value).toBe('4')
    expect(host.textContent).toContain('사내 LLM 해석 · in-house-7b · 812 ms')
    expect(host.textContent).toContain('“EIS 끄면” — 기능 on/off는 다른 variant')
    ask.mockResolvedValue(answered({ plan: { ask: 'what_if', changes: [], search_domains: [], focus: [] }, answer: null, result: null,
      interpretation: { status: 'clarification', used: 'llm', clarification: { message: '얼마나 낮출까요?', choices: [{ label: 'INTCAM L5', change: { target: 'dvfs_level', domain: 'INTCAM', level: 5 } }] } } }))
    act(() => edit(host.querySelector<HTMLTextAreaElement>('[aria-label="자연어 질문"]')!, 'INTCAM 낮추면?'))
    await act(async () => button(host, '질문하기').click())
    ask.mockResolvedValue(answered())
    await act(async () => button(host, 'INTCAM L5').click())
    expect(ask).toHaveBeenLastCalledWith({ ...scope, ask: 'what_if', changes: [{ target: 'dvfs_level', domain: 'INTCAM', level: 5 }] })
  } finally { act(() => root.unmount()) }
})
it('says why the LLM could not answer and keeps the builder usable', async () => {
  mocks({ ...targets, llm: { available: true, model: 'in-house-7b' } })
  vi.spyOn(whatIfApi, 'ask').mockResolvedValue({ scope, baseline_hash: hash, interpretation: { status: 'llm_unavailable', reason: '사내 LLM 응답 시간 초과 (15 s)' }, plan: null, answer: null, result: null, search: null, diagnose: null })
  const { host, root } = await mount()
  try {
    act(() => edit(host.querySelector<HTMLTextAreaElement>('[aria-label="자연어 질문"]')!, 'INTCAM 하나 낮추면?'))
    await act(async () => button(host, '질문하기').click())
    expect(host.textContent).toContain('자연어 해석 불가 — 사내 LLM 응답 시간 초과 (15 s). 아래에서 조건을 골라 계산하세요.')
    expect(host.textContent).not.toContain('답변')
    expect(button(host, '+ DVFS level').disabled).toBe(false)
  } finally { act(() => root.unmount()) }
})
it('ignores a late answer after the authenticated account changes', async () => {
  mocks()
  let finish!: (value: AskResponse) => void
  vi.spyOn(whatIfApi, 'ask').mockImplementation(() => new Promise((resolve) => { finish = resolve }))
  const { host, root } = await mount()
  try {
    await act(async () => button(host, '+ DVFS level').click())
    await act(async () => button(host, '답 보기').click())
    await act(async () => setApiCredential({ keyId: 'new-analyst', secret: 'secret' }))
    await act(async () => finish(answered()))
    expect(host.textContent).not.toContain('기준 대비 조건 변경 결과')
    expect(host.querySelector('[aria-label="실험 제목"]')).toBeNull()
  } finally { act(() => root.unmount()) }
})
it('loads experiment conditions without running and keeps the saved model settings', async () => {
  const record = { ...scope, id: 'saved', title: 'saved experiment', purpose: 'comparison', description: null, assumptions: null, conclusion: null, baseline_hash: hash, condition_hash: hash, created_by: 'analyst', created_at: '2026-10-13T00:00:00Z', visibility: 'private', query: null,
    preview_request: { ...scope, changes: [level4], expected_baseline_hash: 'old', config: { power_model: 'v1-vfps' }, options: { statistic: 'mean' } } } as WhatIfExperiment
  mocks()
  vi.spyOn(whatIfApi, 'experiments').mockResolvedValue({ items: [record], total: 1, limit: 20, offset: 0, has_next: false })
  vi.spyOn(whatIfApi, 'experiment').mockResolvedValue(record)
  const ask = vi.spyOn(whatIfApi, 'ask').mockResolvedValue(answered())
  const { host, root } = await mount()
  try {
    await act(async () => button(host, '조건 불러오기').click())
    expect(ask).not.toHaveBeenCalled()
    expect(host.querySelector<HTMLSelectElement>('[aria-label="INTCAM level"]')!.value).toBe('4')
    await act(async () => button(host, '답 보기').click())
    expect(ask).toHaveBeenCalledWith({ ...scope, config: { power_model: 'v1-vfps' }, options: { statistic: 'mean' }, ask: 'what_if', changes: [level4] })
  } finally { act(() => root.unmount()) }
})
it('asks for the 과제 · scenario · variant before anything', async () => {
  mocks()
  const { host, root } = await mount({ ...ctx, variant: '', navigate: vi.fn() } as unknown as Ctx)
  try {
    expect(host.querySelector('[aria-label="What-if variant"]')).not.toBeNull()
    expect(host.textContent).toContain('과제 · scenario · variant를 먼저 선택하세요')
    expect(whatIfApi.targets).not.toHaveBeenCalled()
  } finally { act(() => root.unmount()) }
})
it('builds editors from server change kinds for any SoC and says when nothing can change', async () => {
  const streamTargets: WhatIfTargets = { ...scope, baseline_hash: hash, anchors: [], nodes: [], output_targets: [], supported_changes: ['stream_size'], limitations: [], fps: 30,
    streams: [{ id: '1920x1080', size: [1920, 1080], primary: true, where: ['mfc_dec.width'] }],
    change_kinds: [{ target: 'stream_size', label: '스트림 크기', shape: 'size', selector: 'stream_id', selector_optional: false, needs_param: false, unit: '', max_value: null, description: '', choices: [{ id: '1920x1080', size: [1920, 1080], primary: true }] }] }
  mocks(streamTargets)
  const ask = vi.spyOn(whatIfApi, 'ask').mockResolvedValue(answered())
  const { host, root } = await mount()
  try {
    expect(button(host, '+ FPS')).toBeUndefined()
    await act(async () => button(host, '+ 스트림 크기').click())
    await act(async () => button(host, 'HD').click())
    await act(async () => button(host, '답 보기').click())
    expect(ask).toHaveBeenCalledWith({ ...scope, ask: 'what_if', changes: [{ target: 'stream_size', stream_id: '1920x1080', width: 1280, height: 720 }] })
  } finally { act(() => root.unmount()) }
  mocks({ ...targets, change_kinds: [], domains: [] })
  const empty = await mount()
  try { expect(empty.host.textContent).toContain('바꿀 수 있는 조건이 없습니다') } finally { act(() => empty.root.unmount()) }
})
