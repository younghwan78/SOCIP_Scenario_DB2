import { describe, expect, it } from 'vitest'
import { batteryOf, DEFAULT_BATTERY, maText, toMa } from './battery'

describe('mA@Vbat', () => {
  it('uses mW / Vbat / efficiency', () => {
    expect(toMa(340)).toBeCloseTo(100)
    expect(maText(1252)).toBe('368 mA')
    expect(maText(-34, DEFAULT_BATTERY, true)).toBe('-10.0 mA')
    expect(maText(null)).toBe('—')
  })
  it('takes Vbat / efficiency from the project profile', () => {
    const b = batteryOf([{ id: 'p', version: 2, run_config: { vbat: 3.85, pmic_efficiency: 0.9 } }], 'p')
    expect(b).toMatchObject({ vbat: 3.85, eff: 0.9, source: 'p' })
    expect(batteryOf([{ id: 'p', run_config: {} }], 'p')).toBe(DEFAULT_BATTERY)
  })
})
