import { describe, expect, it } from 'vitest'
import { levers } from './ExploreTiers'
import type { VariantResult } from '../lib/archExplore'

describe('power-first levers', () => {
  it('lists lossy compression and every option by its own effect, strongest first', () => {
    const v = {
      tiers: { keep: null, trade: { best: { compression: ['PYRAMID_L0'] } }, trade_gain: { delta_mw: -59, delta_mbs: -700, iq_risk: 3 } },
      power_options: {
        results: [{ key: 'knob:pyramid_l0=skip', items: ['knob:pyramid_l0=skip'], kinds: ['knob'] }, { key: 'mode:mtnr=LowPower', items: ['mode:mtnr=LowPower'], kinds: ['ip_mode'] }],
        marginal: [
          { key: 'knob:pyramid_l0=skip', label: 'L0 skip', dimension: 'knob:pyramid_l0', contexts: 4, mean_mw: -31, min_mw: -34, max_mw: -28, always_beneficial: true, sign_varies: false, fixed: true },
          { key: 'mode:mtnr=LowPower', label: 'MTNR LP', dimension: 'mode:mtnr', contexts: 4, mean_mw: -1.4, min_mw: -1.5, max_mw: -1.3, always_beneficial: true, sign_varies: false, fixed: true },
        ],
      },
    } as unknown as VariantResult
    const l = levers(v)
    expect(l.map((x) => x.key)).toEqual(['lossy', 'knob:pyramid_l0=skip', 'mode:mtnr=LowPower'])
    expect(l[0].cost).toBe('IQ (lossy)')
    expect(l[2].cost).toBe('IQ (IP mode)')
  })
  it('is empty without tiers or options', () => expect(levers({} as VariantResult)).toEqual([]))
})
