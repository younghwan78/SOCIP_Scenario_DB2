// @vitest-environment jsdom
import { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { Ctx } from '../App'
import { api, type Evidence, type EvidenceSummary, type HandoffDoc, type ViewResponse } from '../lib/api'
import { archApi } from '../lib/archExplore'
import { calibrationApi } from '../lib/calibration'
import { libraryApi } from '../lib/library'
import { TimingCompare } from '../components/TimingCompare'
import { BehaviorPage } from './Behavior'
import { ComparePage } from './Compare'
import { PipelinePage } from './Pipeline'

vi.mock('../components/CandidateReview', () => ({ CandidateReview: () => null }))
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

const view: ViewResponse = { level: 1, scenario_id: 's', variant_id: 'v', nodes: [], edges: [],
  summary: { name: 'Test', subtitle: '', period_ms: 1000 / 30, budget_ms: 1000 / 30, fps: 30 } }
const ctx: Ctx = { project: 'p', scenario: 's', variant: 'v', params: {}, navigate: vi.fn(), openPicker: vi.fn(), setProject: vi.fn(),
  projects: [], catalog: [], allCatalog: [{ project_id: 'p', scenario_id: 's', scenario_name: 'Test', variant_count: 2,
    category: [], domain: [], severity_counts: {}, node_count: 0, edge_count: 0, buffer_count: 0 }] }
const heavyFields = ['calculation_trace', 'dma_breakdown', 'ip_breakdown', 'timing_breakdown', 'dvfs_breakdown', 'external_devices',
  'cpu_breakdown', 'sw_task_timing', 'hw_task_timing', 'stage_timing', 'sw_event_latency', 'handoff_flows', 'pipeline_model'] as const
const pipe = (id: string, node = 'panel', duration = 2): Evidence => ({ id, kind: 'evidence.simulation', kpi: { total_power_mw: 1234 },
  timeline_events: Array.from({ length: 4 }, (_, f) => [
    { task_id: `sensor#${f}`, node_id: 'sensor', frame_index: f, start_ms: f * 33, end_ms: f * 33 + 1 },
    { task_id: `${node}#${f}`, node_id: node, frame_index: f, start_ms: f * 33 + 1, end_ms: f * 33 + 1 + duration },
  ]).flat() })
const summary = (e: Evidence): EvidenceSummary => {
  const { handoff_flows, ...rest } = e
  return { ...rest, heavy: Object.fromEntries(heavyFields.map((f) => [f, { present: f === 'handoff_flows' && !!handoff_flows, bytes: 0 }])) as EvidenceSummary['heavy'] }
}
const handoff = (name: string): HandoffDoc => ({ format: 'sdb.handoff/1', generator: name,
  participants: [{ id: 'hal', layer: 'hal', name: 'Audio HAL' }], cadences: [{ id: 'frame', name: 'Frame', kind: 'frame', period_ms: 33 }],
  flows: [{ id: 'audio', name, cadence: 'frame', steps: [{ to: 'hal', task: 'audio.read' }] }] })
let host: HTMLDivElement, root: ReturnType<typeof createRoot>
beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
  vi.spyOn(api, 'view').mockResolvedValue(view)
  vi.spyOn(api, 'scenario').mockResolvedValue({ id: 's', pipeline: { nodes: [] } })
  vi.spyOn(api, 'variant').mockResolvedValue({ id: 'v', scenario_id: 's' })
  vi.spyOn(api, 'variants').mockResolvedValue({ items: [{ id: 'v', scenario_id: 's' }, { id: 'v2', scenario_id: 's' }], total: 2 })
  vi.spyOn(api, 'simConfigs').mockResolvedValue({ items: [], total: 0 })
  vi.spyOn(libraryApi, 'socs').mockResolvedValue({ items: [], total: 0 })
  vi.spyOn(calibrationApi, 'ipBandwidth').mockResolvedValue({ scenario_id: 's', variant_id: 'v', rows: [], note: '',
    simulation: null, measurement: null, measurements: [], unmatched: [] })
  vi.spyOn(calibrationApi, 'coverage').mockResolvedValue({})
  vi.spyOn(archApi, 'board').mockResolvedValue({ rows: [] })
})
afterEach(() => { act(() => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
const render = async (node: ReactNode) => { await act(async () => { root.render(node) }) }
async function choose(label: string, value: string) {
  await act(async () => {
    const select = host.querySelector<HTMLSelectElement>(`select[aria-label="${label}"]`)!
    select.value = value; select.dispatchEvent(new Event('change', { bubbles: true }))
  })
}
function evidenceRows(rows: Evidence[]) {
  vi.spyOn(api, 'evidenceList').mockResolvedValue({ items: rows.map(summary), total: rows.length })
  return vi.spyOn(api, 'evidence').mockImplementation(async (id) => rows.find((r) => r.id === id)!)
}

it('Pipeline lists once, shows loading, and opens only the selected trace with the same timeline labels', async () => {
  localStorage.setItem('sdb.pipeline.mode', '"timing"')
  const first = pipe('first'), second = pipe('second', 'mfc_enc')
  const detail = evidenceRows([first, second])
  let finish!: (e: Evidence) => void
  detail.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
  await render(<PipelinePage ctx={ctx} />)
  expect(api.evidenceList).toHaveBeenCalledTimes(1)
  expect(detail.mock.calls).toEqual([['first']])
  expect(host.textContent).toContain('Evidence 불러오는 중…')
  expect(host.querySelector('.tl')).toBeNull()
  await act(async () => { finish(first) })
  expect(host.querySelector('.tl')?.textContent).toContain('PANEL')
  expect(host.querySelector('select[aria-label="timing evidence"]')?.textContent).toContain('calculated · 4f · first')
  await choose('timing evidence', 'second')
  expect(detail.mock.calls).toEqual([['first'], ['second']])
  expect(api.evidenceList).toHaveBeenCalledTimes(1)
  expect(host.querySelector('.tl')?.textContent).toContain('MFC_ENC')
})

it('Behavior opens the selected hand-off document from detail, including a hand-off-only row', async () => {
  const first = { ...pipe('stack'), handoff_flows: handoff('First hand-off') }
  first.timeline_events!.forEach((e) => { e.layer = 'hal' })
  const second: Evidence = { id: 'flow-only', kind: 'evidence.measurement', handoff_flows: handoff('Second hand-off') }
  const detail = evidenceRows([first, second, { id: 'unrelated', kind: 'evidence.measurement' }])
  await render(<BehaviorPage ctx={{ ...ctx, params: { tab: 'flow' } }} />)
  expect(api.evidenceList).toHaveBeenCalledTimes(1)
  expect(detail.mock.calls).toEqual([['stack']])
  expect(host.textContent).toContain('First hand-off')
  await choose('full-stack trace', 'flow-only')
  expect(detail.mock.calls).toEqual([['stack'], ['flow-only']])
  expect(api.evidenceList).toHaveBeenCalledTimes(1)
  expect(host.textContent).toContain('Second hand-off')
  expect(host.textContent).not.toContain('First hand-off')
})

it('Compare lists each compared item once and opens only its displayed timing evidence', async () => {
  const best = pipe('best'), shorter = { ...pipe('shorter', 'csis'), kpi: { total_power_mw: 999 } }
  const detail = evidenceRows([best, shorter])
  await render(<ComparePage ctx={{ ...ctx, params: { items: 's~v,s~v2' } }} />)
  expect(vi.mocked(api.evidenceList).mock.calls).toEqual([['s', 'v', 'p'], ['s', 'v2', 'p']])
  expect(detail.mock.calls).toEqual([['best'], ['best']])
  expect(host.textContent).toContain('1234')
  expect(host.textContent).toContain('calculated · 4f')
  expect(host.textContent).not.toContain('Evidence 불러오는 중…')
})

it('TimingCompare opens only its selected prediction and measurement and keeps duration values', async () => {
  const a = pipe('prediction'), a2 = pipe('prediction2', 'panel', 3)
  const b = { ...pipe('measurement', 'panel', 4), kind: 'evidence.measurement' }
  const detail = evidenceRows([a, a2, b])
  await render(<TimingCompare traces={[a, a2, b].map(summary)} fps={30} laneOfPid={() => 'display'} />)
  expect(detail.mock.calls).toEqual([['prediction'], ['measurement']])
  const row = host.querySelector('table[aria-label="IP별 오차"] tbody tr')!
  expect(row.textContent).toContain('2.00')
  expect(row.textContent).toContain('4.00')
  await choose('예측 trace', 'prediction2')
  expect(detail.mock.calls).toEqual([['prediction'], ['measurement'], ['prediction2']])
  expect(host.querySelector('table[aria-label="IP별 오차"] tbody tr')?.textContent).toContain('3.00')
})
