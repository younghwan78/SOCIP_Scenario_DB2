import { expect, it } from 'vitest'
import { predictionTooltip, type CoveragePrediction } from './calibration'

const prediction: CoveragePrediction = { id: 'pred-test', total_mw: 100 }

it('distinguishes unknown and pending states in the hover when cell markers are hidden', () => {
  expect(predictionTooltip(prediction)).toContain('상태 ? — 판정 정보 없음')
  expect(predictionTooltip(prediction, undefined, true)).toContain('상태 확인 중')
  expect(predictionTooltip(prediction, undefined, true)).not.toContain('상태 ✓')
})

it('keeps normal and changed-input details available in the hover', () => {
  expect(predictionTooltip({ ...prediction, freshness: { status: 'fresh', reasons: [], changed: [] } })).toContain('상태 ✓')
  expect(predictionTooltip({ ...prediction, freshness: { status: 'stale', reasons: ['profile changed'],
    changed: ['config_profile'] } })).toContain('상태 ⚠ 기준 — profile changed')
  expect(predictionTooltip({ ...prediction, freshness: { status: 'stale', reasons: ['variant changed'],
    changed: ['variant_doc'] } })).toContain('상태 ⚠ 데이터 — variant changed')
})
