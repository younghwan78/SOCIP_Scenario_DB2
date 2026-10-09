import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { CpuPurpose, type CpuRun } from './CpuPurpose'

const run = (context: string, bwScale: number, mw: number): CpuRun => ({
  n: mw, profile: context, target: 'target', cmp: null, context, growth: 1, bwScale, pgEff: 0.9,
  ref_mw: mw, best_mw: mw, cmp_ref_mw: null, cmp_best_mw: null, winner: null,
})
const render = (runs: CpuRun[]) => renderToStaticMarkup(createElement(CpuPurpose, {
  rb: null, cmp: null, runs, growth: 1, bwScale: 0.8, onRebalance: () => {}, onPreset: () => {},
}))

it('compares shaping runs only with a baseline from the same complete request context', () => {
  const html = render([run('other-profile', 1, 900), run('current', 1, 300), run('current', 0.8, 250)])
  expect(html).toContain('CPU+DSU -50.0 mW')
  expect(html).not.toContain('-650.0 mW')
})

it('waits for a matching unscaled baseline before showing shaping deltas', () => {
  expect(render([run('old', 1, 900), run('new', 0.8, 250)])).not.toContain('BW ×0.8:')
})

it('labels a BW-scale run whose CPU + DSU power did not move as a BW-only effect (AC-09)', () => {
  const base = { ...run('current', 1, 300), bw_mbs: 1000 }
  const scaled = { ...run('current', 0.8, 300), bw_mbs: 800 }
  const html = render([base, scaled])
  expect(html).toContain('1000→800 MB/s')
  expect(html).toContain('(BW-only)')
})
