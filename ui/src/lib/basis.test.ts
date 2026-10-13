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

describe('basis labels stay short', () => {
  it('drops the SoC from the DVFS id and the profile prefix', async () => {
    const { basisShortLabel, shortDvfs } = await import('./basis')
    expect(shortDvfs('dvfs-exynos2600-sample-v0')).toBe('sample-v0')
    expect(shortDvfs(null)).toBe('DVFS 기본')
    expect(basisShortLabel({ code: 'B2', components: 'cfg v2 · pmp v2 · dvfs-exynos2600-sample-v0 · e11', dvfs_table_ref: 'dvfs-exynos2600-sample-v0' }))
      .toBe('B2 · cfg v2 · pmp v2 · sample-v0 · e11')
    // an older API spelled the profile id out
    expect(basisShortLabel({ code: 'B2', components: 'cfg simcfg-proj-sm-s947b-v2 · pmp v2 · DVFS 기본 · e11', dvfs_table_ref: null }))
      .toBe('B2 · cfg v2 · pmp v2 · DVFS 기본 · e11')
  })
})
