import { describe, expect, it } from 'vitest'
import { groupFailures } from './VariantFailures'

describe('groupFailures', () => {
  it('groups the same cause across variants and keeps legacy rows', () => {
    const groups = groupFailures([
      { variant_id: 'a', category: 'sw_stage_budget', error: 'eis: included hardware needs positive PPC and a time budget', hint: 'h' },
      { variant_id: 'b', category: 'sw_stage_budget', error: 'eis: included hardware needs positive PPC and a time budget', hint: 'h' },
      { variant_id: 'c', category: 'dvfs', error: 'required_clock 1200.0MHz exceeds max DVFS speed 1066.0MHz' },
      { variant_id: 'd', category: 'dvfs', error: 'required_clock 1300.5MHz exceeds max DVFS speed 1066.0MHz' },
      { variant_id: 'old', error: 'legacy message without category' },
    ])
    expect(groups.map((g) => [g.category, g.items.length])).toEqual([['sw_stage_budget', 2], ['dvfs', 2], ['other', 1]])
  })
})
