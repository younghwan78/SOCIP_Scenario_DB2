import { describe, expect, it } from 'vitest'
import { DEFAULT_RUN, coverageOf, promoteTargets, runBody, type VariantResult } from './archExplore'

const v = (o: Partial<VariantResult>) => o as VariantResult

describe('power coverage', () => {
  it('prefers the server status', () => expect(coverageOf(v({ status: { power_coverage: 'complete' } as VariantResult['status'], coverage: { zero_power_ips: ['x'], hw_power_modeled: true, cpu_power_modeled: true } }))).toBe('complete'))
  it('derives partial from zero-power IPs on older runs', () => expect(coverageOf(v({ coverage: { zero_power_ips: ['mlsc'], hw_power_modeled: true, cpu_power_modeled: true } }))).toBe('partial'))
  it('none when no IP is modeled', () => expect(coverageOf(v({ coverage: { zero_power_ips: [], hw_power_modeled: false, cpu_power_modeled: true } }))).toBe('none'))
  it('unknown without coverage', () => expect(coverageOf(v({}))).toBeUndefined())
})

describe('bulk promote targets', () => {
  it('only spec-OK variants with a recommendation', () => {
    const run = { variants: [v({ variant_id: 'a', spec_ok: true, recommended: {} as VariantResult['recommended'] }), v({ variant_id: 'b', spec_ok: false, recommended: null }), v({ variant_id: 'c', spec_ok: true, recommended: null })] }
    expect(promoteTargets(run).map((x) => x.variant_id)).toEqual(['a'])
  })
})

describe('customer budget (EXP-05)', () => {
  it('sends power / BW budgets and the per-variant reference flag only when set', () => {
    const plain = runBody(['s'], '', '', DEFAULT_RUN) as { spec: { constraints: Record<string, unknown> }; power_budget_from_reference?: boolean }
    expect(plain.spec.constraints).toEqual({ allow_lossy: true })
    expect(plain.power_budget_from_reference).toBeUndefined()
    const b = runBody(['s'], '', '', { ...DEFAULT_RUN, power_budget_mw: 1800, bw_budget_mbs: 9000, budget_from_reference: true }) as typeof plain
    expect(b.spec.constraints).toEqual({ allow_lossy: true, power_budget_mw: 1800, bw_budget_mbs: 9000 })
    expect(b.power_budget_from_reference).toBe(true)
  })
})
