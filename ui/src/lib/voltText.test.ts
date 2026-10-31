import { expect, it } from 'vitest'
import { voltText } from './timingBudget'

it('separates the level voltage from a shared VDD rail that raised it (CAM 619 vs 710 mV)', () => {
  expect(voltText({ voltage_mv: 710, level_voltage_mv: 618.75, vdd: 'VDD_CAM', vdd_leader: 'csis,pdp' })).toBe('619 → 710 mV (VDD_CAM: CSIS, PDP)')
  expect(voltText({ voltage_mv: 637.5, level_voltage_mv: 637.5, vdd: null, vdd_leader: null })).toBe('638 mV')
  // older API without the level voltage: the rail value as before
  expect(voltText({ voltage_mv: 710 })).toBe('710 mV')
})
