import { describe, expect, it } from 'vitest'
import { compInfo, llcInfo } from './memLever'
import { buildModel } from './model'
import { buildGraph, bufferPills, ipPills } from './graph'
import { sequenceLayout } from './sequence'
import type { ScenarioDef, ViewResponse } from './api'

const CAT = { COMP_YUV_LOSSLESS: { compressor: 'SBWC', comp_ratio: 1.0, typical_ratio: 0.7 }, COMP_YUV_LOSSY: { compressor: 'SBWC', comp_ratio: 0.5 } }

describe('compInfo', () => {
  it('treats off tokens as off', () => {
    for (const m of ['', 'COMP_OFF', 'disable', 'NONE']) expect(compInfo(m).on).toBe(false)
  })
  it('labels SBWC from the SoC catalog compressor and takes its comp_ratio', () => {
    const c = compInfo('COMP_YUV_LOSSY', CAT)
    expect(c).toMatchObject({ on: true, family: 'SBWC', lossy: true, ratio: 0.5, label: 'SBWC lossy' })
    expect(compInfo('COMP_YUV_LOSSLESS', CAT)).toMatchObject({ label: 'SBWC LL', ratio: 1, typical: 0.7 })
  })
  it('recognises SBWC / AFBC names without a catalog (ratio unknown)', () => {
    expect(compInfo('COMP_SBWC_LOSSLESS')).toMatchObject({ family: 'SBWC', ratio: null })
    expect(compInfo('AFBC').family).toBe('AFBC')
  })
})

describe('llcInfo', () => {
  it('is null unless llc_allocated is true', () => {
    expect(llcInfo(null)).toBeNull()
    expect(llcInfo({ llc_allocated: false, llc_weight: 0.6 })).toBeNull()
  })
  it('keeps weight / policy / size', () => {
    expect(llcInfo({ llc_allocated: true, llc_weight: 0.6, llc_policy: 'dedicated', allocation_owner: 'MTNR' }))
      .toMatchObject({ weight: 0.6, weightKnown: true, policy: 'dedicated', label: 'LLC ×0.6' })
    expect(llcInfo({ llc_allocated: true })).toMatchObject({ weight: 1, weightKnown: false, label: 'LLC' })
  })
})

const view: ViewResponse = {
  level: 1, scenario_id: 's', variant_id: 'v',
  summary: { name: 's', subtitle: '', period_ms: 33.3, budget_ms: 33.3, fps: 30 },
  nodes: [
    { data: { id: 'ip-mlsc', label: 'MLSC', type: 'ip', ip_ref: 'ip-mlsc' } },
    { data: { id: 'ip-mtnr', label: 'MTNR', type: 'ip', ip_ref: 'ip-mtnr' } },
    { data: { id: 'ip-mscl', label: 'MSCL', type: 'ip', ip_ref: 'ip-m2m-scaler' } },
    { data: { id: 'ip-dpu', label: 'DPU', type: 'ip', ip_ref: 'ip-dpu' } },
  ] as ViewResponse['nodes'],
  edges: [
    { data: { id: 'e1', source: 'ip-mlsc', target: 'ip-mtnr', flow_type: 'M2M', buffer_ref: 'PYRAMID_L0', port_pairs: [{ src: 'MLSC_W_L0', dst: 'MTNR0_RDMA_CUR_L0_Y' }],
      memory: { width: 4000, height: 2252, format: 'Y', bitdepth: 12, compression: 'COMP_OFF' }, placement: { llc_allocated: true, llc_weight: 0.6 } } },
    { data: { id: 'e2', source: 'ip-mscl', target: 'ip-dpu', flow_type: 'vOTF' } },
  ],
}
const scn = { id: 's', pipeline: { buffers: {
  PYRAMID_L0: { size_ref: 'l0', format: 'Y', bitdepth: 12, compression: 'COMP_YUV_LOSSY', placement: { llc_allocated: true, llc_weight: 0.6 } },
  TNR_PREV_L0: { size_ref: 'l0', format: 'Y', bitdepth: 12, compression: 'COMP_OFF', placement: { llc_allocated: true, llc_weight: 0.6 },
    history: { node_id: 'mtnr', frame_offset: -1, read_ports: ['MTNR0_RDMA_PREV_L0_Y'], write_ports: ['MTNR0_WDMA_PREV_L0_Y'] } },
} }, size_profile: { anchors: { l0: '4000x2252' } } } as unknown as ScenarioDef

describe('power levers through model / diagram', () => {
  const m = buildModel(view, scn, null, undefined, { compCatalog: CAT })
  const l0 = m.buffers.find((b) => b.name === 'PYRAMID_L0')!
  const prev = m.buffers.find((b) => b.name === 'TNR_PREV_L0')!

  it('applies compression ratio to bus traffic and LLC weight to DRAM traffic', () => {
    expect(l0.compression.on).toBe(true)
    expect(l0.mbRaw).toBeCloseTo(4000 * 2252 * 1.5 / 1e6, 3)
    expect(l0.mbFrame).toBeCloseTo(l0.mbRaw! * 0.5, 3)
    expect(l0.llc?.weight).toBe(0.6)
    expect(l0.dramMBs).toBeCloseTo((l0.wMBs! + l0.rMBs!) * 0.6, 0)
    expect(prev.kind).toBe('history')
    expect(prev.llc?.weight).toBe(0.6)
    expect(m.totalDramMBs).toBeLessThan(m.totalMBs)
    expect(m.levers).toEqual({ llc: 2, sbwc: 1, votf: 1 })
  })

  it('variant buffer_overrides change compression / placement', () => {
    const m2 = buildModel(view, scn, { id: 'v', scenario_id: 's', buffer_overrides: { PYRAMID_L0: { compression: 'COMP_OFF', placement: { llc_allocated: false } } } }, undefined, { compCatalog: CAT })
    const b = m2.buffers.find((x) => x.name === 'PYRAMID_L0')!
    expect(b.compression.on).toBe(false)
    expect(b.llc).toBeNull()
  })

  it('marks IPs and diagram nodes / edges', () => {
    const mtnr = m.byPid.get('mtnr')!
    expect(mtnr.levers.llc).toEqual(expect.arrayContaining(['PYRAMID_L0', 'TNR_PREV_L0']))
    expect(mtnr.levers.sbwc).toEqual(['PYRAMID_L0'])
    expect(m.byPid.get('mscl')!.levers.votf).toEqual(['DPU'])
    expect(ipPills(mtnr.levers).map((p) => p.key)).toEqual(['llc', 'sbwc'])
    expect(bufferPills(l0).map((p) => p.text)).toEqual(['LLC ×0.6', 'SBWC lossy'])

    const g = buildGraph(view, new Set(), new Set(), m)
    expect(g.nodes.find((n) => n.id === 'buf:PYRAMID_L0')!.levers!.map((p) => p.key)).toEqual(['llc', 'sbwc'])
    expect(g.edges.filter((e) => e.id.startsWith('e1')).every((e) => e.lever === 'llc')).toBe(true)
    expect(g.edges.find((e) => e.id === 'e2')!.kind).toBe('vOTF')
    expect(g.nodes.find((n) => n.id === 'buf:TNR_PREV_L0')!.levers!.map((p) => p.key)).toEqual(['llc'])

    const seq = sequenceLayout(view, { showSw: true, model: m, scenario: scn })
    expect(seq.edges.find((e) => e.source === 'ip-mscl')!.kind).toBe('vOTF')
    expect(seq.edges.find((e) => e.source === 'ip-mlsc')!.lever).toBe('llc')
    expect(seq.nodes.find((n) => n.id === 'ip-mtnr')!.levers!.length).toBe(2)
    // vOTF is streaming: producer and consumer share a Sequence column
    const a = seq.nodes.find((n) => n.id === 'ip-mscl')!, b = seq.nodes.find((n) => n.id === 'ip-dpu')!
    expect(a.x).toBe(b.x)
  })
})

describe('variant table lever column', () => {
  it('summarises the server-side lever set and flags a different set vs the reference', async () => {
    const { variantPills, leverColumn } = await import('../components/LeverTag')
    const ml = { llc: ['PYRAMID_L0', 'TNR_PREV_L0'], compressed: ['PYRAMID_L0'], votf: [], llc_weight_min: 0.6 }
    expect(variantPills(ml).map((p) => p.text)).toEqual(['LLC 2 ×0.6', 'SBWC 1'])
    expect(variantPills({ llc: [], compressed: [], votf: [] })).toEqual([])
    const col = leverColumn<{ m: typeof ml | null }>((r) => r.m, () => ({ llc: [], compressed: [], votf: [] }))
    expect(col.cellClass({ m: ml })).toBe('chg')
    expect(col.sort({ m: ml })).toBe(210)
  })
})
