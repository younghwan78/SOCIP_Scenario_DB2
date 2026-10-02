import { describe, expect, it } from 'vitest'
import { categoryFit, issueCounts, powerScope, provText, reportsForProject, statusItems, verdictIssues, type ModelStatus } from './provenance'
import type { ReportMeta } from './archExplore'

const rep = (id: string, project_ref: string | null) => ({ id, project_ref } as ReportMeta)

describe('reportsForProject (U7)', () => {
  it('keeps other projects out of the default list', () => {
    const { mine, others } = reportsForProject([rep('a', 'proj-sm-s957b'), rep('b', 'proj-sm-s947b'), rep('c', null)], 'proj-sm-s947b')
    expect(mine.map((r) => r.id)).toEqual(['b'])
    expect(others.map((r) => r.id)).toEqual(['a', 'c'])
  })
})

describe('verdictIssues (U4)', () => {
  const reasons = [
    'NRT: SW 11.10 ms leaves no HW budget',
    'RT HW 6.40 ms > 75% budget 6.25 ms',
    'preview interval 10.267 ms != 8.333 ms',
    'video interval 10.267 ms != 8.333 ms',
    'msnr: required_clock 1348.8MHz exceeds max DVFS speed 1066.0MHz',
    'byrp: required_clock 1348.8MHz exceeds max DVFS speed 1066.0MHz',
  ]
  it('classifies timing_budget reason strings', () => {
    expect(verdictIssues(reasons).map((i) => i.code)).toEqual(['sw_budget', 'rt_budget', 'interval', 'interval', 'ip_clock'])
    expect(verdictIssues(reasons)[4].label).toBe('DVFS max 초과 · msnr 외 1')
    expect(verdictIssues(reasons)[4].detail.split('\n')).toHaveLength(2)
    expect(verdictIssues(reasons)[0].label).toBe('NRT SW 11.1 ms')
    expect(verdictIssues(['something odd happened here today'])[0].code).toBe('other')
  })
  it('counts rows once per code', () => {
    expect(issueCounts([reasons, [reasons[2]], []])).toEqual({ sw_budget: 1, rt_budget: 1, interval: 2, ip_clock: 1, other: 0 })
  })
})

describe('categoryFit (U6)', () => {
  const rows = [{ category: 'cpu', delta_pct: 3.3 }, { category: 'ip', delta_pct: -35.2 }, { category: 'bw', delta_pct: 50.1 }, { category: 'other', delta_pct: null }]
  it('flags a total that matches by compensation', () => {
    expect(categoryFit(rows, 0.9)).toEqual({ worst_category: 'bw', worst_delta_pct: 50.1, offsetting: true })
    expect(categoryFit(rows, -12.8).offsetting).toBe(false)
    expect(categoryFit(null, 1)).toEqual({ worst_category: null, worst_delta_pct: null, offsetting: false })
  })
})

describe('provenance text (U1)', () => {
  it('names engine, scope and sample DVFS', () => {
    const t = provText({ kind: 'recalc', engine: 'Timing Budget', scope: 'CPU + IP + BW', dvfs: 'dvfs-exynos2600-sample-v0' })
    expect(t).toContain('재계산 · Timing Budget')
    expect(t).toContain('(SAMPLE)')
    expect(powerScope({ cpu: 0, ip: 120, bw: 300 })).toBe('IP + BW')
  })
})

describe('statusItems (U2)', () => {
  const s: ModelStatus = { engine_rev: 'arch-exploration/5', project_ref: 'p', predictions: { current: 54, stale_engine: 54, engines: { 'arch-exploration/4': 54 } },
    dvfs: [{ ref: 'dvfs-exynos2600-sample-v0', sample: true, predictions: 54 }], measurements: { real: 1, synthetic: 32 }, lineage: { power_model: 'v2-vf' } }
  it('warns on sample DVFS and stale predictions', () => {
    const items = statusItems(s, 'p')
    expect(items.find((i) => i.key === 'dvfs')?.level).toBe('warn')
    expect(items.find((i) => i.key === 'pred')?.text).toBe('등록 예측 54/54 이전 model')
    expect(items.find((i) => i.key === 'meas')?.level).toBe('ok')
    expect(items.find((i) => i.key === 'model')?.text).toContain('v2-vf')
  })
  it('says the DVFS table was not recorded instead of "not connected" for old runs', () => {
    const old = { ...s, dvfs: [], dvfs_unrecorded: 54, measurements: { real: 1, synthetic: 33, empty: 1 } }
    const items = statusItems(old, 'p')
    expect(items.find((i) => i.key === 'dvfs')?.text).toBe('DVFS 미기록 (이전 run)')
    expect(items.find((i) => i.key === 'meas')?.text).toBe('실측 1 · 합성 33 · 전력 없음 1')
    expect(statusItems({ ...s, dvfs: [], predictions: { current: 0, stale_engine: 0, engines: {} } }).find((i) => i.key === 'dvfs')?.level).toBe('info')
  })
})
