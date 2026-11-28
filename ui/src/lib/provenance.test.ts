import { describe, expect, it } from 'vitest'
import { categoryFit, issueCounts, powerScope, provText, readableBasis, reportsForProject, statusItems, verdictIssues, type ModelStatus } from './provenance'
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
  it('keeps a read-out-bound RT miss in the RT budget class', () => {
    const [i] = verdictIssues(['RT HW 23.35 ms > 65% budget 21.67 ms — sensor readout 23.35 ms (frame period 33.333 ms의 70%)가 정하는 시간이라 clock으로 줄일 수 없음 (sensor mode · blanking 또는 margin 조정)'])
    expect(i).toMatchObject({ code: 'rt_budget', label: 'RT 23.4>21.7 ms · readout' })
  })
  it('counts rows once per code', () => {
    expect(issueCounts([reasons, [reasons[2]], []])).toEqual({ sw_budget: 1, rt_budget: 1, interval: 2, ip_clock: 1, kpi: 0, other: 0 })
  })
  it('reads an M-10 KPI fail as a KPI issue, not an IP clock one', () => {
    const [i] = verdictIssues(['KPI heap: 2128.43 MB > 2048 MB (가정 목표)'])
    expect(i).toMatchObject({ code: 'kpi', label: 'heap 2128>2048 MB' })
    expect(verdictIssues(['KPI aud-slack: 0.3 ms < 0.5 ms'])[0]).toMatchObject({ code: 'kpi', label: 'aud-slack 0<1 ms' })
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
    expect(items.find((i) => i.key === 'meas')?.text).toBe('capture 실측 1 · 합성 33 · 전력 없음 1')
    expect(statusItems({ ...s, dvfs: [], predictions: { current: 0, stale_engine: 0, engines: {} } }).find((i) => i.key === 'dvfs')?.text).toBe('DVFS table 없음')
  })
  it('names the default table analyses use when nothing is registered (not "DVFS 없음")', () => {
    const empty = { ...s, dvfs: [], predictions: { current: 0, stale_engine: 0, engines: {} }, dvfs_default: { ref: 'dvfs-exynos2600-sample-v0', sample: true } }
    const d = statusItems(empty, 'p').find((i) => i.key === 'dvfs')!
    expect(d.text).toBe('DVFS sample-v0 SAMPLE · 기본')
    expect(d.level).toBe('warn')
    expect(d.title).toContain('예측 기록 기준 DVFS는 0건')
    // an active basis pins the table analyses use (apply_basis), so the status names it as such
    const pinned = statusItems({ ...empty, dvfs_default: { ref: 'dvfs-exynos2600-v1', sample: false, source: 'basis' } }, 'p').find((i) => i.key === 'dvfs')!
    expect(pinned.text).toBe('DVFS v1 · 예측 기준')
    expect(pinned.title).toContain('active 예측 기준이 지정')
  })
})

describe('P0 prediction basis in the model status', () => {
  it('names the bases instead of a count', () => {
    const items = statusItems({ engine_rev: 'arch-exploration/11', project_ref: 'p', predictions: { current: 54, stale_engine: 54, engines: { 'arch-exploration/9': 54 } },
      dvfs: [], measurements: { real: 1, synthetic: 34 }, lineage: null,
      bases: [{ label: '미기록 · e9', key: 'k', recorded: false, predictions: 54, config_profile_ref: null, power_params_ref: null, dvfs_table_ref: 'd', engine_rev: 'arch-exploration/9' }],
      sw: [{ label: '1.2.3', predictions: 54 }] })
    const p = items.find((i) => i.key === 'pred')!
    expect(p.text).toBe('⚠ 예측 기준: 설정 미기록 · engine 9 · 54건 · SW 1.2.3 · 이전 engine 54/54')
    expect(p.title).toContain('설정 선택(config profile · power params)을 기록하지 않은')
    expect(p.level).toBe('warn')
  })
  it('spells the basis label out (X-11)', () => {
    expect(readableBasis('cfg? · pmp2 · e16')).toEqual({ text: 'config 버전 미기록 · power params v2 · engine 16', unknown: ['config profile은 기록됐지만 그 버전이 catalog에 없음'] })
    expect(readableBasis('cfg 기본 · pmp 기본 · e16').text).toBe('config 기본 · power params 기본 · engine 16')
    expect(readableBasis('cfg2 · pmp? · e?')).toEqual({ text: 'config v2 · power params 버전 미기록 · engine 미기록',
      unknown: ['power params는 기록됐지만 그 버전이 catalog에 없음', 'engine revision 미기록'] })
    // a non-digit engine revision is passed through as is
    expect(readableBasis('cfg2 · pmp2 · arch-exploration/dev').text).toBe('config v2 · power params v2 · arch-exploration/dev')
  })
})
