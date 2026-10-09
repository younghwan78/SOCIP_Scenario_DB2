import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { defaultPicks } from './PowerFit'
import { RecomputePanel } from './RecomputePanel'
import { conditionParams, conditionText, type BoardRow } from '../lib/archExplore'
import type { PowerFit } from '../lib/calibration'

const fit = { base_params_ref: 'pmp@2', statistic: 'mean', measured_sw: true, rows: [], errors: [], warnings: [],
  factors: { cpu: { k: 0.9, n: 35, recommended: false }, ip: { k: 1.27, n: 35, recommended: true }, bw: { k: 0.43, n: 35, recommended: true } } } as unknown as PowerFit

it('pre-selects only the factors that explain the measurements better', () => {
  expect(defaultPicks(fit)).toEqual({ cpu: false, ip: true, bw: true })
})

it('offers stale rows first and the calibrated params for recompute', () => {
  const rows = [{ id: 'p1', variant_id: 'v1' }, { id: 'p2', variant_id: 'v2' }] as BoardRow[]
  const html = renderToStaticMarkup(createElement(RecomputePanel, { rows, staleIds: new Set(['p2']), initialParams: 'pmp@3',
    params: [{ id: 'pmp', version: 3, ref: 'pmp@3', soc_ref: 's', status: 'draft', description: null, calibrated: true, ip_power_scale: { '*': 1.27 } }],
    onDone: () => {}, onClose: () => {} }))
  expect(html).toContain('입력 변경(stale) 1')
  expect(html).toContain('1건 재계산')
  expect(html).toMatch(/<option value="pmp@3" selected="">pmp@3 · 보정 · draft/)
})

it('re-opens a condition registered with explicit power params', () => {
  const row = { scenario_id: 's', variant_id: 'v', condition: { source: 'timing-budget', statistic: 'max', runtime_scale: 1, throughput_model: 'pipelined', eis: 'auto', cpu_model: 'flat',
    rt_margin: 0.25, output_margin: 0.25, config_profile_ref: null, dvfs_overrides: {}, dvfs: {}, compression: [], power_params_ref: 'pmp@3' } } as unknown as BoardRow
  expect(conditionParams(row)).toMatchObject({ pp: 'pmp@3' })
  expect(conditionText(row.condition)).toContain('params pmp@3')
})
