import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { DvfsWhatIfTable, comboLabel } from './DvfsWhatIf'
import type { DvfsBrief, DvfsWhatIf } from '../lib/timingBudget'
import { DEFAULT_BATTERY } from '../lib/battery'

const brief = (mw: number, peak: number): DvfsBrief => ({
  total_mw: mw, cpu_mw: 100, hw_mw: mw - 200, bw_mw: 100, bw_mbs: 4000, peak_stage_mbs: peak, peak_upper_mbs: peak * 2,
  verdict: 'ok', reasons: [], intervals_ok: true, latency_ms: { preview_ms: null, video_ms: 40 },
  slack_ms: { rt: 1, nrt: 10, post: 8, output: 2 }, stage_hw_ms: { rt: 5, nrt: 6, post: 4, output: 3 },
})
const data: DvfsWhatIf = {
  base: brief(1000, 6000), fps: 30, period_ms: 33.3, throughput_model: 'pipelined',
  domains: [{ domain: 'CAM', level: 0, mhz: 200, mv: 600, ips: ['csis'], stages: ['rt'] }, { domain: 'INTCAM', level: 2, mhz: 400, mv: 700, ips: ['mcsc'], stages: ['nrt'] }],
  rows: [
    { domain: 'CAM', shift: -1, level: null, mhz: null, boundary: '최저 OPP', error: 'CAM: 최저 OPP에서 더 내릴 level 없음' },
    { ...brief(1040, 6500), domain: 'CAM', shift: 1, level: 1, mhz: 300, delta_mw: 40, delta_peak_mbs: 500 },
  ],
  combos: [
    { ...brief(1080, 7000), combo: { CAM: 1, INTCAM: 1 }, label: 'CAM L1 + INTCAM L3', delta_mw: 80, delta_peak_mbs: 1000 },
    { combo: { CAM: -1, INTCAM: -1 }, label: null, error: 'CAM -1: OPP 경계 밖', boundary: '경계' },
  ],
}

it('shows boundary rows as a badge instead of an undefined level (TIM-05)', () => {
  const html = renderToStaticMarkup(createElement(DvfsWhatIfTable, { data, battery: DEFAULT_BATTERY }))
  expect(html).toContain('최저 OPP')
  expect(html).not.toContain('Lnull')
  expect(html).toContain('여러 domain 동시 변경')
  expect(html).toContain('+1000')
  expect(html).toContain('6.00 GB/s')
})

it('labels uniform all-domain presets', () => {
  expect(comboLabel(data.combos![0], 2)).toBe('모든 domain +1 (CAM L1 + INTCAM L3)')
  expect(comboLabel({ combo: { CAM: -1 }, label: null }, 2)).toBe('CAM −1')
})
