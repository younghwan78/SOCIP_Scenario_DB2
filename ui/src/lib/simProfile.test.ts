import { describe, expect, it } from 'vitest'
import { NO_PROFILE, pickProfile } from './simProfile'

describe('sim config profile pick', () => {
  const ps = [{ id: 'simcfg-v1', version: 1 }, { id: 'simcfg-v2', version: 2 }]
  it('defaults to the newest version', () => expect(pickProfile(ps, undefined)).toBe('simcfg-v2'))
  it('honours an explicit existing choice', () => expect(pickProfile(ps, 'simcfg-v1')).toBe('simcfg-v1'))
  it('rejects an unknown explicit id', () => expect(() => pickProfile(ps, 'gone')).toThrow('gone'))
  it('none = code defaults', () => expect(pickProfile(ps, NO_PROFILE)).toBeNull())
  it('no profiles → null', () => expect(pickProfile([], undefined)).toBeNull())
})
