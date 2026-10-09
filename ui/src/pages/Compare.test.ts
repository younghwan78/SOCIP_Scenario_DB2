import { expect, it } from 'vitest'
import { kpiNumber, predictionKpi } from './Compare'
import type { BoardRow } from '../lib/archExplore'

it('maps a registered prediction to Compare KPI fields (CMP-03)', () => {
  const row = { power: { total_mw: 900, cpu_mw: 200, hw_mw: 500, bw_mw: 200 }, bw_mbs: 3000, fps: 60, verdict: 'ok',
    verdict_detail: { latency: { video_ms: 41 } } } as unknown as BoardRow
  const k = predictionKpi(row)
  expect(kpiNumber(k.total_power_mw)).toBe(900)
  expect(kpiNumber(k.core_power_mw)).toBe(700)
  expect(kpiNumber(k.fps_effective)).toBe(60)
  expect(kpiNumber(k.frame_latency_ms)).toBe(41)
  expect(predictionKpi({ ...row, verdict: 'fail' } as BoardRow).fps_effective).toBeNull()
})
