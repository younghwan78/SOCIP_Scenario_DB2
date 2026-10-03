// @vitest-environment jsdom
// Scale probe for the React UI (run: PERF=1 npx vitest run src/perf). Skipped in the normal suite.
// jsdom is slower than a browser at layout-free DOM work but scales the same way: read the ratios
// between sizes and the DOM node counts, not the absolute milliseconds.
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it } from 'vitest'
import { DataTable, type Column } from '../components/DataTable'
import { RangeBoxes } from '../components/ArchCharts'
import { medoidId, varyingKeys } from '../lib/conditions'
import type { VariantRow } from '../lib/api'

declare const process: { env: Record<string, string | undefined> }
const ON = !!process.env.PERF
const SIZES = [1000, 10000]
const AX: Record<string, unknown[]> = {
  resolution: ['FHD', 'UHD', '8K', 'QHD'], fps: [24, 30, 60, 120, 240], hdr: ['SDR', 'HDR10', 'HLG'],
  stabilization: ['none', 'ois', 'vdis', 'supersteady'], codec_mfc: ['HEVC', 'AVC', 'APV'], camera_mode: ['rear', 'front', 'dual'],
}
const rows = (n: number): VariantRow[] => Array.from({ length: n }, (_, i) => ({
  project_id: 'p', scenario_id: `s${Math.floor(i / 100)}`, variant_id: `v-${String(i).padStart(5, '0')}`,
  design_conditions: Object.fromEntries(Object.entries(AX).map(([k, v], j) => [k, v[Math.floor(i / (j + 1)) % v.length]])),
}))
const ms = (fn: () => void) => { const t = performance.now(); fn(); return Math.round(performance.now() - t) }
const out: Record<string, unknown> = {}
// jsdom has no ResizeObserver (chart width hook)
;(globalThis as { ResizeObserver?: unknown }).ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} }

describe.skipIf(!ON)('UI scale probe', () => {
  for (const n of SIZES) {
    it(`varyingKeys · ${n} variants`, () => { out[`varyingKeys ${n} ms`] = ms(() => varyingKeys(rows(n))) })

    it(`DataTable mount · ${n} rows × 12 cols`, { timeout: 60_000 }, async () => {
      const r = rows(n)
      const cols: Column<VariantRow>[] = [
        { key: 'id', label: 'Variant', sort: (x) => x.variant_id, render: (x) => x.variant_id, sticky: true },
        ...Object.keys(AX).map((k) => ({ key: k, label: k, sort: (x: VariantRow) => String(x.design_conditions[k]), render: (x: VariantRow) => String(x.design_conditions[k]) })),
        ...['a', 'b', 'c', 'd', 'e'].map((k) => ({ key: k, label: k, render: (x: VariantRow) => x.scenario_id })),
      ]
      const host = document.createElement('div')
      document.body.appendChild(host)
      const root = createRoot(host)
      const t = performance.now()
      await act(async () => { root.render(createElement(DataTable<VariantRow>, { id: `perf${n}`, columns: cols, rows: r, rowKey: (x) => x.variant_id })) })
      out[`DataTable mount ${n} ms`] = Math.round(performance.now() - t)
      out[`DataTable DOM nodes ${n}`] = host.querySelectorAll('*').length
      expect(host.querySelectorAll('tbody tr').length).toBe(n)
      await act(async () => root.unmount())
      host.remove()
    })
  }

  // medoid is O(n²) over ONE scenario's variants (Explorer passes the selected scenario only)
  for (const n of [100, 500, 1000, 2000]) {
    it(`medoidId · ${n} variants in one scenario`, () => { out[`medoidId ${n} ms`] = ms(() => medoidId(rows(n))) }, 60_000)
  }

  it('RangeBoxes (Explore range card) · 500 variants', async () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const root = createRoot(host)
    const data = Array.from({ length: 500 }, (_, i) => ({ id: `v${i}`, label: `v${i}`, ok: true, marker: 800 + i, base: 900 + i,
      dist: { min: 700 + i, p25: 750 + i, median: 800 + i, p75: 850 + i, max: 950 + i } }))
    const t = performance.now()
    await act(async () => { root.render(createElement(RangeBoxes, { rows: data, unit: 'mW' })) })
    out['RangeBoxes mount 500 ms'] = Math.round(performance.now() - t)
    out['RangeBoxes DOM nodes 500'] = host.querySelectorAll('*').length
    await act(async () => root.unmount())
  })

  it('JSON.parse of a max exploration run payload (~31.5 MB)', { timeout: 60_000 }, () => {
    // 500 variant summaries ≈ 67 KB each (bench_scale.py measured 31,565,794 bytes)
    const one = { slices: Array.from({ length: 6 }, (_, i) => ({ i, stages: Array.from({ length: 40 }, (_, j) => ({ j, v: Math.random(), k: 'x'.repeat(20) })) })),
      buffers: Array.from({ length: 40 }, (_, i) => ({ i, mode: 'COMP_YUV_LOSSY', modes: ['a', 'b'], d: Math.random(), note: 'y'.repeat(200) })),
      opts: Array.from({ length: 64 }, (_, i) => ({ i, labels: ['bcrop', 'L0 skip'], delta: Math.random(), items: Array.from({ length: 8 }, () => 'z'.repeat(40)) })) }
    let s = JSON.stringify(Array.from({ length: 500 }, () => one))
    const target = 31_565_794
    while (s.length < target) s = s.slice(0, -1) + ',' + JSON.stringify(one) + ']'
    out['run payload bytes'] = s.length
    out['JSON.parse run payload ms'] = ms(() => JSON.parse(s))
  })

  it('report', () => { console.log('\nUI_SCALE ' + JSON.stringify(out, null, 1)); expect(true).toBe(true) })
})
