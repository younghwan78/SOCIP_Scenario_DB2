import { describe, expect, it } from 'vitest'
import { DEFAULT_BATTERY } from './battery'
import { domainPoints, judgedKpis, summaryTiles } from './timingTiles'
import type { KpiResult, StageDomain, StageId, StageRow, TimingReport } from './timingBudget'

const stage = (id: StageId, o: Partial<StageRow> = {}): StageRow => ({
  id, name: id, nodes: [], sw_items: [], sw_ms: 0, budget_ms: 25, hw_ms: 0, overhead_ms: 0, margin: 0.25, feasible: true, fill_pct: 0,
  throughput: id === 'nrt' || id === 'post' ? 'pipelined' : 'frame', ...o,
})
const dom = (domain: string, nodes: string[], set_mhz: number, o: Partial<StageDomain> = {}): StageDomain => ({
  domain, ip: nodes[0], nodes, rule_mhz: set_mhz, required_mhz: set_mhz, set_mhz, level: null, rule_level: null, next_mhz: null,
  headroom_pct: null, hw_ms: 0, basis: 'budget', set_reason: 'exact', domain_leader: null, ...o,
})
const series = (node: string | null, max: number | null, ok: boolean | null) => ({ node, values: [], max_ms: max, min_ms: max, ok })
const kpi = (o: Partial<KpiResult>): KpiResult => ({ id: null, kpi: 'latency', metric: null, job: null, milestone: null, status: 'pass', value: 1, target: 2, bound: 'max', unit: 'ms', value_source: 'assumed', basis: null, sources: [], ...o })

function report(o: Partial<TimingReport> & { stages: StageRow[] }): TimingReport {
  return {
    scenario_id: 's', variant_id: 'v', fps: 30, period_ms: 33.333, statistic: 'mean',
    eis: { on: false, auto: true, mode: 'auto', stabilization: null }, mfc_dual: {}, growth: { runtime_scale: 1, latency_scale: 1 },
    dvfs: { tables: [], applied: true }, ips: [],
    intervals: { target_ms: 33.333, tolerance: 0.02, preview: series(null, null, null), video: series(null, null, null), ok: false },
    latency: { preview_ms: null, video_ms: null, preview_frames: null, video_frames: null },
    power: { total_mw: 100, cpu_mw: 50, hw_mw: 40, bw_mw: 10, bw_hw_mw: 10, bw_sw_mw: 0, share_pct: { cpu: 0, hw: 0, bw: 0 }, hw_by_ip: {}, cpu_by_task: {}, cpu_busy_ms: 1,
      cpu_model: { cluster: 0, freq_mhz: 1000, volt_v: 0.7, source: 'assumed' }, zero_power_ips: [] },
    bw: { total_mbs: 1000, hw_mbs: 1000, sw_mbs: 0, hw_by_ip: {}, sw_by_task: {}, share_pct: { hw: 100, sw: 0 } },
    verdict: { status: 'ok', reasons: [], nrt_clock_factor: null }, timeline: [], warnings: [],
    ...o,
  } as TimingReport
}

const ids = (r: TimingReport) => summaryTiles(r, 0.25, DEFAULT_BATTERY).map((t) => t.id)
const bad = (r: TimingReport) => summaryTiles(r, 0.25, DEFAULT_BATTERY).filter((t) => t.bad).map((t) => t.id)

describe('summaryTiles (X-01)', () => {
  it('keeps the camera recording tiles', () => {
    const r = report({
      stages: [stage('rt', { nodes: ['csis', 'byrp'], hw_ms: 10.2 }), stage('nrt', { nodes: ['mcsc'], sw_items: [{ task: 'a', kind: 'sw', runtime_ms: 8.3, latency_ms: 0, source: 'x' }], sw_ms: 8.3, hw_ms: 18.5 }),
        stage('post', { nodes: ['eis'], sw_items: [{ task: 'eis', kind: 'sw', runtime_ms: 3, latency_ms: 0, source: 'x' }], sw_ms: 3 }), stage('output', { nodes: ['dpu', 'mfc_enc'], hw_ms: 4.1 })],
      eis: { on: true, auto: true, mode: 'auto', stabilization: null },
      stage_domains: { nrt: [dom('CAM', ['mcsc'], 333, { rule_mhz: 333, level: 5, headroom_pct: 30 })] },
      intervals: { target_ms: 33.333, tolerance: 0.02, preview: series('dpu', 33.33, true), video: series('mfc_enc', 33.33, true), ok: true },
    })
    expect(ids(r)).toEqual(['rt', 'nrt', 'post', 'clock', 'slack', 'interval', 'power'])
    const t = summaryTiles(r, 0.25, DEFAULT_BATTERY)
    expect(t.find((x) => x.id === 'interval')).toMatchObject({ label: 'Preview / Video 간격', value: '33.33 / 33.33', bad: false })
    expect(t.find((x) => x.id === 'post')?.label).toBe('Post SW (EIS 등)')
    expect(t.find((x) => x.id === 'clock')?.value).toBe('CAM 333')
    expect(bad(r)).toEqual([])
  })

  it('still flags a real interval miss', () => {
    const r = report({ stages: [stage('output', { nodes: ['dpu'], hw_ms: 4 })], intervals: { target_ms: 33.333, tolerance: 0.02, preview: series('dpu', 40, false), video: series(null, null, null), ok: false } })
    const t = summaryTiles(r, 0.25, DEFAULT_BATTERY).find((x) => x.id === 'interval')
    expect(t).toMatchObject({ label: 'Preview 간격', value: '40.00', note: '목표 이탈', bad: true })
  })

  it('capture: no interval tile without a judged output; job milestones and KPI targets instead', () => {
    const r = report({
      stages: [stage('rt', { nodes: ['csispdp'], hw_ms: 9.85 }), stage('nrt', { nodes: ['byrp'], hw_ms: 19.7 }), stage('post'), stage('output')],
      stage_domains: { nrt: [dom('CAM', ['byrp'], 1066)] },
      jobs: [{ id: 'still_shot', model: 'job-v1', milestones: { saved: 56.3, thumbnail: 22.97 }, makespan_ms: 56.3, phases: [], stages: [], peak: { window_ms: 10, power_mw: 1151.8, power_instant_mw: 4214, bw_mbs: 5655, bw_instant_mbs: 24000, footprint_mb: 112 } }],
      kpis: [kpi({ id: 'saved-12m', kpi: 'event_latency', job: 'still_shot', milestone: 'saved', value: 56.3, target: 500 }), kpi({ kpi: 'event_energy', status: 'no_target', target: null }),
        kpi({ id: 'heap', kpi: 'peak_footprint', status: 'fail', value: 2128, target: 2048, unit: 'MB' }), kpi({ id: 'bw-10ms', kpi: 'peak_bw', value: 5655, target: 50000, unit: 'MB/s' }),
        kpi({ id: 'thumb', kpi: 'event_latency', job: 'still_shot', milestone: 'thumbnail', value: 22.97, target: 300 })],
    })
    expect(ids(r)).not.toContain('interval')
    expect(ids(r)).not.toContain('post')
    const t = summaryTiles(r, 0.25, DEFAULT_BATTERY)
    expect(t.find((x) => x.id === 'job-still_shot')).toMatchObject({ value: '56.3', bad: false })
    expect(t.find((x) => x.id === 'job-still_shot')?.note).toContain('thumbnail 23.0 · saved 56.3')
    const k = t.filter((x) => x.id.startsWith('kpi-'))
    expect(k.map((x) => x.label)).toEqual(['peak memory', '촬영 → saved', 'peak BW'])
    expect(k[0].bad).toBe(true)
    expect(k[2].note).toContain('외 KPI 1개')
    expect(bad(r)).toEqual([k[0].id])
  })

  it('audio: no stage or interval tiles, AUD from the subsystem, KPI and ABOX tiles', () => {
    const r = report({
      verdict: { status: 'not_applicable', reasons: [], nrt_clock_factor: null },
      stages: [stage('rt'), stage('nrt', { nodes: ['abox', 'audio_hal', 'bt_codec', 'storage'] }), stage('post'), stage('output')],
      stage_domains: { rt: [], nrt: [dom('INT', ['storage'], 133, { level: 5, set_reason: 'dvfs_floor' }), dom('AUD', ['abox', 'audio_hal', 'bt_codec'], 0)], post: [], output: [] },
      power: { ...report({ stages: [] }).power, residency_mw: 50, domain_loads: { abox: { model: 'mcps-v1', mw: 2.477, feasible: true, freq_mhz: 200, util: 0.125, value_source: 'assumed', unattributed_units: [] } } },
      kpis: [kpi({ id: 'aud-slack', kpi: 'underrun', value: 4.375, target: 0.5, bound: 'min' }), kpi({ kpi: 'latency', value: 50.775, target: 80 })],
    })
    expect(ids(r)).toEqual(['clock', 'kpi-0', 'kpi-1', 'load-abox', 'power'])
    const t = summaryTiles(r, 0.25, DEFAULT_BATTERY)
    expect(t[0]).toMatchObject({ value: 'INT 133 · AUD 200', bad: false })
    expect(t[0].note).toContain('AUD ABOX subsystem')
    expect(t[1]).toMatchObject({ label: 'deadline 여유 (underrun)', value: '4.38' })
    expect(t[1].note).toContain('목표 ≥ 0.50 ms')
    expect(t.find((x) => x.id === 'load-abox')?.note).toContain('200 MHz subsystem')
    expect(t.find((x) => x.id === 'power')?.note).toContain('wake 50')
    expect(bad(r)).toEqual([])
  })

  it('game: GPU clock from the domain load, pacing tile', () => {
    const r = report({
      fps: 120, period_ms: 8.333,
      stages: [stage('rt'), stage('nrt', { nodes: ['gpu'], sw_items: [{ task: 'game_logic', kind: 'sw', runtime_ms: 4, latency_ms: 0, source: 'x' }], sw_ms: 4 }), stage('post'), stage('output', { nodes: ['dpu'], hw_ms: 6.56 })],
      stage_domains: { nrt: [dom('gpu', ['gpu'], 0)] },
      intervals: { target_ms: 8.333, tolerance: 0.02, preview: series('dpu', 8.333, true), video: series(null, null, null), ok: true },
      power: { ...report({ stages: [] }).power, domain_loads: { gpu: { model: 'util-vf-v1', work_mcycles_s: 480, freq_mhz: 605, freq_by: 'governor', f_max_mhz: 980, mv: 700, util: 0.7934, target_util: 0.85, dynamic_mw: 3142, static_mw: 30, mw: 3172.5, feasible: true, value_source: 'assumed' } } },
      pacing: { model: 'frame-pacing-v1', node: 'gpu', status: 'ok', target_fps: 120, achieved_fps: 119.79, fail_below_fps: 117.6, jank_pct: 0.176 },
    })
    const t = summaryTiles(r, 0.25, DEFAULT_BATTERY)
    expect(t.map((x) => x.id)).toEqual(['nrt', 'clock', 'slack', 'interval', 'pacing', 'load-gpu', 'power'])
    expect(t.find((x) => x.id === 'clock')?.value).toBe('gpu 605')
    expect(t.find((x) => x.id === 'clock')?.note).toContain('governor · util 79%')
    expect(t.find((x) => x.id === 'slack')?.note).toMatch(/^NRT — /)
    expect(t.find((x) => x.id === 'pacing')?.value).toBe('119.8 / 120')
    expect(bad(r)).toEqual([])
  })

  it('a domain with no operating point says so instead of 0 MHz', () => {
    const r = report({ stages: [stage('nrt', { nodes: ['x'] })], stage_domains: { nrt: [dom('NPU', ['x'], 0)] } })
    const p = domainPoints(r, 'nrt')
    expect(p[0]).toMatchObject({ mhz: null, source: 'none' })
    expect(summaryTiles(r, 0.25, DEFAULT_BATTERY).find((x) => x.id === 'clock')).toMatchObject({ value: '운영점 없음', unit: '' })
  })
})

describe('judgedKpis', () => {
  it('lists failing targeted rows first and skips rows without a target', () => {
    const rows = [kpi({ id: 'a' }), kpi({ id: 'b', status: 'fail' }), kpi({ id: 'c', status: 'no_target', target: null }), kpi({ id: 'd', status: 'no_input' })]
    const out = judgedKpis(rows, 1)
    expect(out.shown.map((k) => k.id)).toEqual(['b'])
    expect(out.rest).toBe(1)
  })
})
