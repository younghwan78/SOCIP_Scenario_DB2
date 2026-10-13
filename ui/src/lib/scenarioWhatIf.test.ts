import { expect, it } from 'vitest'
import { clockExplanation } from './scenarioWhatIf'
it('explains DVFS clocks in Korean and preserves the shared-domain leader', () => {
  const base = { clock_reason: null, basis: 'rule' }
  expect(clockExplanation({ ...base, set_reason: 'dvfs_floor' })).toBe('최소 DVFS 단계 유지')
  expect(clockExplanation({ ...base, set_reason: 'dvfs_step' })).toBe('필요 clock을 만족하는 DVFS 단계로 올림')
  expect(clockExplanation({ ...base, set_reason: 'exact' })).toBe('요구값 적용')
  expect(clockExplanation({ ...base, set_reason: 'domain', domain_leader: 'gdc_o' })).toBe('공유 domain의 요구 clock 적용 · 기준 IP gdc_o')
})
