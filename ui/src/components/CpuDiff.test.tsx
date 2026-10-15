// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { CpuDiffView } from './CpuDiff'
import { cpuSideOf, type CpuPick } from '../lib/cpuDiff'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
const row = (task: string, a: number, T = 33.33, k = 300) => ({ task, cluster: 'MID_LF1', active_ms: a, util: a / T, power_mw: (k * a) / T })
const simPick = (rows: ReturnType<typeof row>[]): CpuPick => {
  const pb = { cpu: { total_mw: rows.reduce((s, r) => s + r.power_mw, 0), by_cluster: { MID_LF1: rows.reduce((s, r) => s + r.power_mw, 0) } } }
  return { side: cpuSideOf({ power_breakdown: pb, cpu_breakdown: rows }, pb), source: 'sim', state: 'ok' }
}
const render = (picks: CpuPick[], onRun = vi.fn()) => {
  const el = document.createElement('div')
  act(() => createRoot(el).render(<CpuDiffView ids={['a', 'b', 'c']} labels={{ a: 'A', b: 'B', c: 'C' }} color={() => '#000'} picks={picks} onRun={onRun} />))
  return el
}

it('offers a CPU run for items without a same-session result and explains a failed reference', () => {
  const onRun = vi.fn()
  const el = render([{ side: null, source: null, state: 'error', error: '422 — basis inputs changed' },
    { side: null, source: null, state: 'none' }, { side: null, source: null, state: 'running' }], onRun)
  expect(el.textContent).toContain('★ A: 예측 실행 실패 — 422 — basis inputs changed')
  const btn = [...el.querySelectorAll('button')].find((b) => b.textContent?.startsWith('CPU 예측 실행'))!
  expect(btn.textContent).toBe('CPU 예측 실행 (2개)')   // the running item is not queued again
  act(() => btn.click())
  expect(onRun).toHaveBeenCalledWith([0, 1])
})

it('splits causes once every item has run, and flags mixed sources', () => {
  const ok = render([simPick([row('eis', 3)]), simPick([row('eis', 4)]), simPick([row('eis', 3, 16.67)])])
  expect(ok.textContent).not.toContain('CPU 예측 실행')
  expect(ok.textContent).toContain('SW 부하')
  expect(ok.textContent).not.toContain('출처 혼합')
  const stored: CpuPick = { side: cpuSideOf(null, { cpu: { total_mw: 30, by_task: { eis: 30 } } }), source: 'stored', state: 'ok' }
  const mixed = render([simPick([row('eis', 3)]), stored, simPick([row('eis', 4)])])
  expect(mixed.textContent).toContain('출처 혼합')
  expect(mixed.textContent).toContain('저장 evidence vs ★ 즉석 실행')
  expect(mixed.textContent).toContain('CPU 예측 실행 (1개)')
})
