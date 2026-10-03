// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { CpuSweep, SweepCase } from '../src/lib/cpu'
import { applyDsu, expandVote, monotone, proportionalVote, shiftVote, type VoteTable } from '../src/lib/dsu'
import { DsuPanel } from '../src/components/DsuPanel'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
const fx = JSON.parse(readFileSync(join(process.cwd(), 'tests/fixtures/cpu-dsu-sweeps.json'), 'utf-8')) as
  { vote_table: VoteTable; proportional: CpuSweep; measured: CpuSweep; vote: CpuSweep }
const S = (k: 'proportional' | 'measured' | 'vote') => fx[k]
const VOTE = fx.vote_table
const key = (c: SweepCase) => JSON.stringify(c.knobs)
const all = (r: CpuSweep) => [r.reference, r.eas_default, r.measured_placement, ...r.cases, ...r.others]

function expectSame(client: CpuSweep, server: CpuSweep) {
  expect(client.reference.total_mw).toBeCloseTo(server.reference.total_mw, 2)
  expect(client.reference.dsu?.mhz).toBe(server.reference.dsu?.mhz)
  const srv = new Map(all(server).map((c) => [key(c), c]))
  let n = 0
  for (const c of all(client)) {
    const s = srv.get(key(c)); if (!s) continue
    n++
    expect(c.dsu?.mhz).toBe(s.dsu?.mhz)
    expect(c.total_mw).toBeCloseTo(s.total_mw, 2)
  }
  expect(n).toBeGreaterThanOrEqual(4)   // ref, EAS, measured + shared cases (top-N sets differ by rule)
}

describe('client DSU recomputation reproduces the server', () => {
  it('proportional / measured response + vote table = server vote sweep', () => {
    expectSame(applyDsu(S('proportional'), { mode: 'vote', vote: VOTE }), S('vote'))
    expectSame(applyDsu(S('measured'), { mode: 'vote', vote: VOTE }), S('vote'))
  })
  it('vote response -> proportional and measured rules', () => {
    expectSame(applyDsu(S('vote'), { mode: 'proportional' }), S('proportional'))
    expectSame(applyDsu(S('vote'), { mode: 'measured' }), S('measured'))
  })
  it('a vote table filled from the proportional rule gives the proportional result', () => {
    const p = S('vote').dsu_params!
    expectSame(applyDsu(S('vote'), { mode: 'vote', vote: proportionalVote(p) }), S('proportional'))
  })
  it('re-ranks: better = feasible and below the new reference, ascending power', () => {
    const r = applyDsu(S('proportional'), { mode: 'vote', vote: VOTE })
    expect(r.cases.every((c, i) => c.feasible && (c.delta_mw ?? 0) < 0 && c.rank === i + 1)).toBe(true)
    expect(r.cases.map((c) => c.total_mw)).toEqual([...r.cases.map((c) => c.total_mw)].sort((a, b) => a - b))
    expect(r.dsu_model?.source).toBe('experiment')
    expect(applyDsu(S('vote'), null)).toBe(S('vote'))
  })
})

it('vote table helpers', () => {
  const p = S('vote').dsu_params!
  const t = expandVote(VOTE, p)
  expect(Object.keys(t)).toEqual(expect.arrayContaining(['MID_LF0', 'MID_LF1', 'MID_HF', 'BIG']))
  expect(t.MID_LF0).toEqual([[400, 400], [1000, 400], [1600, 900], [2000, 1500]])
  expect(shiftVote(t, p, 1).MID_LF0.map((x) => x[1])).toEqual([900, 900, 1500, 1500])
  expect(shiftVote(t, p, -1).MID_LF0.map((x) => x[1])).toEqual([400, 400, 400, 900])
  expect(monotone([[1, 900], [2, 400], [3, 1500]])).toEqual([[1, 900], [2, 900], [3, 1500]])
})

it('DSU panel: experiment rows, corners and changed-optimum flag', () => {
  const host = document.createElement('div'), root = createRoot(host)
  let exp: Parameters<typeof DsuPanel>[0]['exp'] = null
  const render = () => act(() => root.render(<DsuPanel raw={S('proportional')} exp={exp} setExp={(p) => { exp = p; render() }} onApply={() => {}} applied={null} />))
  render()
  expect(host.querySelectorAll('table[aria-label="DSU 정책 비교"] tbody tr')).toHaveLength(1)
  const sel = host.querySelector<HTMLSelectElement>('select[aria-label="DSU 실험 규칙"]')!
  act(() => { sel.value = 'vote'; sel.dispatchEvent(new Event('change', { bubbles: true })) })
  expect(host.querySelector('table[aria-label="DSU vote 표"]')).not.toBeNull()
  expect(host.querySelectorAll('table[aria-label="DSU 정책 비교"] tbody tr')).toHaveLength(4)   // server, exp, -1, +1
  const cell = host.querySelector<HTMLSelectElement>('select[aria-label="MID_LF0 2000 MHz DSU"]')!
  act(() => { cell.value = '400'; cell.dispatchEvent(new Event('change', { bubbles: true })) })
  expect(exp!.vote!.MID_LF0.map((x) => x[1])).toEqual([400, 400, 400, 400])   // lower cells clamp to the edit
  act(() => root.unmount())
})
