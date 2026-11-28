// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it } from 'vitest'
import { JobCard, jobSpan, peakWindow } from './JobCard'
import type { EventJob, KpiResult } from '../lib/timingBudget'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

const job = (o: Partial<EventJob> = {}): EventJob => ({
  id: 'still_shot', model: 'job-v1', label: '12M shot', milestones: { saved: 56.307, thumbnail: 22.974 }, makespan_ms: 56.307,
  phases: [{ id: 'process', start_ms: 9.85, end_ms: 22.974 }, { id: 'encode', start_ms: 22.974, end_ms: 52.974 }, { id: 'store', start_ms: 52.974, end_ms: 56.307 }],
  stages: [
    { id: 'reproc', phase: 'process', kind: 'hw', nodes: ['byrp'], chunks: 1, start_ms: 9.85, end_ms: 11.079, service_ms: 1.229, elapsed_ms: 1.229, clock_mhz: { byrp: 1066 }, energy_mj: 4.5, mb: 28.07, energy_attributed: true, value_source: 'assumed' },
    { id: 'post', phase: 'process', kind: 'hw', nodes: ['msnr'], chunks: 1, start_ms: 15, end_ms: 22.974, service_ms: 3.275, elapsed_ms: 7.974, clock_mhz: { msnr: 800 }, energy_mj: 1.48, mb: 37.4, energy_attributed: true, value_source: 'measured' },
    { id: 'enc', phase: 'encode', kind: 'sw', nodes: ['post_proc'], chunks: 1, start_ms: 22.974, end_ms: 52.974, service_ms: 30, elapsed_ms: 30, clock_mhz: {}, energy_mj: 18, mb: 22.7, energy_attributed: true, value_source: 'assumed' },
  ],
  energy_mj: { event: 24.815, by_kind: { hw: 5.98, sw: 18, transfer: 0.83 }, unattributed: [] },
  peak: { window_ms: 10, power_mw: 1151.8, power_instant_mw: 4214.6, bw_mbs: 5655.6, bw_instant_mbs: 24246.5, footprint_mb: 112.3 },
  background: { power_mw: 551.75, bw_mbs: 1403.6, rt_wait_max_ms: 0, dropped_frames: 0, priority: 'rt' },
  series: { dt_ms: 1, power_mw: [...Array(10).fill(550), 4200, 4200, ...Array(46).fill(550)], bw_mbs: Array(58).fill(1400) },
  basis: 'job-v1: background = steady', ...o,
})
const kpis: KpiResult[] = [
  { id: 'saved-12m', kpi: 'event_latency', metric: null, job: 'still_shot', milestone: 'saved', status: 'pass', value: 56.3, target: 500, bound: 'max', unit: 'ms', value_source: 'assumed', basis: null, sources: [] },
]

function render(jobs: EventJob[]) {
  const el = document.createElement('div')
  act(() => createRoot(el).render(<JobCard jobs={jobs} kpis={kpis} />))
  return el
}

describe('JobCard (X-02)', () => {
  it('draws stage bars, milestones, series and the stage table with sources', () => {
    const el = render([job()])
    expect(el.textContent).toContain('makespan 56.31 ms')
    expect(el.textContent).toContain('saved 56.31 ms ≤ 500')
    expect(el.textContent).toContain('thumbnail 22.97 ms')
    expect(el.textContent).toContain('stage 출처: 실측 1 / 3')
    const bar = el.querySelector('[data-testid="job-bar-post"]') as HTMLElement
    // span = 58 ms (the series runs past the 56.3 ms makespan): 15 / 58
    expect(bar.style.left).toMatch(/^25\.86/)
    expect(bar.title).toContain('대기 4.70 ms')
    expect(el.querySelector('[data-testid="job-row-post"]')?.textContent).toContain('실측')
    expect(el.querySelector('[data-testid="job-row-enc"]')?.textContent).toContain('가정')
    expect(el.querySelectorAll('svg[aria-label$="시계열"]').length).toBe(2)
    expect(el.querySelector('[data-testid="job-peak"]')?.textContent).toContain('1152 / 4215 mW')
    expect(el.querySelector('[data-testid="job-background"]')?.textContent).toContain('drop 0 frame')
  })

  it('offers a picker for several jobs', () => {
    const el = render([job(), job({ id: 'burst', label: 'burst', stages: [] })])
    const buttons = [...el.querySelectorAll('[aria-label="event job"] button')] as HTMLButtonElement[]
    expect(buttons.map((b) => b.textContent)).toEqual(['still_shot', 'burst'])
    act(() => buttons[1].click())
    expect(el.querySelector('[data-testid="job-burst"]')).not.toBeNull()
  })

  it('span and peak window follow the series', () => {
    expect(jobSpan(job())).toBe(58)
    // samples 10 and 11 are high: the first 10 ms window that holds both starts at 2
    expect(peakWindow(job())).toEqual({ start_ms: 2, end_ms: 12 })
    expect(peakWindow(job({ series: undefined }))).toBeNull()
  })
})
