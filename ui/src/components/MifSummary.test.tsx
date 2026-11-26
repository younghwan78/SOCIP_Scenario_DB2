// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { MifSummary } from './PacingCard'
import type { GpuMif } from '../lib/timingBudget'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

const base: GpuMif = {
  model: 'gpu-mif-floor-v1', node: 'gpu', gpu_mhz: 605, source: 'catalog', status: 'ok', floor_mhz: 2730,
  floor_key_khz: '605000', bw_model: 'mif-linear', applied: true, level_mhz: 2730, level_without_floor_mhz: 1539,
  level_reason: 'min_lock', base_mw: 150, dram_mbs: 7750.7, utilization: 0.37, floor_extra_mw: 60,
  gpu_workload_mbs: { GPU_WORKLOAD_RD: 4320, GPU_WORKLOAD_WR: 1440 },
}

function render(m: GpuMif) {
  const host = document.createElement('div')
  act(() => createRoot(host).render(<MifSummary mif={m} />))
  return host
}

it('shows the floor, the level it sets and what it adds', () => {
  const text = render(base).textContent ?? ''
  expect(text).toContain('4.32 / 1.44 GB/s')
  expect(text).toContain('2730 MHz')
  expect(text).toContain('min_lock · floor 없을 때 1539 MHz')
  expect(text).toContain('60.0 mW')
})

it('reports the floor only under a BW model without MIF levels', () => {
  const text = render({ ...base, bw_model: 'legacy-coeff', applied: false, level_mhz: undefined, floor_extra_mw: undefined }).textContent ?? ''
  expect(text).toContain('legacy-coeff: 보고만')
})

it('says why there is no floor', () => {
  expect(render({ ...base, status: 'no_table', reason: 'gpu: no table' }).textContent).toBe('gpu: no table')
})
