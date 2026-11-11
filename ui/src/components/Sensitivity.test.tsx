// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { SensitivityTornado, type Sensitivity } from './Sensitivity'

const data: Sensitivity = {
  method: 'linear', pct: 20, voltage_pct: 5, total_mw: 1000, limits: { 'power budget': 1040 },
  rows: [
    { key: 'sw:runtime', label: 'SW timing (가정 1/2 task)', source: 'assumed', step_pct: 20, component_mw: 300, delta_low_mw: -60, delta_high_mw: 60,
      swing_mw: 120, swing_pct: 12, break_even_pct: { 'power budget': 13.3 }, crosses: ['power budget'],
      timing: { growth_tolerance: 1.1, break_even_pct: 10, at_least: false, fails_at_high: true } },
    { key: 'ip:mfc', label: 'mfc unit power', source: 'IP catalog', step_pct: 20, component_mw: 150, delta_low_mw: -30, delta_high_mw: 30,
      swing_mw: 60, swing_pct: 6, break_even_pct: { 'power budget': 26.7 }, crosses: [] },
  ],
}

it('lists the inputs with their swing and what each one changes', () => {
  const host = document.createElement('div')
  const root = createRoot(host)
  act(() => root.render(<SensitivityTornado data={data} />))
  const rows = [...host.querySelectorAll('tbody tr')].map((tr) => tr.textContent)
  expect(rows[0]).toContain('SW timing (가정 1/2 task)')
  expect(rows[0]).toContain('power budget 넘김')
  expect(rows[0]).toContain('SW +20%면 timing 미달')
  expect(rows[1]).toContain('power budget까지 +27%')
  expect(host.querySelector('[role="img"]')!.getAttribute('aria-label')).toBe('SW timing (가정 1/2 task): -60.0 ~ +60.0 mW')
  expect(host.textContent).toContain('기준 total 1000.0 mW · power budget 1040 mW')
  act(() => root.unmount())
})
