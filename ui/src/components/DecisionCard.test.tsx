// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import type { ExpCase, VariantResult } from '../lib/archExplore'
import { conclusion, defaultCase } from '../lib/conclusion'
import { ExplorationDecision } from './DecisionCard'
import { ParetoScatter, scatterPoints } from './ParetoScatter'

const kase = (key: string, over: Partial<ExpCase> = {}): ExpCase => ({
  key, statistic: 'max', runtime_scale: 1, compression: [], dvfs: { MIF: 3 }, dvfs_raise: 0, total_mw: 1000, cpu_mw: 300, hw_mw: 500,
  bw_mw: 200, bw_mbs: 5000, lossy: false, assumed_ratio: false, verdict: 'ok', eligible: true, ...over,
})
const base = kase('base', { total_mw: 1200, bw_mbs: 6000 })
const low = kase('low', { total_mw: 1098.4, bw_mbs: 5200, compression: ['B1'] })
const robust = kase('robust', { total_mw: 1167.4, bw_mbs: 5200, compression: ['B1'], dvfs_raise: 2, lossy: true })
const variant = (over: Partial<VariantResult> = {}): VariantResult => ({
  scenario_id: 's', variant_id: 'v', fps: 60, period_ms: 16.7, eis_on: false, mfc_dual: false, spec_ok: true, spec_reasons: [],
  counts: { cases: 10, eligible: 8, sw_slices: 1, compression_sets: 2, dvfs_sets: 5 }, distribution: {} as never,
  baseline: base, recommended: low, alternatives: [], slices: [], buffers: [], domains: [], axis_spread: {} as never,
  sw_margin: {} as never, warnings: [], input_hash: 'h', ...over,
})

function render(node: React.ReactElement) {
  const host = document.createElement('div')
  const root = createRoot(host)
  act(() => root.render(node))
  return { host, done: () => act(() => root.unmount()) }
}

it('registers the lowest-power case by default, also when the objective order recommends another one', () => {
  expect(defaultCase(variant(), false)?.key).toBe('low')
  const ordered = variant({ recommended: robust, min_power_case: low, objectives: { order: ['growth', 'power'] } as never })
  expect(defaultCase(ordered, false)?.key).toBe('low')
  const keep = kase('keep', { total_mw: 1110 })
  expect(defaultCase(variant({ tiers: { keep: { best: keep } } as never }), true)?.key).toBe('keep')
  const c = conclusion(ordered, false)
  expect(c.target?.key).toBe('low')
  expect(c.rule).toBe('auto:min-power')
  expect(c.objective?.case.key).toBe('robust')
  expect(c.cautions[c.cautions.length - 1]).toContain('추천 기준(growth → power)의 추천은 다른 조합 (+69.0 mW)')
  expect(c.delta).toEqual({ total_mw: low.total_mw - 1200, total_pct: (100 * (low.total_mw - 1200)) / 1200, bw_mbs: -800 })
})

it('keeps three cautions in their order of weight and counts the rest', () => {
  const bad = kase('bad', { lossy: true, assumed_ratio: true, compression: ['B1'], dvfs_raise: 1, verified: { ok: false, reasons: ['power 3% off'] } as never })
  const c = conclusion(variant({ recommended: bad, coverage: { zero_power_ips: ['GPU', 'NPU'], hw_power_modeled: true, cpu_power_modeled: true, power_coverage: 'partial' } }), false)
  expect(c.cautions).toEqual([
    '부분 모델 — 전력 미모델 IP 2개 (GPU, NPU), total은 하한',
    'lossy 압축 포함 — IQ 평가 필요',
    '가정 compression ratio 사용 — catalog에 없는 ratio',
  ])
  expect(c.more).toBe(1)
  const complete = { zero_power_ips: [], hw_power_modeled: true, cpu_power_modeled: true, power_coverage: 'complete' as const }
  expect(conclusion(variant({ recommended: kase('clean'), coverage: complete }), false).cautions).toEqual([])
  // no power model at all, and an older result that never recorded its coverage, are not "no caution"
  expect(conclusion(variant({ coverage: { ...complete, hw_power_modeled: false, power_coverage: 'none' } }), false).cautions[0]).toContain('전력 모델 없음')
  expect(conclusion(variant(), false).cautions[0]).toBe('전력 모델 범위 미확인 (coverage 기록 이전 결과)')
})

it('fails the decision when the registered case itself failed re-simulation, though the variant passed', () => {
  // objective order: the recommendation verified, the lowest-power case the server would register did not
  const unverified = kase('low', { total_mw: 1098.4, verified: { ok: false, reasons: ['bw 2% off'] } as never })
  const c = conclusion(variant({ recommended: robust, min_power_case: unverified, objectives: { order: ['growth', 'power'] } as never }), false)
  expect(c.verdict).toBe('fail')
  expect(c.registrable).toBe(false)
  expect(c.reasons).toEqual(['기본 등록 조합 재시뮬레이션 검증 실패 — bw 2% off'])
  expect(conclusion(variant(), false).registrable).toBe(true)
  expect(conclusion(variant({ spec_ok: false, spec_reasons: ['x'] }), false).registrable).toBe(false)
})

it('shows target, verdict, delta, cautions and the action in one card', () => {
  const failing = variant({ spec_ok: false, spec_reasons: ['ISP stage over period', 'MIF short'], recommended: null })
  const { host, done } = render(<ExplorationDecision c={conclusion(failing, false)} action={<button>등록</button>} />)
  expect(host.textContent).toContain('등록할 eligible 조합 없음')
  expect(host.textContent).toContain('ISP stage over period · MIF short')
  done()
  const complete = { zero_power_ips: [], hw_power_modeled: true, cpu_power_modeled: true, power_coverage: 'complete' as const }
  const ok = render(<ExplorationDecision c={conclusion(variant({ coverage: complete }), false)} action={<button>등록</button>} />)
  const text = ok.host.textContent!
  expect(text).toContain('1098.4 mW · 최저 power (auto:min-power)')
  expect(text).toContain('-101.6 mW (-8.5%) · BW -800 MB/s')
  expect(text).toContain('주의 사항 없음')
  expect(ok.host.querySelector('.decision-action button')!.textContent).toBe('등록')
  ok.done()
})

it('plots each listed case once against the chosen axis and marks the roles', () => {
  const v = variant({ recommended: robust, min_power_case: low, alternatives: [low], pareto: [{ ...robust, iq_risk: 3 }] })
  const pts = scatterPoints(v, 'iq', { low: '기본 등록', robust: '추천' })
  expect(pts.map((p) => [p.key, p.y, p.roles])).toEqual([['robust', 3, ['추천']], ['low', 1, ['기본 등록']], ['base', 0, []]])
  expect(scatterPoints(v, 'growth', {})).toEqual([]) // no growth_fixed without an objective order
  const { host, done } = render(<ParetoScatter v={v} marks={{ low: '기본 등록' }} />)
  expect(host.querySelectorAll('circle').length).toBe(3)
  expect([...host.querySelectorAll('[role=tab]')].map((b) => b.textContent)).toEqual(['BW MB/s', 'IQ risk'])
  done()
})

it('adds the registered case the lists may not hold, and offers only axes with two points', () => {
  const keep = kase('keep', { total_mw: 1110, bw_mbs: 5600 })
  const v = variant({ recommended: low, alternatives: [] })
  expect(scatterPoints(v, 'bw', { keep: '기본 등록' }, [keep]).find((p) => p.key === 'keep')?.roles).toEqual(['기본 등록'])
  // growth is known for one eligible case only: the axis is not offered, the others stay selectable
  const grown = variant({ recommended: { ...low, growth_fixed: 1.2 } as ExpCase, alternatives: [] })
  const { host, done } = render(<ParetoScatter v={grown} marks={{}} extra={[keep]} />)
  expect([...host.querySelectorAll('[role=tab]')].map((b) => b.textContent)).toEqual(['BW MB/s', 'IQ risk'])
  expect(host.querySelectorAll('circle').length).toBe(3)
  done()
})
