import { expect, it } from 'vitest'
import { clockExplanation } from './scenarioWhatIf'
it('explains DVFS clocks in Korean and preserves the shared-domain leader', () => {
  const base = { clock_reason: null, basis: 'rule' }
  expect(clockExplanation({ ...base, set_reason: 'dvfs_floor' })).toBe('최소 DVFS 단계 유지')
  expect(clockExplanation({ ...base, set_reason: 'dvfs_step' })).toBe('필요 clock을 만족하는 DVFS 단계로 올림')
  expect(clockExplanation({ ...base, set_reason: 'exact' })).toBe('요구값 적용')
  expect(clockExplanation({ ...base, set_reason: 'domain', domain_leader: 'gdc_o' })).toBe('공유 domain의 요구 clock 적용 · 기준 IP gdc_o')
})
it('keeps one value per target and leads the answer with the asked metrics', async () => {
  const { upsertChange, describeChange } = await import('./scenarioWhatIf')
  const a = upsertChange([{ target: 'fps', value: 30 }], { target: 'node_clock_mhz', node_id: 'mfc', value: 400 })
  expect(upsertChange(a, { target: 'fps', value: 60 })).toEqual([{ target: 'fps', value: 60 }, { target: 'node_clock_mhz', node_id: 'mfc', value: 400 }])
  expect(describeChange({ target: 'output_size', anchor_id: 'record_out', width: 1920, height: 1080 })).toBe('출력 크기 record_out → 1920×1080')
})
