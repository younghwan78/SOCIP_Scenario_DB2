import { describe, expect, it } from 'vitest'
import { coverageOf, promoteTargets, type VariantResult } from './archExplore'

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
