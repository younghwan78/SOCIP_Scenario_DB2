import { describe, expect, it } from 'vitest'
import { freqColor, meanMhz, mhzText, oppColor, pickStats, type ClockDomain } from './clockResidency'

const stats = (mean: number) => ({ bins: [{ mhz: mean, ratio: 1 }], mean_mhz: mean, p50_mhz: mean, max_mhz: mean, min_mhz: mean, dominant_mhz: mean, dominant_share: 1, high_share: null })
const dom = (wall: number | null, active: number | null): ClockDomain => ({
  domain_class: 'cpu', class_label: 'CPU', domain: 'MID_LF0', is_dsu: false, opp_max_mhz: 2000,
  wall: wall === null ? null : stats(wall), active: active === null ? null : stats(active),
  active_ratio: null, clock_gated_ratio: null, power_gated_ratio: null, pass_jsd: null, source: null, notes: [],
})

describe('clock residency helpers', () => {
  it('ramp matches the report colours', () => {
    expect(oppColor(0, 4)).toBe('#D7ECE7')
    expect(oppColor(3, 4)).toBe('#174D47')
    expect(oppColor(0, 1)).toBe('#D7ECE7')
    expect(freqColor(2000, 2000, 0, 2)).toBe('#174D47')         // at fmax: darkest whatever its rank
    expect(freqColor(1000, 2000, 1, 2)).toBe(oppColor(10, 21))
    expect(freqColor(1000, null, 1, 2)).toBe('#174D47')         // no fmax: rank
  })
  it('falls back to the available basis', () => {
    expect(pickStats(dom(800, 950), 'active')).toMatchObject({ used: 'active' })
    expect(pickStats(dom(800, null), 'active')).toMatchObject({ used: 'wall' })
    expect(pickStats(dom(null, 950), 'wall')).toMatchObject({ used: 'active' })
  })
  it('formats and averages', () => {
    expect(mhzText(1140)).toBe('1.14 GHz')
    expect(mhzText(948)).toBe('948 MHz')
    expect(mhzText(null)).toBe('—')
    expect(meanMhz([{ mhz: 400, ratio: 0.3 }, { mhz: 1000, ratio: 0.7 }])).toBeCloseTo(820)
  })
})
