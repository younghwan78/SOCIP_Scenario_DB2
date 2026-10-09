import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { ConditionBar, IntervalBoxes, conditionChips } from './TimingWorkbench'

const cond = { statistic: 'max', scale: 1, eis: 'auto', cpuModel: 'flat', throughput: 'pipelined', margin: 0.25, profile: null, overrides: { CAM: 3 } }
const noop = async () => ''

it('summarises the condition and blocks registering a failing one', () => {
  expect(conditionChips(cond)).toContain('DVFS override CAM L3')
  const ok = renderToStaticMarkup(createElement(ConditionBar, { cond, verdict: 'ok', onSaveEvidence: noop, onRegister: noop, onOpenPredictions: () => {} }))
  expect(ok).toContain('Sim evidence 저장')
  expect(ok).toContain('예측으로 등록')
  const fail = renderToStaticMarkup(createElement(ConditionBar, { cond, verdict: 'fail', onSaveEvidence: noop, onRegister: noop, onOpenPredictions: () => {} }))
  expect(fail).toMatch(/disabled="" title="timing fail/)
})

it('draws interval and latency boxes per output stream', () => {
  const html = renderToStaticMarkup(createElement(IntervalBoxes, { data: {
    period_ms: 33.3, trials: 2, frames: 12, warmup_excluded: 2, tolerance: 0.001, method: 'm', varied: ['post_irta'], fixed: [],
    streams: [{ node: 'dpu', kind: 'preview', intervals: [33.1, 33.3, 33.6], latency: [40, 41, 42], drops: 0, off_cadence_pct: 66.7 }] } }))
  expect(html).toContain('SW 편차 반영 분포')
  expect(html).toContain('Preview · dpu')
  expect(html).toContain('post_irta')
})
