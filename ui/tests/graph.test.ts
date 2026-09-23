import { describe, expect, it } from 'vitest'
import view from './fixtures/view-uhd30-vdis.json'
import { buildGraph, dmaRows, frameMb, layoutGraph, pipelineIdOf } from '../src/lib/graph'
import type { ViewResponse } from '../src/lib/api'

const v = view as unknown as ViewResponse

describe('buildGraph', () => {
  const g = buildGraph(v)
  it('splits M2M edges into separate buffer nodes (each pyramid level on its own)', () => {
    const buffers = g.nodes.filter((n) => n.kind === 'buffer').map((n) => n.bufferRef)
    expect(buffers).toEqual(expect.arrayContaining(['PYRAMID_L0', 'PYRAMID_L1', 'PYRAMID_L2', 'PYRAMID_L3', 'PYRAMID_L4', 'MCSC_VIDEO', 'GDC_VIDEO']))
    const l1 = g.nodes.find((n) => n.bufferRef === 'PYRAMID_L1')!
    expect(l1.sub).toBe('2040×1148 444 12b')
    expect(g.edges.some((e) => e.source === 'ip-mlsc' && e.target === 'buf:PYRAMID_L1')).toBe(true)
    expect(g.edges.some((e) => e.source === 'buf:PYRAMID_L1' && e.target === 'ip-mtnr')).toBe(true)
  })
  it('marks sensor and panel as external modules and groups ISP by stage', () => {
    expect(g.nodes.find((n) => n.id === 'ip-sensor-rear')?.kind).toBe('external')
    expect(g.nodes.find((n) => n.id === 'ip-panel')?.kind).toBe('external')
    expect(g.nodes.find((n) => n.id === 'ip-csis')?.group).toBe('g:isp-front')
    expect(g.nodes.find((n) => n.id === 'ip-mcsc')?.group).toBe('g:isp-nr')
    expect(g.nodes.find((n) => n.id === 'ip-eis')?.group).toBe('g:sw')
  })
  it('collapses a group into one node and reroutes edges', () => {
    const c = buildGraph(v, new Set(['g:isp-front']))
    expect(c.nodes.some((n) => n.id === 'ip-csis')).toBe(false)
    expect(c.nodes.find((n) => n.id === 'g:isp-front')?.kind).toBe('group')
    expect(c.edges.some((e) => e.source === 'g:isp-front' && e.target === 'buf:PYRAMID_L0')).toBe(true)
  })
  it('hides buffers, SW and control when asked', () => {
    const t = buildGraph(v, new Set(), new Set(['buffer', 'sw', 'control']))
    expect(t.nodes.some((n) => n.kind === 'buffer' || n.kind === 'sw')).toBe(false)
    expect(t.edges.every((e) => e.kind !== 'control')).toBe(true)
    expect(t.edges.some((e) => e.source === 'ip-mlsc' && e.target === 'ip-mtnr' && e.kind === 'M2M')).toBe(true)
  })
  it('maps view ids to pipeline ids', () => {
    expect(pipelineIdOf('ip-gdc-o')).toBe('gdc_o')
    expect(pipelineIdOf('ip-sensor-rear')).toBe('sensor_rear')
  })
})

describe('layout', () => {
  it('produces orthogonal edges inside the canvas', async () => {
    const layout = await layoutGraph(buildGraph(v))
    expect(layout.nodes.length).toBeGreaterThan(20)
    for (const e of layout.edges) {
      for (let i = 1; i < e.points.length; i++) {
        const a = e.points[i - 1], b = e.points[i]
        // ELK may leave sub-pixel jogs; anything under 1px is still a straight segment.
        expect(Math.abs(a.x - b.x) <= 1 || Math.abs(a.y - b.y) <= 1).toBe(true)
      }
      for (const p of e.points) { expect(p.x).toBeGreaterThanOrEqual(-1); expect(p.y).toBeGreaterThanOrEqual(-1); expect(p.x).toBeLessThanOrEqual(layout.width + 1) }
    }
  }, 30000)
})

describe('dma table', () => {
  it('computes frame size estimates', () => {
    expect(frameMb({ width: 1920, height: 1080, format: 'YUV420', bitdepth: 8 })).toBe(2.97)
    expect(frameMb({ width: 2040, height: 1148, format: 'YUV444', bitdepth: 12 })).toBe(13.4)
    expect(frameMb({ format: 'BITSTREAM' })).toBeNull()
    const rows = dmaRows(v)
    expect(rows.find((r) => r.buffer === 'PYRAMID_L1')?.ports).toContain('MLSC_W_GLPG1_Y → MTNR1_RDMA_CUR_L1_Y')
  })
})
