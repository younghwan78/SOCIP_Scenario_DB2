import { describe, expect, it } from 'vitest'
import { FOLLOW_BASIS, NO_PROFILE, pickProfile, type SimProfile } from './simProfile'
import type { ModelBasis } from './basis'

const profiles: SimProfile[] = [{ id: 'simcfg-p-v1', version: 1 }, { id: 'simcfg-p-v2', version: 2 }]
const basis = { id: 'basis-p-1', code: 'B1', config_profile_ref: 'simcfg-p-v1' } as ModelBasis

describe('profile pick follows the active 예측 기준', () => {
  it('defaults to the basis profile, not the latest version', () => {
    expect(pickProfile(profiles, undefined, basis)).toBe('simcfg-p-v1')
    expect(pickProfile(profiles, FOLLOW_BASIS, basis)).toBe('simcfg-p-v1')
    expect(pickProfile(profiles, undefined, null)).toBe('simcfg-p-v2')
  })
  it('an explicit choice (기준 외) still wins', () => {
    expect(pickProfile(profiles, 'simcfg-p-v2', basis)).toBe('simcfg-p-v2')
    expect(pickProfile(profiles, NO_PROFILE, basis)).toBeNull()
    expect(pickProfile(profiles, undefined, { ...basis, config_profile_ref: null })).toBeNull()
  })
})
