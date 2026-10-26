// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { ScenarioWhatIfPage } from './ScenarioWhatIf'
import type { Ctx } from '../App'
import { whatIfApi, type AskResponse, type WhatIfExperiment, type WhatIfResult, type WhatIfTargets } from '../lib/scenarioWhatIf'
import type { TimingReport } from '../lib/timingBudget'
import { setApiCredential } from '../lib/auth'
import { readExperimentContext, updateExperimentContext } from '../lib/experimentContext'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
afterEach(() => { setApiCredential(null); sessionStorage.clear(); vi.restoreAllMocks() })
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
    expect(host.querySelector('.wi-headline')!.textContent).toBe('timing 충족 INTCAM L3→L4 (200 MHz): timing 충족, 최소 여유 NRT 3.74 ms (기준 NRT 4.10 ms)')
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
    expect(again.host.textContent).toContain('이전 조건 결과 · 재계산 필요')
    expect(again.host.querySelectorAll('.wi-result-state.is-stale').length).toBe(3)
    expect(button(again.host, '현재 결과를 후보로 담기').disabled).toBe(true)
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
    expect(whatIfApi.targets).toHaveBeenLastCalledWith(scope, { config: { power_model: 'v1-vfps' }, options: { statistic: 'mean' } })
    expect(host.querySelector<HTMLSelectElement>('[aria-label="INTCAM level"]')!.value).toBe('4')
    await act(async () => button(host, '답 보기').click())
    expect(ask).toHaveBeenCalledWith({ ...scope, config: { power_model: 'v1-vfps' }, options: { statistic: 'mean' }, ask: 'what_if', changes: [level4] })
  } finally { act(() => root.unmount()) }
})

const savedRecord = (id: string, level: number): WhatIfExperiment => ({ ...scope, id, title: id,
  purpose: null, description: null, assumptions: null, conclusion: null, baseline_hash: hash, condition_hash: hash,
  created_by: 'analyst', created_at: '2026-10-13T00:00:00Z', visibility: 'private', query: null,
  preview_request: { ...scope, changes: [{ ...level4, level }], expected_baseline_hash: hash, config: {}, options: {} } })

it('opens a new saved-record URL in the same scope and ignores the previous late load', async () => {
  mocks()
  const pending = new Map<string, (record: WhatIfExperiment) => void>()
  const load = vi.spyOn(whatIfApi, 'experiment').mockImplementation((id) => new Promise((finish) => pending.set(id, finish)))
  const { host, root } = await mount({ ...ctx, params: { experiment: 'saved-a' } })
  try {
    expect(load).toHaveBeenCalledWith('saved-a')
    await act(async () => root.render(<ScenarioWhatIfPage ctx={{ ...ctx, params: { experiment: 'saved-b' } }} />))
    expect(load).toHaveBeenCalledWith('saved-b')
    await act(async () => pending.get('saved-b')!(savedRecord('saved-b', 5)))
    expect(host.querySelector<HTMLSelectElement>('[aria-label="INTCAM level"]')?.value).toBe('5')
    await act(async () => pending.get('saved-a')!(savedRecord('saved-a', 4)))
    expect(host.querySelector<HTMLSelectElement>('[aria-label="INTCAM level"]')?.value).toBe('5')
    expect(readExperimentContext(scope)?.changes).toEqual([{ ...level4, level: 5 }])
    expect(button(host, '답 보기').disabled).toBe(false)
  } finally { act(() => root.unmount()) }
})

it.each(['scope', 'principal'])('does not write a saved-record load into a changed %s draft', async (change) => {
  mocks()
  let finish!: (record: WhatIfExperiment) => void
  vi.spyOn(whatIfApi, 'experiment').mockImplementation(() => new Promise((resolve) => { finish = resolve }))
  const { host, root } = await mount({ ...ctx, params: { experiment: 'saved-a' } })
  try {
    const next = change === 'scope' ? { ...ctx, variant: 'other-variant', params: {} } : ctx
    const nextScope = { project_ref: next.project, scenario_id: next.scenario, variant_id: next.variant }
    await act(async () => {
      if (change === 'principal') setApiCredential({ keyId: 'other-analyst', secret: 'secret' })
      root.render(<ScenarioWhatIfPage ctx={next} />)
    })
    await act(async () => finish(savedRecord('saved-a', 4)))
    expect(host.querySelector('[aria-label="INTCAM level"]')).toBeNull()
    expect(readExperimentContext(nextScope)?.changes).toEqual([])
    expect(host.textContent).not.toContain('저장된 조건을 불러왔습니다')
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
const leverKinds: WhatIfTargets['change_kinds'] = [
  ...targets.change_kinds!,
  { target: 'power_knob', label: 'Power option', shape: 'choice', selector: 'param', selector_optional: false, needs_param: true, unit: '', max_value: null, description: '', group: 'temporal', iq: 'required',
    choices: [{ id: 'pyramid_l0', param: 'pyramid_l0', label: 'MTNR L0 skip', current: 'use', options: [{ id: 'skip', label: 'MTNR L0 skip (skip)', iq_eval: 'required' }] }] },
  { target: 'history_interval', label: 'Previous DMA 빈도', shape: 'value', selector: 'buffer_id', selector_optional: true, needs_param: false, unit: 'frame', max_value: 8, description: '', group: 'temporal', iq: 'required',
    choices: [{ id: 'TNR_PREV_L0', node: 'mtnr', ports: 2, value: 1, format: 'Y' }] },
  { target: 'compression', label: 'SBWC 압축', shape: 'choice', selector: 'buffer_id', selector_optional: false, needs_param: false, unit: '', max_value: null, description: '', group: 'compression', value_optional: true,
    choices: [{ id: 'PYRAMID_L0', format: 'Y', current: 'COMP_YUV_LOSSLESS', nodes: ['mlsc', 'mtnr'], history: false,
      options: [{ id: 'COMP_OFF', ratio: 1, ratio_source: 'off', supported: true }, { id: 'COMP_YUV_LOSSLESS', ratio: 0.7, ratio_source: 'typical', supported: true }, { id: 'COMP_YUV_LOSSY', ratio: 0.5, ratio_source: 'catalog', lossy: true, supported: true }, { id: 'COMP_YUV_LOSSY_FP', ratio: 0.6, ratio_source: 'catalog', lossy: true, supported: false }] }] },
]
it('groups levers by commercialization task, edits choice levers and compares them in one combine run', async () => {
  mocks({ ...targets, change_kinds: leverKinds })
  const combine: AskResponse['combine'] = { mode: 'each', baseline_mw: 800, best: '0+1', interaction_mw: 2.5,
    levers: [{ index: 0, change: { target: 'power_knob', param: 'pyramid_l0', option: 'skip' }, label: 'MTNR L0 skip (skip)', group: 'temporal', iq_required: true },
      { index: 1, change: { target: 'history_interval', value: 2 }, label: 'previous DMA 전체 2 frame마다 1회', group: 'temporal', iq_required: true }],
    rows: [
      { key: 'baseline', levers: [], metrics: metrics, delta: { modeled_power_mw: 0, cpu_power_mw: 0, ip_power_mw: 0, memory_power_mw: 0, bw_mbs: 0 }, feasible: true, min_slack_ms: 3, tight_stage: 'NRT', reason: null, notes: [] },
      { key: '0', levers: [0], metrics: metrics, delta: { modeled_power_mw: -40, cpu_power_mw: 0, ip_power_mw: 0, memory_power_mw: -40, bw_mbs: -800 }, feasible: true, min_slack_ms: 3, tight_stage: 'NRT', reason: null, notes: [] },
      { key: '1', levers: [1], metrics: metrics, delta: { modeled_power_mw: -44, cpu_power_mw: 0, ip_power_mw: 0, memory_power_mw: -44, bw_mbs: -850 }, feasible: true, min_slack_ms: 3, tight_stage: 'NRT', reason: null, notes: [] },
      { key: '0+1', levers: [0, 1], metrics: metrics, delta: { modeled_power_mw: -81.5, cpu_power_mw: 0, ip_power_mw: 0, memory_power_mw: -81.5, bw_mbs: -1600 }, feasible: true, min_slack_ms: 3, tight_stage: 'NRT', reason: null, notes: [] }] }
  const ask = vi.spyOn(whatIfApi, 'ask').mockResolvedValue(answered({ plan: { ask: 'combine', changes: combine.levers.map((l) => l.change), search_domains: [], focus: [] }, result: null, combine,
    answer: { verdict: 'ok', headline: 'fps 충족 최저 전력: #1 + #2 — -81.5 mW (-10.2%)', facts: [], actions: [] } }))
  const { host, root } = await mount()
  try {
    expect([...host.querySelectorAll('.wi-pal-label')].map((x) => x.textContent)).toEqual(['크기 · crop · downscale', 'Temporal · previous DMA', 'DVFS · clock · FPS', 'SBWC 압축'])
    await act(async () => button(host, '+ SBWC 압축').click())
    const mode = host.querySelector<HTMLSelectElement>('[aria-label="SBWC 압축 값"]')!
    expect(mode.value).toBe('COMP_OFF')                                                       // first option that differs from the current mode
    expect([...mode.options].find((o) => o.value === 'COMP_YUV_LOSSY_FP')!.disabled).toBe(true)   // IP catalog does not list it
    act(() => select(mode, 'COMP_YUV_LOSSY'))
    expect(host.textContent).toContain('IQ 평가')                                             // lossy needs image-quality evaluation
    await act(async () => button(host, '항목 제거').click())
    await act(async () => button(host, '레버 조합 비교').click())
    expect(button(host, '답 보기').disabled).toBe(true)                                        // needs two levers
    await act(async () => button(host, '+ Power option').click())
    await act(async () => button(host, '+ Previous DMA 빈도').click())
    expect(host.textContent).toContain('previous DMA 갱신 15.0 fps')
    await act(async () => button(host, '답 보기').click())
    expect(ask).toHaveBeenCalledWith({ ...scope, ask: 'combine', combine: 'each', changes: [{ target: 'power_knob', param: 'pyramid_l0', option: 'skip' }, { target: 'history_interval', value: 2 }] })
    expect(host.textContent).toContain('레버 조합 비교')
    expect(host.querySelector('.wi-combo tr.wi-focus th')!.textContent).toBe('★ #1 + #2')
    expect(host.textContent).toContain('모두 적용 − 단독 합 = +2.5 mW')
  } finally { act(() => root.unmount()) }
})
it('steps a DVFS domain ±1/±2 levels from the current OPP', async () => {
  mocks()
  vi.spyOn(whatIfApi, 'ask').mockResolvedValue(answered())
  const { host, root } = await mount()
  try {
    await act(async () => button(host, '+ DVFS level').click())
    await act(async () => button(host, '−2 step').click())
    expect(host.querySelector<HTMLSelectElement>('[aria-label="INTCAM level"]')!.value).toBe('5')
    await act(async () => button(host, '+1 step').click())
    expect(host.querySelector<HTMLSelectElement>('[aria-label="INTCAM level"]')!.value).toBe('2')
    expect(button(host, '+2 step').disabled).toBe(true)                                       // beyond the ladder
  } finally { act(() => root.unmount()) }
})

it('preserves candidate baseline settings across navigation and marks changed model inputs', async () => {
  const model = { config: { power_model: 'v1-vfps' }, options: { statistic: 'mean' }, basis_ref: 'basis-1', comparison: 'fixed_opp' as const }
  updateExperimentContext(scope, { changes: [level4], ...model })
  mocks({ ...targets, analysis_hash: 'analysis-1', baseline: { metrics, coverage } })
  const ask = vi.spyOn(whatIfApi, 'ask').mockResolvedValue(answered({ result: { ...result, analysis_hash: 'analysis-1', normalized_condition: { ...result.normalized_condition, config: { dvfs_overrides: { INTCAM: 4 } } } } }))
  const first = await mount()
  try {
    expect(first.host.textContent).toContain('센서 전력: 미확정')
    expect(first.host.querySelector<HTMLSelectElement>('[aria-label="조건 비교 방식"]')?.value).toBe('fixed_opp')
    await act(async () => button(first.host, '답 보기').click())
    expect(ask).toHaveBeenCalledWith(expect.objectContaining({ ...model, expected_baseline_hash: hash, expected_analysis_hash: 'analysis-1' }))
    await act(async () => button(first.host, '현재 결과를 후보로 담기').click())
    expect(readExperimentContext(scope)?.candidates[0]).toMatchObject({ config: model.config, comparison: 'fixed_opp', analysis_hash: 'analysis-1' })
    await act(async () => select(first.host.querySelector<HTMLSelectElement>('[aria-label="INTCAM level"]')!, '5'))
    expect(button(first.host, '현재 결과를 후보로 담기').disabled).toBe(true)
  } finally { act(() => first.root.unmount()) }
  vi.mocked(whatIfApi.targets).mockResolvedValue({ ...targets, analysis_hash: 'analysis-2' })
  const second = await mount()
  try {
    expect(second.host.querySelector<HTMLSelectElement>('[aria-label="INTCAM level"]')?.value).toBe('5')
    expect(second.host.textContent).toContain('기준 다름')
    await act(async () => button(second.host, '조건 불러오기').click())
    expect(second.host.querySelector<HTMLSelectElement>('[aria-label="INTCAM level"]')?.value).toBe('4')
    expect(readExperimentContext(scope)?.comparison).toBe('fixed_opp')
  } finally { act(() => second.root.unmount()) }
})
it('opens the requested pipeline node and validates crop ROI before submitting', async () => {
  const cropKind = { target: 'chain_size', label: 'IP crop', shape: 'size' as const, selector: 'node_id' as const, selector_optional: false, needs_param: false, unit: '', max_value: null, description: '', choices: ['first', 'requested'].map((id) => ({ id, size: [3840, 2160] as [number, number], downstream: ['out'], affected_buffers: ['OUT'], geometry: { operations: ['crop' as const], default_operation: 'crop' as const, capabilities: { crop: { alignment: [16, 2] as [number, number], offset_alignment: [8, 2] as [number, number] } } } })) }
  mocks({ ...targets, change_kinds: [cropKind] })
  const mounted = await mount({ ...ctx, params: { whatif_target: 'chain_size', whatif_node: 'requested' } })
  try {
    expect(mounted.host.querySelector<HTMLSelectElement>('[aria-label="IP crop 대상"]')?.value).toBe('requested')
    expect(mounted.host.textContent).toContain('영향 buffer: OUT')
    const x = mounted.host.querySelector<HTMLInputElement>('[aria-label="Crop X"]')!
    act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(x, '9'); x.dispatchEvent(new Event('input', { bubbles: true })) })
    expect(button(mounted.host, '답 보기').disabled).toBe(true)
    expect(mounted.host.textContent).toContain('Crop 위치는 8×2')
  } finally { act(() => mounted.root.unmount()) }
})
it('groups sensor identities and selects a pinned catalog mode from a Library entry', async () => {
  const binding = { catalog_ref: 'catalog-2', catalog_sha256: hash, mode_label: 'RAW12 full 60', lineup_ref: 'board', lineup_sha256: hash, board_config: 'production', slot: 'rear' }
  const sensorKind = { target: 'sensor_binding', label: '등록 센서', shape: 'choice' as const, selector: 'node_id' as const, selector_optional: false, needs_param: false, unit: '', max_value: null, description: '', group: 'sensor' as const,
    choices: [{ id: 'sensor', options: [
      { id: 'catalog-1#RAW10 full 60', sensor: 'Sensor A', ip_ref: 'sensor-a', mode: 'RAW10 full 60', size: [4000, 3000] as [number, number], fps: 60, supported: true, sensor_binding: { ...binding, catalog_ref: 'catalog-1', mode_label: 'RAW10 full 60' } },
      { id: 'catalog-2#RAW12 full 60', sensor: 'Sensor B', ip_ref: 'sensor-b', mode: 'RAW12 full 60', size: [4000, 3000] as [number, number], fps: 60, supported: true, sensor_binding: binding },
      { id: 'catalog-2#RAW10 binned 30', sensor: 'Sensor B', ip_ref: 'sensor-b', mode: 'RAW10 binned 30', fps: 30, fps_compatible: false, supported: true, sensor_binding: { ...binding, mode_label: 'RAW10 binned 30' } },
    ] }] }
  mocks({ ...targets, change_kinds: [sensorKind] })
  const ask = vi.spyOn(whatIfApi, 'ask').mockResolvedValue(answered())
  const mounted = await mount({ ...ctx, params: { whatif_target: 'sensor_mode', whatif_catalog: 'catalog-2' } })
  try {
    const sensor = mounted.host.querySelector<HTMLSelectElement>('[aria-label="등록 센서 센서"]')!, mode = mounted.host.querySelector<HTMLSelectElement>('[aria-label="등록 센서 값"]')!
    expect(sensor.options).toHaveLength(2)
    expect(sensor.value).toBe('sensor-b')
    expect(mode.value).toBe('catalog-2#RAW12 full 60')
    expect([...mode.options].map((item) => item.value)).toEqual(['', 'catalog-2#RAW12 full 60', 'catalog-2#RAW10 binned 30'])
    expect(mode.options[2].disabled).toBe(false) // can combine with a lower final FPS
    await act(async () => button(mounted.host, '답 보기').click())
    expect(ask).toHaveBeenCalledWith(expect.objectContaining({ changes: [{ target: 'sensor_binding', node_id: 'sensor', option: 'catalog-2#RAW12 full 60', sensor_binding: binding }] }))
  } finally { act(() => mounted.root.unmount()) }
})
