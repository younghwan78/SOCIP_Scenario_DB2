import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it, vi } from 'vitest'
import { OptionResults } from '../src/components/PowerOptions'
import { IpModes, RangeBoxes } from '../src/components/ArchCharts'
import { variantSpecCounts, variantSpecState, type IpModeRow, type OptionResult, type VariantResult } from '../src/lib/archExplore'

vi.mock('../src/components/Charts', async (original) => ({
  ...await original<typeof import('../src/components/Charts')>(),
  useWidth: () => [null, 700],
}))

const option: OptionResult = {
  key: 'audio-option', items: ['mode:abox=LowPower'], labels: ['ABOX LowPower'], kinds: ['ip_mode'], iq_eval: 'not_required',
  spec_ok: false, spec_reasons: [], verdict: 'not_applicable', total_mw: null, delta_mw: -5, delta_pct: null, delta_bw_mbs: 0,
  raw_delta_mw: -5, raw_delta_pct: null, attribution: { reference: 'base', delta_mw: -5, by_category: {}, factors: [] },
}

it('shows the same grey unsupported badge on option and IP-mode result tables', () => {
  const mode = { node: 'abox', hw_name: 'ABOX', dvfs_group: null, mode: 'Normal', unit_power_mw_mp: 1, ppc: 1,
    power_mw: 10, declared: true, alternatives: [{ mode: 'LowPower', unit_power_mw_mp: 0.5, explorable: true }] } as IpModeRow
  const tables = [renderToStaticMarkup(createElement(OptionResults, { results: [option] })),
    renderToStaticMarkup(createElement(IpModes, { rows: [mode], results: [option] }))]
  for (const html of tables) {
    expect(html).toContain('badge v-na')
    expect(html).toContain('timing 판정 미지원')
    expect(html).not.toMatch(/badge v-fail|spec ✗/)
  }
})

it('keeps unsupported range bars neutral instead of colouring them as failures', () => {
  const html = renderToStaticMarkup(createElement(RangeBoxes, { unit: 'mW', rows: [{ id: 'audio', label: 'audio', ok: false,
    verdict: 'not_applicable', dist: { min: 1, p25: 2, median: 3, p75: 4, max: 5 } }] }))
  const chart = html.split('</svg>')[0]
  expect(chart).toContain('#9CA3AF')
  expect(chart).not.toContain('#9B1C1C')
})

it('excludes unsupported variants from the failure count and filter state', () => {
  const variants = [{ spec_ok: false, baseline: { verdict: 'not_applicable' } },
    { spec_ok: false, baseline: { verdict: 'fail' } }, { spec_ok: true, baseline: { verdict: 'clock_up' } }] as VariantResult[]
  expect(variantSpecCounts(variants)).toEqual({ ok: 1, fail: 1, not_applicable: 1 })
  expect(variants.filter((v) => variantSpecState(v) === 'fail')).toEqual([variants[1]])
})
