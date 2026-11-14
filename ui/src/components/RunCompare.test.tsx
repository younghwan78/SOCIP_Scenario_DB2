// @vitest-environment jsdom
import { act, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import type { RunDetail, RunMeta, VariantResult } from '../lib/archExplore'
import { useAsync } from '../lib/route'
import { RunList, lineageDiff, runDelta } from './RunCompare'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

const meta = (id: string, over: Partial<RunMeta> = {}): RunMeta => ({
  id, title: `run ${id}`, scenario_type: 'Camera', project_ref: 'p', soc_ref: 'soc', dvfs_table_ref: 'dvfs-v0', engine_rev: 'arch-exploration/15',
  created_by: null, created_at: '2026-11-14T10:00:00', config_profile_ref: null,
  summary: { variants: 2, errors: 0, spec_ok: 2, cases: 1200, eligible_cases: 900, verified: 2, recommended_power_mw: [750, 1010] }, ...over,
})
const variant = (id: string, mw: number | null, spec = true) => ({ scenario_id: 's', variant_id: id, spec_ok: spec,
  recommended: mw == null ? null : { total_mw: mw } }) as unknown as VariantResult
const detail = (m: RunMeta, variants: VariantResult[]) => ({ ...m, spec: {}, variants, errors: [] }) as RunDetail

it('compares the recommended total per variant, largest change first, and keeps one-sided variants', () => {
  const a = detail(meta('a'), [variant('uhd30', 752.8), variant('fhd30', 462.0), variant('only-a', 100)])
  const b = detail(meta('b'), [variant('uhd30', 760.0), variant('fhd30', 470.5, false), variant('only-b', 90)])
  const rows = runDelta(a, b)
  expect(rows.map((r) => [r.variant_id, r.delta_mw === null ? null : Number(r.delta_mw.toFixed(2))])).toEqual([
    ['fhd30', -8.5], ['uhd30', -7.2], ['only-a', null], ['only-b', null],
  ])
  expect(rows[0]).toMatchObject({ a_spec: true, b_spec: false })
  expect(rows.find((r) => r.variant_id === 'only-b')).toMatchObject({ a_mw: null, a_spec: null, b_mw: 90 })
})

it('names what differs in how two runs were computed', () => {
  expect(lineageDiff(meta('a'), meta('b'))).toEqual([])
  expect(lineageDiff(meta('a', { engine_rev: 'arch-exploration/14', config_profile_ref: 'p2' }), meta('b'))).toEqual([
    'engine arch-exploration/14 ≠ arch-exploration/15', 'profile p2 ≠ 기본'])
})

it('lists runs with what tells them apart and offers a comparison against the selected run', () => {
  const host = document.createElement('div')
  const root = createRoot(host)
  const onCompare = vi.fn()
  act(() => root.render(<RunList runs={[meta('a'), meta('b', { config_profile_ref: 'thermal' })]} selected="a" onPick={vi.fn()} onCompare={onCompare} />))
  const rows = [...host.querySelectorAll('tbody tr')].map((tr) => [...tr.querySelectorAll('td')].map((td) => td.textContent))
  expect(rows[1].slice(0, 8)).toEqual(['run b', '2026-11-14 10:00', 'thermal', 'rev 15', 'dvfs-v0', '2 / 2', '1,200', '750–1010'])
  expect(rows[0][8]).toBe('') // the selected run has no compare button
  act(() => (host.querySelector('tbody tr:nth-child(2) .btn') as HTMLButtonElement).click())
  expect(onCompare).toHaveBeenCalledWith('b')
  act(() => root.unmount())
})

it('keeps the previous value while the same target refreshes, never across targets (U-08)', async () => {
  const seen: { data?: string; stale?: boolean }[] = []
  let resolve: (v: string) => void = () => {}
  let refresh: () => void = () => {}
  let switchTarget: () => void = () => {}
  function Probe() {
    const [tick, setTick] = useState(0)
    const [target, setTarget] = useState('v1')
    refresh = () => setTick((t) => t + 1)
    switchTarget = () => setTarget('v2')
    const q = useAsync(() => new Promise<string>((r) => { resolve = r }), [tick, target], { keep: [target] })
    seen.push({ data: q.data, stale: q.stale })
    return null
  }
  const root = createRoot(document.createElement('div'))
  await act(async () => root.render(<Probe />))
  await act(async () => resolve('v1@0'))
  expect(seen[seen.length - 1]).toEqual({ data: 'v1@0', stale: undefined })
  seen.length = 0
  await act(async () => refresh())
  expect(seen.every((s) => s.data === 'v1@0' && s.stale === true)).toBe(true) // shown, dimmed
  await act(async () => resolve('v1@1'))
  expect(seen[seen.length - 1]).toEqual({ data: 'v1@1', stale: undefined })
  seen.length = 0
  await act(async () => switchTarget())
  expect(seen.every((s) => s.data === undefined)).toBe(true) // another target: hidden at once
  act(() => root.unmount())
})
