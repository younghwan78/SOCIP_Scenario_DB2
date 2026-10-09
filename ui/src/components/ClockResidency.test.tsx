// @vitest-environment jsdom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it, vi } from 'vitest'
import { ClockCompareCard, ClockResidencyCard, ModelCheckDist } from './ClockResidency'
import { clockApi } from '../lib/clockResidency'
import type { ClockDomain, ClockView } from '../lib/clockResidency'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const st = (bins: [number, number][], high: number | null) => ({
  bins: bins.map(([mhz, ratio]) => ({ mhz, ratio })), mean_mhz: bins.reduce((a, [m, r]) => a + m * r, 0), p50_mhz: bins[0][0],
  max_mhz: bins[bins.length - 1][0], min_mhz: bins[0][0], dominant_mhz: bins[0][0], dominant_share: bins[0][1], high_share: high,
})
const dom = (p: Partial<ClockDomain>): ClockDomain => ({
  domain_class: 'cpu', class_label: 'CPU', domain: 'MID_LF0', is_dsu: false, opp_max_mhz: 2000,
  wall: st([[400, 0.3], [1000, 0.7]], 0), active: st([[1000, 0.6], [1600, 0.4]], 0.4),
  active_ratio: 0.47, clock_gated_ratio: 0.24, power_gated_ratio: 0.29, pass_jsd: 0.092, source: 'observation',
  notes: [{ level: 'warn', code: 'high_opp', text: '고 OPP 40%' }], ...p,
})
const view: ClockView = {
  rules_version: 1, summary: ['CPU: 가장 바쁜 cluster MID_LF0'], thresholds: { high_opp_fraction: 0.8, high_opp_warn: 0.3, pass_jsd_warn: 0.05 },
  domains: [dom({}), dom({ domain: 'DSU', is_dsu: true, notes: [], pass_jsd: null }),
            dom({ domain_class: 'gpu', class_label: 'GPU', domain: 'GPU', opp_max_mhz: null, active: null, wall: st([[300, 1]], null), notes: [] })],
}

function mount(el: ReturnType<typeof createElement>) {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const root = createRoot(host)
  act(() => root.render(el))
  return { host, root }
}

describe('ClockResidencyCard', () => {
  it('renders measurement evidence without a variant', async () => {
    const spy = vi.spyOn(clockApi, 'rows').mockResolvedValue([{
      id: 'base-measurement', scenario_id: 'scenario', variant_id: null,
      measured_at: null, sw_baseline_ref: null, synthetic: false, domains: [],
    }])
    const { host, root } = mount(createElement(ClockCompareCard, { onPick: () => {} }))
    try {
      await act(async () => { await Promise.resolve() })
      expect(host.textContent).toContain('기본 시나리오')
    } finally {
      act(() => root.unmount())
      spy.mockRestore()
    }
  })
  it('groups CPU / DSU / GPU, flags warnings and toggles the basis', () => {
    const { host, root } = mount(createElement(ClockResidencyCard, { view }))
    const text = host.textContent ?? ''
    expect(text).toContain('CPU: 가장 바쁜 cluster MID_LF0')
    expect([...host.querySelectorAll('tr.clk-group')].map((r) => r.textContent)).toEqual(['CPU', 'DSU', 'GPU'])
    expect(text).toContain('0.092')
    expect(text).toContain('확인 1')
    expect(text).toContain('(전체)')                       // GPU has no running distribution -> falls back
    const row = host.querySelector('tr.clickable') as HTMLTableRowElement
    act(() => row.click())
    expect(host.querySelector('tr.clk-detail')).not.toBeNull()
    const wallBtn = [...host.querySelectorAll('button')].find((b) => b.textContent === '전체 기준') as HTMLButtonElement
    act(() => wallBtn.click())
    expect(host.querySelector('tr.clickable td.mono + td + td')?.textContent).toBe('820 MHz')
    act(() => root.unmount())
  })
  it('model check renders the model line only when known', () => {
    const { host, root } = mount(createElement(ModelCheckDist, { wall: [{ mhz: 1000, ratio: 1 }], modelMhz: 1600, fmax: 2000 }))
    expect(host.querySelectorAll('line[stroke="#B42318"]').length).toBe(1)
    act(() => root.unmount())
    const empty = mount(createElement(ModelCheckDist, {}))
    expect(empty.host.textContent).toBe('—')
    act(() => empty.root.unmount())
  })
})
