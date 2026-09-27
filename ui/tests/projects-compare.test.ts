import { describe, expect, it } from 'vitest'
import view from './fixtures/view-uhd30-vdis.json'
import type { CatalogItem, VariantDetail, ViewResponse } from '../src/lib/api'
import { addItem, canonicalKey, canonicalOf, compareItems, counterpart, defaultScenario, formatItems, parseItems, projectTag, projectsOf } from '../src/lib/projects'
import { insights, ipShort, itemLabels, nodeIps, nodeSizes, pixels } from '../src/lib/compare'

const cat = (project: string, soc: string, board: string, scenario: string, name: string, canonical?: string, variants = 10): CatalogItem => ({
  project_id: project, soc_ref: soc, board_type: board, scenario_id: scenario, scenario_name: name, canonical_usecase: canonical,
  category: ['camera'], domain: [], variant_count: variants, severity_counts: {}, node_count: 0, edge_count: 0, buffer_count: 0,
})
const CATALOG: CatalogItem[] = [
  cat('proj-sm-s957b', 'soc-exynos2700', 'SM-S957B', 'uc-cam-recording-e2700', 'Camera Recording', 'uc-cam-recording', 78),
  cat('proj-sm-s957b', 'soc-exynos2700', 'SM-S957B', 'uc-cam-preview-e2700', 'Camera Preview', 'uc-cam-preview'),
  cat('proj-sm-s947b', 'soc-exynos2600', 'SM-S947B', 'uc-cam-preview-e2600', 'Camera Preview', 'uc-cam-preview'),
  cat('proj-sm-s947b', 'soc-exynos2600', 'SM-S947B', 'uc-cam-recording-e2600', 'Camera Recording', 'uc-cam-recording', 75),
]

describe('project scoping', () => {
  it('lists projects ordered by SoC with counts', () => {
    const p = projectsOf(CATALOG)
    expect(p.map((x) => x.id)).toEqual(['proj-sm-s947b', 'proj-sm-s957b'])
    expect(p[1]).toMatchObject({ soc: 'Exynos2700', board: 'SM-S957B', scenarios: 2, variants: 88 })
    expect(projectTag(p[1], p)).toBe('2700')
  })
  it('maps a scenario to the same use case in another project', () => {
    expect(counterpart(CATALOG, CATALOG[3], 'proj-sm-s957b')?.scenario_id).toBe('uc-cam-recording-e2700')
    expect(canonicalOf({ scenario_id: 'uc-x', canonical_usecase: null })).toBe('uc-x')
    expect(canonicalOf({ scenario_id: 'uc-cam-preview-e2800c', canonical_usecase: null })).toBe('uc-cam-preview')
    expect(canonicalKey('uc-camera-recording')).toBe('uc-cam-recording')
    expect(defaultScenario(CATALOG.filter((c) => c.project_id === 'proj-sm-s957b'))?.scenario_id).toBe('uc-cam-recording-e2700')
  })
})

describe('comparison items', () => {
  it('round-trips, dedupes and accepts legacy variants=', () => {
    const items = parseItems('uc-cam-recording-e2600~cam-rec-r1-uhd30-vdis,uc-cam-recording-e2700~cam-rec-r1-uhd30-pro,uc-cam-recording-e2600~cam-rec-r1-uhd30-vdis,bad')
    expect(items).toHaveLength(2)
    expect(parseItems(formatItems(items))).toEqual(items)
    expect(compareItems({ variants: 'a,b,a' }, 'uc-s', 'x')).toEqual([{ scenario: 'uc-s', variant: 'a' }, { scenario: 'uc-s', variant: 'b' }])
    expect(addItem(items, items[0])).toBe(items)
    expect(addItem(items, { scenario: 'uc-cam-preview-e2600', variant: 'v' })).toHaveLength(3)
  })
  it('labels carry a project tag / scenario only when they differ', () => {
    const p = projectsOf(CATALOG)
    const same = itemLabels([{ scenario: 'uc-cam-recording-e2600', variant: 'cam-rec-r1-uhd30-vdis' }, { scenario: 'uc-cam-recording-e2600', variant: 'cam-rec-r1-fhd30-vdis' }], CATALOG, p)
    expect(same.map((l) => l.short)).toEqual(['uhd30-vdis', 'fhd30-vdis'])
    const cross = itemLabels([{ scenario: 'uc-cam-recording-e2600', variant: 'cam-rec-r1-uhd30-vdis' }, { scenario: 'uc-cam-recording-e2700', variant: 'cam-rec-r1-uhd30-pro' }, { scenario: 'uc-cam-preview-e2600', variant: 'p1' }], CATALOG, p)
    expect(cross[1].short).toBe('2700 · Camera Recording · cam-rec-r1-uhd30-pro')
    expect(cross[0].full).toContain('Exynos2600 SM-S947B')
  })
})

describe('HW / size diff and insights', () => {
  it('normalizes IP refs across SoC tags', () => {
    expect(ipShort('ip-mtnr-is-v15-s5e9965')).toBe(ipShort('ip-mtnr-is-v15-s5e9975'))
    expect(ipShort('ip-nr-v2-exynos2800c')).toBe('nr-v2')
    expect(ipShort('ip-sensor-imx564-ff-s5e9965')).toBe('sensor-imx564-ff')
  })
  it('extracts node IPs from a view and sizes from node_configs', () => {
    const ips = nodeIps(view as unknown as ViewResponse)
    expect(ips.size).toBeGreaterThan(5)
    const sizes = nodeSizes({ id: 'v', scenario_id: 's', node_configs: { mtnr: { sim: { width: 3760, height: 2114 } }, eis: { sw_timing: {} } } } as VariantDetail)
    expect([...sizes]).toEqual([['mtnr', '3760×2114']])
    expect(pixels('4080×2296')).toBe(4080 * 2296)
  })
  it('computes KPI / DMA deltas and top-moving IPs vs the reference', () => {
    const f = insights({
      n: 2,
      kpi: [{ label: 'Total power', unit: 'mW', values: [559.4, 507.4] }, { label: 'Frame latency', unit: 'ms', values: [null, 30] }],
      dma: [5367, 4858],
      traffic: [new Map([['MTNR', 1200], ['MCSC', 800], ['DPU', 100]]), new Map([['MTNR', 1000], ['MCSC', 700], ['DPU', 100]])],
      changedConditions: [0, 3],
      ipMaps: [new Map([['mtnr', 'mtnr-is-v15']]), new Map([['mtnr', 'nr-v2']])],
      sizeMaps: [new Map([['mtnr', '4080×2296']]), new Map([['mtnr', '3760×2114']])],
    })
    expect(f).toHaveLength(1)
    expect(f[0].kpi).toHaveLength(1)
    expect(f[0].kpi[0].pct).toBeCloseTo(-9.3, 1)
    expect(f[0].dmaTotal?.pct).toBeCloseTo(-9.48, 1)
    expect(f[0].topIp.map((t) => t.ip)).toEqual(['MTNR', 'MCSC'])
    expect(f[0].changed).toEqual({ conditions: 3, ips: 1, sizes: 1 })
  })
})

it('does not report a zero baseline as zero percent change', () => {
  const result = insights({ n: 2, kpi: [{ label: 'power', unit: 'mW', values: [0, 10] }],
    dma: [0, 20], traffic: [], changedConditions: [], ipMaps: [], sizeMaps: [] })
  expect(result[0].kpi[0].pct).toBeNull()
  expect(result[0].dmaTotal?.pct).toBeNull()
})
