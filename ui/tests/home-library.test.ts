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

describe('timing clock text', () => {
  it('shows DVFS levels on both sides, or why there is none', async () => {
    const { clockText } = await import('../src/lib/timingBudget')
    expect(clockText({ rule_clock_mhz: 342.3, set_clock_mhz: 400, rule_dvfs_level: 4, dvfs_level: 4, dvfs_table: true, dvfs_group: 'CAM' })).toBe('342 (Lv4) → 400 MHz (Lv4)')
    expect(clockText({ rule_clock_mhz: 342.3, set_clock_mhz: 342.3, rule_dvfs_level: null, dvfs_level: null, dvfs_table: false, dvfs_group: 'CSIS' })).toBe('342 → 342 MHz (Lv — · CSIS 표 없음)')
  })
})

describe('ip topology', () => {
  it('ranks by longest path and lays lanes out as columns', async () => {
    const { ranks, topoLayout } = await import('../src/lib/topology')
    const r = ranks(['a', 'b', 'c'], [{ from: 'a', to: 'b', kind: 'OTF' }, { from: 'b', to: 'c', kind: 'M2M' }, { from: 'a', to: 'c', kind: 'M2M' }, { from: 'c', to: 'a', kind: 'ctrl' }])
    expect(r.get('c')).toBeGreaterThan(r.get('b')!)
    const ip = (pid: string, lane: string) => ({ pid, viewId: pid, label: pid.toUpperCase(), lane, type: 'ip', ipRef: '', inSize: '', outSizes: [], ops: [], flags: [], ports: [], channels: [], rdma: { used: 0, total: null }, wdma: { used: 0, total: null } })
    const m = { ips: [ip('csis', 'rt'), ip('byrp', 'rt'), ip('mtnr', 'nrt')], links: [{ from: 'csis', to: 'byrp', kind: 'OTF' }, { from: 'byrp', to: 'mtnr', kind: 'M2M' }] }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const lay = topoLayout(m as any)
    const pos = new Map(lay.nodes.map((n) => [n.ip.pid, n]))
    expect(pos.get('csis')!.x).toBe(pos.get('byrp')!.x)
    expect(pos.get('byrp')!.y).toBeGreaterThan(pos.get('csis')!.y)
    expect(pos.get('mtnr')!.x).toBeGreaterThan(pos.get('byrp')!.x)
  })
})
