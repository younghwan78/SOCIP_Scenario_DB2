// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { PacingSummary } from './PacingCard'
import type { FramePacing } from '../lib/timingBudget'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

const pacing: FramePacing = {
  model: 'frame-pacing-v1', node: 'gpu', status: 'ok', target_fps: 120, refresh_hz: 120, achieved_fps: 119.79,
  fail_below_fps: 117.6, jank_pct: 0.176, drops: 0, expected_interval_ms: 8.3333, depth: 3, present_mode: 'fifo',
  frames: 600, seed: 7, gpu_ms: { p50: 6.63, p95: 8.55, p99: 9.21, median_computed: 6.61 },
  latency_ms: { p50: 25, p99: 25 }, gpu_basis: { distribution: 'lognormal', p95_x_gap: 0.0505 }, gpu_clock_mhz: 605,
  value_source: 'assumed',
}

function render(p: FramePacing) {
  const host = document.createElement('div')
  act(() => createRoot(host).render(<PacingSummary pacing={p} />))
  return host
}

it('shows achieved fps, jank, the GPU percentiles and latency', () => {
  const text = render(pacing).textContent ?? ''
  expect(text).toContain('119.8 / 120')
  expect(text).toContain('0.18 %')
  expect(text).toContain('6.63 / 8.55 / 9.21 ms')
  expect(text).toContain('BufferQueue 3')
})

it('states why there is no pacing when the GPU time is missing', () => {
  const text = render({ model: 'frame-pacing-v1', node: 'gpu', status: 'no_gpu_time', reason: 'gpu: needs a domain load' }).textContent
  expect(text).toBe('gpu: needs a domain load')
})
