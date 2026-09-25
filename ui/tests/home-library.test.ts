import { describe, expect, it } from 'vitest'
import { DOMAINS, domainFor } from '../src/lib/tunnel'
import { errClass } from '../src/lib/calibration'
import { ipSummary, range } from '../src/lib/library'
import { formatHash, parseHash } from '../src/lib/route'

describe('tunnel stages', () => {
  it('uses generic stage names; IP names only as examples', () => {
    for (const stages of Object.values(DOMAINS)) {
      expect(stages.length).toBeGreaterThan(3)
      for (const s of stages) {
        expect(s.n).toMatch(/^[A-Z0-9 ·/&-]+$/)
        expect(['rt', 'm2m', 'mem', 'sw', 'post', 'out']).toContain(s.k)
      }
    }
    const names = DOMAINS.camera.map((s) => s.n).join(' ')
    expect(names).not.toMatch(/CSIS|BYRP|RGBP|MCSC|MTNR/)
  })
  it('maps categories to a domain', () => {
    expect(domainFor(['Camera', 'Recording'])).toBe('camera')
    expect(domainFor(['video_playback'])).toBe('video')
    expect(domainFor(['display'])).toBe('display')
    expect(domainFor(undefined)).toBe('camera')
  })
})

describe('calibration', () => {
  it('classifies prediction error bands', () => {
    expect(errClass(null)).toBe('')
    expect(errClass(-9.9)).toBe('v-ok')
    expect(errClass(18)).toBe('v-warn')
    expect(errClass(-40)).toBe('v-fail')
  })
})

describe('library', () => {
  it('summarises IP capabilities', () => {
    const s = ipSummary({ id: 'ip-x', category: 'ISP', capabilities: {
      sim: { hw_name: 'X', vdd: 'VDD_CAM', dvfs_group: 'CAM', source: 'datasheet' },
      operating_modes: [{ id: 'a' }, { id: 'b' }],
      supported_features: { compression: ['SBWC_OFF', 'SBWC_LOSSY_50'] } } })
    expect(s).toMatchObject({ hw: 'X', vdd: 'VDD_CAM', dvfs: 'CAM', modes: 2, compression: ['SBWC_LOSSY_50'] })
    expect(ipSummary({ id: 'y', category: 'ISP', capabilities: {} }).hw).toBe('—')
  })
  it('formats ranges', () => {
    expect(range(null)).toBe('—')
    expect(range([2, 2])).toBe('2.0')
    expect(range([1.25, 3.5], 2)).toBe('1.25–3.50')
  })
})

describe('new routes', () => {
  it('parses home / calibration / library / settings', () => {
    expect(parseHash('#/').page).toBe('home')
    expect(parseHash('#/calibration?m=abc').params.m).toBe('abc')
    expect(parseHash('#/library?tab=sw').page).toBe('library')
    expect(parseHash('#/settings').page).toBe('settings')
    expect(parseHash(formatHash({ page: 'library', params: { tab: 'dvfs' } })).params.tab).toBe('dvfs')
  })
})
