// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { Ctx } from '../App'
import { ExplorePage } from './Explore'
import { DEFAULT_RUN, archApi, runBody, type RunDetail, type RunOptions } from '../lib/archExplore'
import { StatusToast } from '../components/StatusToast'
import { dismissStatus, useStatusNotices } from '../lib/status'

vi.mock('../lib/simProfile', async (original) => ({
  ...await original<typeof import('../lib/simProfile')>(),
  useSimProfiles: (_project: string, param?: string) => ({ profiles: [{ id: 'profile', version: 1 }, { id: 'other', version: 2 }], ref: param ?? 'profile', ready: true, basis: null }),
}))
vi.mock('../lib/review', async (original) => ({ ...await original<typeof import('../lib/review')>(), useReferences: () => null }))
vi.mock('../components/ArchCharts', () => ({
  AxisSpread: () => null, BufferSavings: () => null, CompositionBars: () => null, DomainLevels: () => null,
  IpModes: () => null, RangeBoxes: () => null, SplitBar: () => null, SplitLegend: () => null,
}))
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
let host: HTMLDivElement
let root: ReturnType<typeof createRoot>
let notices: ReturnType<typeof useStatusNotices>
function Feedback() { notices = useStatusNotices(); return <StatusToast /> }
const ctx = { project: '', scenario: 's', params: {}, navigate: vi.fn(), catalog: [
  { scenario_id: 's', scenario_name: 'Synthetic', variant_count: 70, category: ['test'] },
  { scenario_id: 'other', scenario_name: 'Other', variant_count: 2, category: ['test'] },
] } as unknown as Ctx
const run: RunDetail = { id: 'new', title: 'Synthetic run', project_ref: '', scenario_type: 'Synthetic', variants: [], errors: [], spec: {},
  summary: { variants: 70, errors: 0, spec_ok: 0, cases: 0, eligible_cases: 0, verified: 0, recommended_power_mw: null } } as unknown as RunDetail
beforeEach(() => {
  host = document.createElement('div'); root = createRoot(host); notices = []
  vi.spyOn(archApi, 'runs').mockResolvedValue([])
  vi.spyOn(archApi, 'board').mockResolvedValue({ rows: [] })
  vi.spyOn(archApi, 'createRun').mockResolvedValue(run)
})
afterEach(() => {
  act(() => root.unmount()); notices.forEach((notice) => dismissStatus(notice.id))
  vi.restoreAllMocks(); sessionStorage.clear(); localStorage.clear()
})
const mount = async (context = ctx) => { await act(async () => root.render(<><ExplorePage ctx={context} /><Feedback /></>)) }
const button = (text: string) => [...host.querySelectorAll('button')].find((item) => item.textContent === text)!
const form = () => host.querySelector<HTMLElement>('[aria-label="새 탐색"]')!
const checkbox = (text: string) => [...form().querySelectorAll('label')].find((label) => label.textContent === text)!.querySelector<HTMLInputElement>('input')!
const changeInput = (input: HTMLInputElement, value: string) => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

it.each([
  ['빠른 점검', { ...DEFAULT_RUN, statistics: ['mean'], runtime_scales: [1], dvfs_headroom_levels: 0, objective_statistic: 'mean', objective_scale: 1, options: { ...DEFAULT_RUN.options, knobs: false, modes: false } }],
  ['표준 검토', DEFAULT_RUN],
  ['전수', { ...DEFAULT_RUN, statistics: ['mean', 'max'], runtime_scales: [1, 1.1, 1.2, 1.3, 1.5], dvfs_headroom_levels: 2, modes: ['lossless', 'lossy'], options: { ...DEFAULT_RUN.options, knobs: true, modes: true } }],
] as [string, RunOptions][])('sets %s controls and keeps the existing request encoding', async (label, expected) => {
  await mount()
  act(() => button(label).click())
  expect(button(label).getAttribute('aria-pressed')).toBe('true')
  for (const statistic of ['mean', 'max']) expect(checkbox(statistic).checked).toBe(expected.statistics.includes(statistic as 'mean' | 'max'))
  for (const scale of [1, 1.1, 1.2, 1.3, 1.5]) expect(checkbox(`×${scale.toFixed(1)}`).checked).toBe(expected.runtime_scales.includes(scale))
  expect(button(`+${expected.dvfs_headroom_levels} level`).className).toBe('on')
  expect(button(`SW ${expected.objective_statistic}`).className).toBe('on')
  for (const mode of ['lossless', 'lossy']) expect(checkbox(mode).checked).toBe(expected.modes.includes(mode as 'lossless' | 'lossy'))
  expect(checkbox('arch knob (bcrop, L0 skip …)').checked).toBe(expected.options.knobs)
  expect(checkbox('IP mode (대체 가능 mode · unit power별)').checked).toBe(expected.options.modes)
  await act(async () => button('탐색 실행').click())
  expect(archApi.createRun).toHaveBeenCalledWith(runBody(['s'], '', 'Synthetic', expected, 'profile'))
})

it.each([
  ['빠른 점검', ['mean'], [1.0]],
  ['전수', ['mean', 'max'], [1.0, 1.1, 1.2, 1.3, 1.5]],
] as [string, RunOptions['statistics'], number[]][])('submits exactly the %s axes with its objective inside them', async (label, statistics, scales) => {
  await mount()
  act(() => button(label).click())
  await act(async () => button('탐색 실행').click())
  const { axes, objective } = vi.mocked(archApi.createRun).mock.calls[0][0].spec
  expect(axes.statistics).toEqual(statistics)
  expect(axes.runtime_scales).toEqual(scales)
  expect(axes.statistics).toContain(objective.statistic)
  expect(axes.runtime_scales).toContain(objective.runtime_scale)
  if (label === '빠른 점검') expect(objective).toEqual({ statistic: 'mean', runtime_scale: 1.0 })
})

it('preserves the standard default request snapshot', async () => {
  await mount()
  await act(async () => button('탐색 실행').click())
  expect(vi.mocked(archApi.createRun).mock.calls[0][0]).toMatchInlineSnapshot(`
    {
      "config_profile_ref": "profile",
      "scenario_ids": [
        "s",
      ],
      "scenario_type": "Synthetic",
      "spec": {
        "axes": {
          "compression": {
            "enabled": true,
            "max_buffers": 6,
            "modes": [
              "lossless",
              "lossy",
            ],
            "require_declared": true,
          },
          "dvfs_headroom_levels": 1,
          "power_options": {
            "enabled": true,
            "include_knobs": true,
            "include_modes": true,
            "max_sets": 64,
          },
          "runtime_scales": [
            1,
            1.1,
            1.2,
          ],
          "statistics": [
            "mean",
            "max",
          ],
        },
        "constraints": {
          "allow_lossy": true,
        },
        "objective": {
          "runtime_scale": 1,
          "statistic": "max",
        },
      },
      "title": undefined,
    }
  `)
})

it.each(['title', 'scenario', 'profile'].flatMap((field) => [false, true].map((open) => ({ field, open }))))('keeps the preset and advanced open=$open when $field changes', async ({ field, open }) => {
  await mount()
  act(() => button('빠른 점검').click())
  if (open) act(() => form().querySelector('summary')!.click())
  expect(form().querySelector('details')!.open).toBe(open)
  act(() => {
    if (field === 'title') changeInput(form().querySelector<HTMLInputElement>('input[placeholder="Synthetic exploration"]')!, 'custom')
    else if (field === 'scenario') form().querySelectorAll<HTMLInputElement>('.ax-scen input')[1].click()
    else {
      const select = form().querySelector<HTMLSelectElement>('[aria-label="설정 profile"]')!
      select.value = 'other'; select.dispatchEvent(new Event('change', { bubbles: true }))
    }
  })
  expect(form().textContent).not.toContain('사용자 설정')
  expect(button('빠른 점검').getAttribute('aria-pressed')).toBe('true')
  expect(form().querySelector('details')!.open).toBe(open)
})

it.each(['statistic', 'options'])('marks a changed advanced %s as custom and opens advanced settings', async (field) => {
  await mount()
  expect(form().querySelector('details')!.open).toBe(false)
  act(() => {
    form().querySelector('summary')!.click()
    checkbox(field === 'statistic' ? 'max' : 'arch knob (bcrop, L0 skip …)').click()
  })
  expect(form().textContent).toContain('사용자 설정')
  expect(form().querySelector('details')!.open).toBe(true)
  expect(form().querySelector('[aria-pressed="true"]')).toBeNull()
  act(() => button('표준 검토').click())
  expect(form().querySelector('details')!.open).toBe(false)
  expect(form().textContent).not.toContain('사용자 설정')
})

it('shows catalog variant count and time as upper bounds and keeps the submitted estimate while busy', async () => {
  let finish!: (created: RunDetail) => void
  vi.mocked(archApi.createRun).mockImplementation(() => new Promise((resolve) => { finish = resolve }))
  await mount()
  expect(form().textContent).toContain('variant ≤70 × 최대 34,992 조합 · 예상 최대 약 1분 31초')
  await act(async () => button('탐색 실행').click())
  expect(button('탐색 중… (예상 최대 약 1분 31초)').disabled).toBe(true)
  act(() => form().querySelector<HTMLInputElement>('.ax-scen input')!.click())
  expect(form().textContent).toContain('variant ≤0 × 최대 34,992 조합 · 예상 최대 약 0초')
  expect(button('탐색 중… (예상 최대 약 1분 31초)').disabled).toBe(true)
  await act(async () => finish(run))
  expect(host.querySelector('[aria-label="작업 알림"]')?.textContent).toContain('탐색 완료: Synthetic run · variant 70개')
})

it('announces a failed run in the global alert and leaves the form available', async () => {
  vi.mocked(archApi.createRun).mockRejectedValue(new Error('engine failed'))
  await mount()
  await act(async () => button('탐색 실행').click())
  expect(host.querySelector('[aria-label="작업 알림"] [role="alert"]')?.textContent).toContain('engine failed')
  expect(form().textContent).not.toContain('engine failed')
  expect(button('탐색 실행').disabled).toBe(false)
})

it.each(['ok', 'error'])('announces a bulk registration %s in the global region', async (outcome) => {
  const candidate = { key: 'max@1', total_mw: 100, cpu_mw: 10, hw_mw: 50, bw_mw: 40, compression: [], dvfs: {} }
  const existing = { ...run, variants: [{ scenario_id: 's', variant_id: 'v', fps: 30, spec_ok: true, spec_reasons: [], recommended: candidate, baseline: candidate,
    distribution: { total_mw: { min: 100, max: 100 } }, sw_margin: { worst: null, recommendations: [] } }], summary: { ...run.summary, variants: 1, spec_ok: 1 } } as unknown as RunDetail
  vi.spyOn(archApi, 'run').mockResolvedValue(existing)
  const promote = vi.spyOn(archApi, 'promote')
  if (outcome === 'ok') promote.mockResolvedValue({ promoted: [{ id: 'prediction', variant_id: 'v', total_mw: 100 }], skipped: [] })
  else promote.mockRejectedValue(new Error('registration failed'))
  await mount({ ...ctx, params: { run: 'new' } })
  act(() => button('최저 power 조합 전체 등록…').click())
  await act(async () => button('1개 등록').click())
  expect(promote).toHaveBeenCalledWith('new', undefined, undefined, undefined, undefined, '', [{ scenario_id: 's', variant_id: 'v', prediction_id: null }])
  const region = host.querySelector('[aria-label="작업 알림"]')!
  expect(region.textContent).toContain(outcome === 'ok' ? '1개 variant를 최저 power 조합으로 등록 (건너뜀 0)' : 'registration failed')
  expect(region.querySelector('[role="alert"]') !== null).toBe(outcome === 'error')
})
