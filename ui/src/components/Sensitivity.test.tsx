// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { SensitivityTornado, sourceGrade, type Sensitivity } from './Sensitivity'

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

it('grades inputs by source and shows assumed ones by default (X-13)', () => {
  expect(sourceGrade({ key: 'sw:runtime', source: 'profile / measured' })).toBe('measured')
  expect(sourceGrade({ key: 'sw:runtime', source: 'assumed' })).toBe('assumed')
  // the ratio sources the server emits (arch_exploration ratio_source / sensitivity): all assumed inputs today
  for (const s of ['ratio override', 'ratio typical', 'ratio catalog', 'ratio assumed', 'ratio scenario (현재 압축)', 'BW power model', 'design_conditions', 'domain_load'])
    expect(sourceGrade({ key: s.startsWith('ratio') ? 'ratio:b' : 'x', source: s })).toBe('assumed')
  expect(sourceGrade({ key: 'ip:mfc', source: 'IP catalog' })).toBe('assumed')
  expect(sourceGrade({ key: 'vdd:CAM', source: 'SAMPLE DVFS' })).toBe('assumed')
  // a measured row that changes a verdict stays in the default view
  const decisive: Sensitivity = { ...data, rows: [{ ...data.rows[0], source: 'profile / measured' }, data.rows[1]] }
  const h0 = document.createElement('div'); const r0 = createRoot(h0)
  act(() => r0.render(<SensitivityTornado data={decisive} />))
  expect([...h0.querySelectorAll('tbody tr')].map((tr) => tr.getAttribute('data-testid'))).toEqual(['sens-measured', 'sens-assumed'])
  act(() => r0.unmount())
  const quiet = { ...data.rows[0], source: 'profile / measured', crosses: [], timing: { ...data.rows[0].timing!, fails_at_high: false } }
  const measured: Sensitivity = { ...data, rows: [quiet, data.rows[1]] }
  const host = document.createElement('div')
  const root = createRoot(host)
  act(() => root.render(<SensitivityTornado data={measured} />))
  expect([...host.querySelectorAll('tbody tr')].map((tr) => tr.getAttribute('data-testid'))).toEqual(['sens-assumed'])
  const box = host.querySelector('[data-testid="sens-all"]') as HTMLInputElement
  act(() => box.click())
  expect([...host.querySelectorAll('tbody tr')].map((tr) => tr.getAttribute('data-testid'))).toEqual(['sens-measured', 'sens-assumed'])
  act(() => root.unmount())
})
