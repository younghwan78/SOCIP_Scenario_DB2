// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it } from 'vitest'
import { CandidateReview, candidateReviewDocument } from '../src/components/CandidateReview'
import { updateExperimentContext, type ExperimentCandidate } from '../src/lib/experimentContext'
import { rankProfiles } from '../src/pages/CpuWhatIf'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
afterEach(() => sessionStorage.clear())
const scope = { project_ref: 'p', scenario_id: 's', variant_id: 'v' }
const candidate: ExperimentCandidate = { id: 'c', title: 'Crop candidate', condition_hash: 'condition-1', baseline_hash: 'baseline-old',
  changes: [{ target: 'chain_size', node_id: 'mcsc', width: 1920, height: 1080 }],
  metrics: { modeled_power_mw: 0, total_power_mw: null, cpu_power_mw: 0, ip_power_mw: 0, memory_power_mw: 0, bw_mbs: 50, fps: 30, period_ms: 33, feasible: true },
  baseline_metrics: { modeled_power_mw: 100, total_power_mw: null, cpu_power_mw: 0, ip_power_mw: 100, memory_power_mw: 0, bw_mbs: 80, fps: 30, period_ms: 33, feasible: true },
  coverage: { complete: false, scope: 'IP', missing_components: ['sensor'], excluded_components: [], cpu_model: 'flat', assumptions: [] }, iq_required: ['crop'], created_at: '2026-10-26' }

it('retains zero, warns on baseline mismatch and shows coverage/IQ before export', () => {
  const context = updateExperimentContext(scope, { baseline_hash: 'baseline-current', candidates: [candidate] })
  const host = document.createElement('div'), root = createRoot(host)
  try {
    act(() => root.render(<CandidateReview scope={scope} exportable />))
    expect(host.textContent).toContain('100.0 → 0.0')
    expect(host.textContent).toContain('-100.0')
    expect(host.textContent).toContain('다른 기준 · 재계산 필요')
    expect(host.textContent).toContain('IQ 검증 필요')
    expect(host.textContent).toContain('일부 power만 모델링')
    const exported = candidateReviewDocument({ ...context, secret: 'never-export' } as typeof context)
    expect(JSON.stringify(exported)).not.toContain('never-export')
    expect(exported.candidates[0].baseline_hash).toBe('baseline-old')
    expect(exported.status).toBe('unreviewed_local_snapshot')
  } finally { act(() => root.unmount()) }
})

it('chooses a matching scoped CPU profile before an unrelated usable profile', () => {
  const profiles = [{ id: 'other', project_ref: 'q', scenario_ref: 'other', variant_ref: 'other', tasks: [{}], origin: 'physical_capture' },
    { id: 'match', project_ref: 'p', scenario_ref: 's', variant_ref: 'v', tasks: [], origin: 'synthetic' }]
  expect(rankProfiles(profiles as never, { project: 'p', scenario: 's', variant: 'v' })[0].id).toBe('match')
})
