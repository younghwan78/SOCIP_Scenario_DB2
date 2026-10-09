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
  expect(html).toContain('BW ×0.8: -50.0 mW')
  expect(html).not.toContain('-650.0 mW')
})

it('waits for a matching unscaled baseline before showing shaping deltas', () => {
  expect(render([run('old', 1, 900), run('new', 0.8, 250)])).not.toContain('BW ×0.8:')
})
