import { describe, expect, it } from 'vitest'
import view from './fixtures/view-uhd30-vdis.json'
import events from './fixtures/trace-events.json'
import type { TimelineEvent, ViewResponse } from '../src/lib/api'
import { compareValues, sortRows } from '../src/components/DataTable'
import { buildModel, trafficByIp } from '../src/lib/model'
import { sequenceLayout, sequenceRanks } from '../src/lib/sequence'
import { buildTimeline } from '../src/lib/timeline'
import { analyse, boxStats, stageTimings } from '../src/lib/cadence'
import { modeNotes } from '../src/lib/modes'
import { preferredReference, resFpsKey } from '../src/lib/defaults'

const V = view as unknown as ViewResponse
const tl = buildTimeline(events as unknown as TimelineEvent[], { maxFrames: 16 })

describe('DataTable sorting', () => {
  it('numeric-aware, blanks last in both directions', () => {
    expect(compareValues(2, 10)).toBeLessThan(0)
    expect(compareValues('f2', 'f10')).toBeLessThan(0)
    const rows = [{ v: 3 }, { v: null }, { v: 1 }, { v: 2 }]
    expect(sortRows(rows, (r) => r.v, 1).map((r) => r.v)).toEqual([1, 2, 3, null])
    expect(sortRows(rows, (r) => r.v, -1).map((r) => r.v)).toEqual([3, 2, 1, null])
  })
  it('pinned rows stay on top', () => {
    const rows = [{ id: 'a', v: 1 }, { id: 'ref', v: 9 }]
    expect(sortRows(rows, (r) => r.v, 1, (r) => r.id === 'ref')[0].id).toBe('ref')
  })
  it('res·fps sort key orders UHD60 > UHD30 > FHD60', () => {
    expect(resFpsKey({ resolution: 'UHD', fps: 60 })!).toBeGreaterThan(resFpsKey({ resolution: 'UHD', fps: 30 })!)
    expect(resFpsKey({ resolution: 'UHD', fps: 30 })!).toBeGreaterThan(resFpsKey({ resolution: 'FHD', fps: 60 })!)
  })
  it('camera recording reference = rear UHD30 EIS', () => {
    expect(preferredReference('uc-camera-recording', ['a', 'cam-rec-r1-uhd30-vdis'], 'a')).toBe('cam-rec-r1-uhd30-vdis')
    expect(preferredReference('uc-camera-recording', ['a'], 'a')).toBe('a')
  })
})

describe('sequence lens', () => {
  it('OTF keeps rank, M2M/control advance', () => {
    const r = sequenceRanks(['s', 'a', 'b', 'c'], [{ source: 's', target: 'a', kind: 'OTF' }, { source: 'a', target: 'b', kind: 'control' }, { source: 'b', target: 'c', kind: 'M2M' }])
    expect([r.get('s'), r.get('a'), r.get('b'), r.get('c')]).toEqual([0, 0, 1, 2])
  })
  it('RT chain shares one column; SW hand-off sits between RT and NRT', () => {
    const m = buildModel(V)
    const L = sequenceLayout(V, { showSw: true, model: m, timing: stageTimings(tl) })
    const x = (id: string) => L.nodes.find((n) => n.id === id)!.x
    expect(new Set(['ip-csis', 'ip-pdp', 'ip-byrp', 'ip-rgbp', 'ip-yuvsc', 'ip-mlsc'].map(x)).size).toBe(1)
    expect(x('ip-post-crta')).toBeGreaterThan(x('ip-mlsc'))
    expect(x('ip-mtnr')).toBeGreaterThan(x('ip-post-irta'))
    expect(x('ip-eis')).toBeGreaterThan(x('ip-mcsc'))
    expect(x('ip-gdc-o')).toBeGreaterThan(x('ip-eis'))
    expect(L.bands!.map((b) => b.label)).toContain('RT → NRT hand-off')
    expect(L.nodes.find((n) => n.id === 'ip-mtnr')!.sub).toBe('4080×2296')
    expect(L.nodes.find((n) => n.id === 'ip-mcsc')!.sub).toMatch(/1920×1080/)
  })
})

describe('pipeline model', () => {
  it('buffers carry ports, size and MB/s; stat buffers flagged', () => {
    const m = buildModel(V)
    const l1 = m.buffers.find((b) => b.name === 'PYRAMID_L1')!
    expect(l1.wPorts).toEqual(['MLSC_W_GLPG1_Y', 'MLSC_W_GLPG1_U', 'MLSC_W_GLPG1_V'])
    expect(l1.width).toBe(2040)
    expect(l1.wMBs).toBeGreaterThan(0)
    expect(m.buffers.find((b) => b.name === 'RGBP_DRC')!.kind).toBe('stat')
    expect(m.byPid.get('mcsc')!.outSizes).toEqual(['1920×1080', '3840×2160'])
    expect([...trafficByIp(m).keys()]).toContain('MTNR')
    expect(m.byPid.get('mlsc')!.wdma.used).toBeGreaterThan(10)
    expect(m.byPid.get('mlsc')!.wdma.total).toBeNull()
  })
  it('catalog channels: used / unused / off', () => {
    const cat = new Map([['ip-mcsc-is-v15-s5e9965', { id: 'ip-mcsc-is-v15-s5e9965', capabilities: { properties: { modules: [
      { name: 'MCSC_WDMA_W0', type: 'DMA', direction: 'write' }, { name: 'MCSC_WDMA_W1', type: 'DMA', direction: 'write' }, { name: 'MCSC_WDMA_W2', type: 'DMA', direction: 'write' }, { name: 'CINFIFO', type: 'FIFO', direction: 'read' }] } } }]])
    const mc = buildModel(V, null, null, cat).byPid.get('mcsc')!
    expect(mc.wdma).toEqual({ used: 2, total: 3 })
    expect(mc.channels.find((c) => c.name === 'MCSC_WDMA_W2')!.status).toBe('unused')
    expect(mc.channels.find((c) => c.name === 'CINFIFO')!.status).toBe('used')
  })
})

describe('cadence', () => {
  it('box stats', () => {
    const b = boxStats([1, 2, 3, 4, 5])!
    expect(b.median).toBe(3)
    expect(b.q1).toBe(2)
  })
  it('preview/video buffer period meets 30fps on fixture', () => {
    const a = analyse(tl, V, 30)
    const prev = a.results.find((r) => r.stream.id === 'preview')!
    expect(prev.stream.pid).toBe('gdc_m')
    expect(prev.fpsAchieved!).toBeCloseTo(30, 0)
    expect(prev.verdict).toBe('ok')
    expect(a.inFlight).toBeGreaterThanOrEqual(2)
  })
  it('mode notes', () => {
    expect(modeNotes({ power_saving_mode: true }, new Set(['mcsc']), ['eis', 'gdc_m']).map((n) => n.id)).toContain('psm')
    expect(modeNotes({}, new Set(['vps_dof']), []).map((n) => n.id)).toContain('dof')
    expect(modeNotes({ fps: 960, extend_mode: 'EX_DUALFPS_960' }, new Set(), []).map((n) => n.id)).toContain('hs')
  })
})
