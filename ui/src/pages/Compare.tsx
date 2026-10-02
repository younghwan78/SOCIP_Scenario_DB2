import { useMemo, useState, type ReactNode } from 'react'
import type { Ctx } from '../App'
import { api, type Dict, type Evidence, type ScenarioDef, type SimRunResponse, type VariantRow, type ViewResponse } from '../lib/api'
import { useAsync } from '../lib/route'
import { MISSING, evidenceSource, valueText, varyingKeys } from '../lib/conditions'
import { compareItems, formatItems, type CompareItem } from '../lib/projects'
import { insights, itemLabels, nodeIps, nodeSizes, pixels, type Insight } from '../lib/compare'
import { memoryText } from '../lib/graph'
import { buildModel, trafficByIp, type PipelineModel } from '../lib/model'
import { buildTimeline } from '../lib/timeline'
import { analyse, type CadenceResult } from '../lib/cadence'
import { SEVERITY_RANK } from '../lib/defaults'
import { toRows } from '../components/Picker'
import { PageLayout, usePref } from '../components/Layout'
import { DataTable, type Column, type RowGroup, type SortValue } from '../components/DataTable'
import { Bars, BoxPlot, SERIES, StackedBars } from '../components/Charts'
import { PowerDeltaTable, PowerStack, type PowerRow } from '../components/PowerModelCharts'
import { cpuSource, mifSummary, powerModelParts } from '../lib/powerModel'
import { CompareSummary, type ItemInfo, type MetricRow } from '../components/CompareSummary'
import { pickProfile } from '../lib/simProfile'

const KPI_FIELDS: [string, string, string][] = [
  ['Total power', 'total_power_mw', 'mW'], ['Core power', 'core_power_mw', 'mW'], ['BW power', 'bw_power_mw', 'mW'],
  ['Total BW', 'total_bw_mbs', 'MB/s'], ['Frame latency', 'frame_latency_ms', 'ms'], ['HW time max', 'hw_time_max_ms', 'ms'], ['Effective fps', 'fps_effective', 'fps'],
]

export function kpiNumber(v: unknown): number | null {
  if (typeof v === 'number') return v
  if (v && typeof v === 'object') for (const k of ['mean', 'value', 'p50']) { const x = (v as Dict)[k]; if (typeof x === 'number') return x }
  return null
}

export function transfers(view: ViewResponse | undefined): Map<string, string> {
  const out = new Map<string, string>()
  if (!view) return out
  const label = new Map(view.nodes.map((n) => [n.data.id, n.data.label]))
  for (const { data: e } of view.edges) {
    if (e.flow_type !== 'M2M') continue
    out.set(`${label.get(e.source) ?? e.source} → ${e.buffer_ref ?? '?'} → ${label.get(e.target) ?? e.target}`, memoryText(e.memory) || '✓')
  }
  return out
}

function pickEvidence(items: Evidence[]): Evidence | undefined {
  const rank = { measured: 0, calculated: 1, synthetic: 2, assumed: 3 }
  return [...items].filter((e) => e.kpi && Object.keys(e.kpi).length).sort((a, b) => rank[evidenceSource(a)] - rank[evidenceSource(b)])[0]
}
function pickTrace(items: Evidence[]): Evidence | undefined {
  const score = (e: Evidence) => { const t = e.timeline_events ?? []; return (t.some((x) => /^(panel|dpu|mfc)/.test(String(x.node_id ?? ''))) ? 1000 : 0) + new Set(t.map((x) => x.frame_index)).size }
  return items.filter((e) => (e.timeline_events ?? []).length > 3).sort((a, b) => score(b) - score(a))[0]
}

interface Item { id: string; section: string; label: ReactNode; sortLabel: string; values: (string | null)[]; nums: (number | null)[]; cls: string[] }

const num = (s: string | null): number | null => { if (s === null) return null; const m = s.replace(/,/g, '').match(/-?\d+(\.\d+)?/); return m ? Number(m[0]) : null }

type SimState = { status: 'running' } | { status: 'done'; res: SimRunResponse } | { status: 'error'; error: string }

export function ComparePage({ ctx }: { ctx: Ctx }) {
  const cItems: CompareItem[] = compareItems(ctx.params, ctx.scenario, ctx.variant)
  const ids = cItems.map((it) => `${it.scenario}~${it.variant}`)
  const key = ids.join(',')
  const catOf = (s: string) => ctx.allCatalog.find((c) => c.scenario_id === s)
  const scnIds = [...new Set(cItems.map((it) => it.scenario))]
  const scnKey = scnIds.join(',')
  const variantsQ = useAsync(() => Promise.all(scnIds.map((s) => api.variants(s).then((r) => [s, r.items] as const))), [scnKey])
  const scnQ = useAsync(() => Promise.all(scnIds.map((s) => api.scenario(s).catch(() => null).then((d) => [s, d] as const))), [scnKey])
  const scnDef = (s: string): ScenarioDef | null | undefined => scnQ.data?.find(([k]) => k === s)?.[1]
  const viewsQ = useAsync(() => Promise.all(cItems.map((it) => api.view(it.scenario, it.variant, 1))), [key])
  const detailsQ = useAsync(() => Promise.all(cItems.map((it) => api.variant(it.scenario, it.variant))), [key])
  const evQ = useAsync(() => Promise.all(cItems.map((it) => api.evidenceList(it.scenario, it.variant, catOf(it.scenario)?.project_id).then((r) => r.items))), [key, ctx.allCatalog.length])
  const [onlyDiff, setOnlyDiff] = useState(true)
  const [orient, setOrient] = usePref<'items' | 'variants'>('compare.orient', 'items')
  const [show, setShow] = usePref<'both' | 'table' | 'plot'>('compare.show', 'both')
  const [sims, setSims] = useState<Record<string, SimState>>({})
  // evidence: measured/registered KPI first (mixed sources) · sim: every column from the same simulation model
  const [kpiMode, setKpiMode] = usePref<'evidence' | 'sim'>('compare.kpi', 'evidence')

  const rows = useMemo(() => new Map((variantsQ.data ?? []).map(([s, items]) => [s, toRows(catOf(s), items)])), [variantsQ.data, ctx.allCatalog]) // eslint-disable-line react-hooks/exhaustive-deps
  const selected = cItems.map((it): VariantRow => rows.get(it.scenario)?.find((r) => r.variant_id === it.variant)
    ?? { project_id: catOf(it.scenario)?.project_id ?? '', scenario_id: it.scenario, variant_id: it.variant, design_conditions: {} })
  const missing = variantsQ.data ? cItems.filter((it) => !rows.get(it.scenario)?.some((r) => r.variant_id === it.variant)).map((it) => `${it.scenario} · ${it.variant}`) : []
  const itemLbl = itemLabels(cItems, ctx.allCatalog, ctx.projects)
  const labels: Record<string, string> = Object.fromEntries(itemLbl.map((l) => [l.key, l.short]))
  const { varying, constant } = useMemo(() => varyingKeys(selected), [selected])
  const condKeys = onlyDiff ? varying : [...varying, ...Object.keys(constant)]
  const trans = (viewsQ.data ?? []).map((v) => transfers(v))
  const transKeys = [...new Set(trans.flatMap((t) => [...t.keys()]))].sort()
  const shownTrans = transKeys.filter((k) => !onlyDiff || new Set(trans.map((t) => t.get(k) ?? MISSING)).size > 1)
  const evidence = (evQ.data ?? []).map((items) => pickEvidence(items))
  const models: (PipelineModel | null)[] = useMemo(() => (viewsQ.data ?? []).map((v, i) => (v ? buildModel(v, scnDef(cItems[i].scenario), detailsQ.data?.[i]) : null)), [viewsQ.data, scnQ.data, detailsQ.data]) // eslint-disable-line react-hooks/exhaustive-deps
  const ipMaps = (viewsQ.data ?? []).map((v) => nodeIps(v))
  const sizeMaps = (detailsQ.data ?? []).map((d) => nodeSizes(d))
  const cadences = useMemo(() => (evQ.data ?? []).map((items, i) => {
    const t = pickTrace(items)
    if (!t) return null
    const tl = buildTimeline(t.timeline_events ?? [], { maxFrames: 64 })
    const fps = models[i]?.fps ?? null
    return { trace: t, fps, ...analyse(tl, viewsQ.data?.[i], fps) }
  }), [evQ.data, models, viewsQ.data])
  /** KPI source per item: evidence KPI, else an on-demand (not persisted) simulation result. */
  const kpiOf = (i: number): { kpi: Dict | null | undefined; source: string | null } => {
    const e = kpiMode === 'evidence' ? evidence[i] : undefined
    if (e) return { kpi: e.kpi, source: evidenceSource(e) }
    const st = sims[ids[i]]
    return st?.status === 'done' ? { kpi: st.res.kpi, source: '재계산 (즉석)' } : { kpi: undefined, source: null }
  }
  const runSim = async (targets: number[]) => {
    for (const i of targets) {
      const it = cItems[i]
      const cat = catOf(it.scenario)
      setSims((m) => ({ ...m, [ids[i]]: { status: 'running' } }))
      try {
        const cfg = cat ? pickProfile((await api.simConfigs(cat.project_id)).items, undefined) : null
        const res = await api.simulate({
          scenario_id: it.scenario, variant_id: it.variant, config_profile_ref: cfg ?? null,
          execution_context: { silicon_rev: 'EVT1', sw_baseline_ref: cat?.default_sw_profile_ref ?? 'sw-vendor-v1.2.3', thermal: 'nominal', method: 'calculation' },
        })
        setSims((m) => ({ ...m, [ids[i]]: { status: 'done', res } }))
      } catch (e) {
        setSims((m) => ({ ...m, [ids[i]]: { status: 'error', error: e instanceof Error ? e.message : String(e) } }))
      }
    }
  }
  /** power_breakdown per item: same-model simulation first (Simulation 통일), else stored simulation evidence. */
  const powerOf = (i: number): { pb: Dict | null; source: string | null } => {
    const st = sims[ids[i]]
    const simPb = st?.status === 'done' ? st.res.result?.power_breakdown ?? null : null
    const stored = (evQ.data?.[i] ?? []).find((e) => e.kind === 'evidence.simulation' && e.power_breakdown)
    if (kpiMode === 'sim' && simPb) return { pb: simPb, source: '재계산 (즉석)' }
    if (stored?.power_breakdown) return { pb: stored.power_breakdown, source: 'Sim evidence (저장)' }
    return simPb ? { pb: simPb, source: '재계산 (즉석)' } : { pb: null, source: null }
  }
  const powerRows: PowerRow[] = ids.map((id, i) => {
    const { pb, source } = powerOf(i)
    return { id, label: labels[id] ?? id, parts: powerModelParts(pb), sub: [source, mifSummary(pb), cpuSource(pb)].filter(Boolean).join(' · ') || null }
  }).filter((r) => r.parts.length > 0)
  const noKpi = ids.map((_, i) => i).filter((i) => evQ.data && (kpiMode === 'sim' || !evidence[i]) && sims[ids[i]]?.status !== 'done' && sims[ids[i]]?.status !== 'running')
  const mixed = kpiMode === 'evidence' && new Set(ids.map((_, i) => kpiOf(i).source).filter(Boolean)).size > 1
  const stream = (i: number, id: string): CadenceResult | undefined => cadences[i]?.results.find((r) => r.stream.id === id)

  // ---------------- items (rows of the transposed table)
  const items: Item[] = []
  const add = (section: string, id: string, label: ReactNode, sortLabel: string, values: (string | null)[], diffMode: 'ref' | 'set' | 'none' = 'ref', nums?: (number | null)[]) => {
    const cls = values.map((v, i) => {
      if (diffMode === 'none' || i === 0) return v === null || v === MISSING ? 'dim' : ''
      const r = values[0]
      if (diffMode === 'set') return v && !r ? 'add' : !v && r ? 'del' : v !== r ? 'chg' : ''
      return v !== r ? 'chg' : v === MISSING ? 'dim' : ''
    })
    items.push({ id: `${section}:${id}`, section, label, sortLabel, values, nums: nums ?? values.map(num), cls })
  }
  add('cond', 'load', 'Load', 'Load', selected.map((r) => r.severity ?? null), 'ref', selected.map((r) => (r.severity ? SEVERITY_RANK[r.severity] ?? null : null)))
  condKeys.forEach((k) => add('cond', k, k, k, selected.map((r) => valueText(r.design_conditions[k]))))
  add('perf', 'dma', 'DMA traffic W+R (MB/s)', 'DMA', models.map((m) => (m ? m.totalMBs.toFixed(0) : null)), 'ref')
  for (const [sid, label] of [['preview', 'Preview buffer'], ['video', 'Video buffer']] as const) {
    add('perf', `${sid}-fps`, `${label} fps (achieved / target)`, `${label} fps`, ids.map((_, i) => { const r = stream(i, sid); return r?.fpsAchieved ? `${r.fpsAchieved.toFixed(2)} / ${cadences[i]?.fps ?? '?'}` : null }), 'none')
    add('perf', `${sid}-int`, `${label} interval max (ms)`, `${label} interval`, ids.map((_, i) => { const b = stream(i, sid)?.box; return b ? b.max.toFixed(2) : null }), 'none')
    add('perf', `${sid}-lat`, `${label} latency mean (ms)`, `${label} latency`, ids.map((_, i) => { const b = stream(i, sid)?.latBox; return b ? b.mean.toFixed(1) : null }), 'none')
  }
  add('perf', 'trace', 'timing source', 'timing source', cadences.map((c) => (c ? `${evidenceSource(c.trace)} · ${new Set((c.trace.timeline_events ?? []).map((x) => x.frame_index)).size}f` : null)), 'none')
  const nodeKeys = (maps: Map<string, string>[]) => [...new Set(maps.flatMap((m) => [...m.keys()]))].sort()
  nodeKeys(ipMaps).filter((k) => !onlyDiff || new Set(ipMaps.map((m) => m.get(k) ?? MISSING)).size > 1)
    .forEach((k) => add('hw', `ip:${k}`, <span className="mono">{k}</span>, k, ipMaps.map((m) => m.get(k) ?? null), 'set'))
  nodeKeys(sizeMaps).filter((k) => !onlyDiff || new Set(sizeMaps.map((m) => m.get(k) ?? MISSING)).size > 1)
    .forEach((k) => add('size', `sz:${k}`, <span className="mono">{k}</span>, k, sizeMaps.map((m) => m.get(k) ?? null), 'ref', sizeMaps.map((m) => pixels(m.get(k)))))
  shownTrans.forEach((k) => add('dma', k, <span className="mono" style={{ fontSize: 12 }}>{k}</span>, k, trans.map((t) => t.get(k) ?? null), 'set'))
  add('kpi', 'src', 'KPI 출처', 'KPI 출처', ids.map((_, i) => kpiOf(i).source), 'none')
  const kpiRows = KPI_FIELDS.map(([label, field, unit]) => ({ label, unit, field, values: ids.map((_, i) => kpiNumber(kpiOf(i).kpi?.[field])) })).filter((r) => r.values.some((v) => v !== null))
  kpiRows.forEach((r) => add('kpi', r.field, `${r.label} (${r.unit})`, r.label, r.values.map((v, i) => {
    if (v === null) return null
    const b = r.values[0]
    return i > 0 && b ? `${v.toFixed(1)} (${v >= b ? '+' : ''}${(((v - b) / b) * 100).toFixed(1)}%)` : v.toFixed(1)
  }), 'none', r.values))

  const SECTIONS: [string, string][] = [['cond', '조건 · 기준과 다른 값 강조'], ['hw', 'HW 구성 · node → IP (과제 태그 제외)'], ['size', '처리 크기 · node sim size'], ['perf', 'Timing · DMA 요약 (trace / 모델 계산)'], ['dma', 'DMA 전송 · 파랑 = 기준에 없음, 빨강 = 기준에만 있음'], ['kpi', 'KPI · 값 (기준 대비 Δ%) · evidence 출처']]
  const groups: RowGroup<Item>[] = SECTIONS.map(([s, title]) => ({ id: s, header: <span className="sec-h">{title}</span>, rows: items.filter((it) => it.section === s), className: 'sec-row' }))
    .filter((g) => g.rows.length)
  const itemCols: Column<Item>[] = [
    { key: 'item', label: '항목', width: 280, sticky: true, sort: (it) => it.sortLabel, title: (it) => it.sortLabel, render: (it) => <span className="muted">{it.label}</span> },
    ...ids.map((id, i): Column<Item> => ({
      key: `v:${id}`, label: <span className="mono" title={itemLbl[i]?.full}>{labels[id]}{i === 0 ? ' ★' : ''}</span>, width: 170, headClass: i === 0 ? 'ref-col' : '',
      sort: (it): SortValue => it.nums[i] ?? it.values[i], title: (it) => it.values[i] ?? '', cellClass: (it) => `mono ${it.cls[i]}`,
      render: (it) => it.values[i] ?? <span className="dim">—</span>,
    })),
  ]

  // ---------------- variant rows (non-transposed)
  interface VRow { id: string; i: number }
  const vrows: VRow[] = ids.map((id, i) => ({ id, i }))
  const perKeys = items.filter((it) => it.section !== 'dma')
  const varCols: Column<VRow>[] = [
    { key: 'variant', label: 'Variant', width: 250, sticky: true, sort: (r) => r.id, render: (r) => <span className="mono" title={itemLbl[r.i]?.full}>{labels[r.id]}{r.i === 0 ? ' ★' : ''}</span> },
    ...perKeys.map((it): Column<VRow> => ({ key: it.id, label: it.sortLabel, width: 130, headTitle: it.sortLabel, sort: (r) => it.nums[r.i] ?? it.values[r.i],
      title: (r) => it.values[r.i] ?? '', cellClass: (r) => `mono ${it.cls[r.i]}`, render: (r) => it.values[r.i] ?? <span className="dim">—</span> })),
  ]

  // ---------------- plots
  const color = (i: number) => SERIES[i % SERIES.length]
  const dmaStack = ids.map((id, i) => {
    const m = models[i]
    const t = m ? [...trafficByIp(m).entries()].sort((a, b) => b[1] - a[1]) : []
    return { id, label: labels[id], parts: t.map(([key, value]) => ({ key, value })) }
  })
  const cadRows = ids.flatMap((id, i) => (['preview', 'video'] as const).map((sid) => {
    const r = stream(i, sid)
    const p = cadences[i]?.period
    const norm = r && p ? r.intervals.map((x) => (x / p) * 100) : []
    const box = norm.length ? (() => { const v = [...norm].sort((a, b) => a - b); const q = (x: number) => v[Math.min(v.length - 1, Math.max(0, Math.round((v.length - 1) * x)))]; const mean = v.reduce((s, x) => s + x, 0) / v.length
      return { n: v.length, min: v[0], q1: q(0.25), median: q(0.5), q3: q(0.75), max: v[v.length - 1], mean, std: Math.sqrt(v.reduce((s, x) => s + (x - mean) ** 2, 0) / v.length), p95: q(0.95) } })() : null
    return { id: `${id}:${sid}`, label: <span><span className="mono">{labels[id]}</span> · {sid}</span>, box, values: norm, color: color(i) }
  })).filter((r) => r.box)
  const latRows = ids.map((id, i) => { const r = stream(i, 'preview') ?? stream(i, 'display'); return { id, label: <span className="mono">{labels[id]}</span>, box: r?.latBox ?? null, values: r?.latencies ?? [], color: color(i) } }).filter((r) => r.box)

  const pmTarget = (evQ.data ?? []).map((items, i) => ({ i, sim: items.find((e) => e.kind === 'evidence.simulation' && e.kpi), meas: items.find((e) => e.kind === 'evidence.measurement' && e.kpi && e.vdd_power) })).find((x) => x.sim && x.meas)
  const pmQ = useAsync(() => (pmTarget ? api.predMeas(pmTarget.sim!.id, pmTarget.meas!.id) : Promise.resolve(null)), [pmTarget?.sim?.id, pmTarget?.meas?.id])

  const setItems = (next: CompareItem[]) => ctx.navigate(undefined, { items: formatItems(next), variants: undefined })
  const remove = (i: number) => setItems(cItems.filter((_, n) => n !== i))
  const makeRef = (i: number) => setItems([cItems[i], ...cItems.filter((_, n) => n !== i)])
  const condDiff = selected.map((r) => varying.filter((k) => valueText(r.design_conditions[k]) !== valueText(selected[0]?.design_conditions[k])).length)
  const found: Insight[] = insights({
    n: ids.length, kpi: kpiRows, dma: models.map((m) => (m ? m.totalMBs : null)),
    traffic: models.map((m) => (m ? trafficByIp(m) : null)), changedConditions: condDiff, ipMaps, sizeMaps,
  })
  const sign = (x: number) => `${x >= 0 ? '+' : ''}${x.toFixed(1)}`
  // ---- decision summary: Power / BW / Latency vs ★
  const kv = (field: string) => kpiRows.find((r) => r.field === field)?.values ?? ids.map(() => null)
  const fam = (i: number, f: 'cpu' | 'ip' | 'mem'): number | null => {
    const r = powerRows.find((x) => x.id === ids[i])
    return r ? r.parts.filter((p) => p.family === f).reduce((a, p) => a + p.mw, 0) : null
  }
  const lat = (sid: 'preview' | 'video') => ids.map((_, i) => stream(i, sid)?.latBox?.mean ?? null)
  const metrics: MetricRow[] = [
    { group: 'Power', key: 'total_power_mw', label: 'Total power', unit: 'mW', values: kv('total_power_mw'), hint: 'KPI (evidence 또는 즉석 simulation)' },
    { group: 'Power', key: 'fam_cpu', label: '구성 · CPU (SW)', unit: 'mW', values: ids.map((_, i) => fam(i, 'cpu')), hint: 'power_breakdown: CPU cluster 합' },
    { group: 'Power', key: 'fam_ip', label: '구성 · IP core', unit: 'mW', values: ids.map((_, i) => fam(i, 'ip')), hint: 'power_breakdown: IP 동작 + leakage + clock' },
    { group: 'Power', key: 'fam_mem', label: '구성 · 메모리 (BW)', unit: 'mW', values: ids.map((_, i) => fam(i, 'mem')), hint: 'power_breakdown: traffic + MIF base' },
    // KPI core/BW power only when the power breakdown is missing (same quantity otherwise)
    ...(powerRows.length ? [] : [
      { group: 'Power' as const, key: 'core_power_mw', label: 'Core power', unit: 'mW', values: kv('core_power_mw') },
      { group: 'Power' as const, key: 'bw_power_mw', label: 'BW power', unit: 'mW', values: kv('bw_power_mw') }]),
    { group: 'BW', key: 'total_bw_mbs', label: 'Total BW', unit: 'MB/s', digits: 0, values: kv('total_bw_mbs'), hint: 'KPI · DMA W+R' },
    { group: 'BW', key: 'dma', label: 'DMA 모델 합계', unit: 'MB/s', digits: 0, values: models.map((m) => (m ? m.totalMBs : null)), hint: 'pipeline view memory × fps (stat/size 미정 제외)' },
    { group: 'Latency · Timing', key: 'preview_lat', label: 'Sensor → Preview 지연 (평균)', unit: 'ms', values: lat('preview'), hint: 'timeline evidence (trace / simulation)' },
    { group: 'Latency · Timing', key: 'video_lat', label: 'Sensor → Video 지연 (평균)', unit: 'ms', values: lat('video') },
    { group: 'Latency · Timing', key: 'frame_latency_ms', label: 'Frame latency (KPI)', unit: 'ms', values: kv('frame_latency_ms') },
    { group: 'Latency · Timing', key: 'hw_time_max_ms', label: 'HW time max', unit: 'ms', values: kv('hw_time_max_ms') },
    { group: 'Latency · Timing', key: 'fps_effective', label: 'Effective fps', unit: 'fps', digits: 2, values: kv('fps_effective'), lowerIsBetter: false, tolerancePct: 0.5 },
  ]
  const summaryItems: ItemInfo[] = ids.map((id, i) => {
    const f = found.find((x) => x.index === i)
    const drivers: string[] = []
    const pr0 = powerRows.find((x) => x.id === ids[0]), pri = powerRows.find((x) => x.id === id)
    if (i > 0 && pr0 && pri) {
      const keys = [...new Set([...pr0.parts, ...pri.parts].map((p) => p.key))]
      keys.map((k) => ({ k, label: (pri.parts.find((p) => p.key === k) ?? pr0.parts.find((p) => p.key === k))!.label, d: (pri.parts.find((p) => p.key === k)?.mw ?? 0) - (pr0.parts.find((p) => p.key === k)?.mw ?? 0) }))
        .filter((x) => Math.abs(x.d) >= 1).sort((a, b) => Math.abs(b.d) - Math.abs(a.d)).slice(0, 3)
        .forEach((x) => drivers.push(`${x.label} ${sign(x.d)} mW`))
    }
    if (f?.topIp.length) drivers.push(`DMA ${f.topIp.slice(0, 3).map((t) => `${t.ip} ${sign(t.delta)}`).join(', ')} MB/s`)
    const st = sims[id]
    return { label: labels[id] ?? id, full: itemLbl[i]?.full, color: color(i), source: kpiOf(i).source, changed: f?.changed, drivers,
      status: st?.status === 'running' ? <div className="faint">예측 계산 중…</div> : st?.status === 'error' ? <div className="err" style={{ margin: 0 }}>{st.error}</div> : undefined }
  })
  const analysis = ids.length > 1 && (
    <section className="panel fit" style={{ padding: 10 }}>
      <div className="panel-head" style={{ padding: '0 0 8px' }}><h2>분석 요약 · 기준(★) 대비 Power · BW · Latency</h2>
        <span className="muted" style={{ fontSize: 12 }}>★ {itemLbl[0]?.full}</span><span className="grow" />
        <div className="seg sm" role="group" aria-label="KPI 출처">
          <button className={kpiMode === 'evidence' ? 'on' : ''} onClick={() => setKpiMode('evidence')} title="실측/등록 evidence 우선, 없으면 즉석 예측">Evidence 우선</button>
          <button className={kpiMode === 'sim' ? 'on' : ''} onClick={() => setKpiMode('sim')} title="모든 항목을 같은 simulation 모델로 계산 (공정 비교)">Simulation 통일</button>
        </div>
        {noKpi.length > 0 && <button className="btn primary" onClick={() => runSim(noKpi)} title="simulation으로 KPI 계산 (DB에 저장하지 않음)">{kpiMode === 'sim' ? `${noKpi.length}개 예측 실행` : `KPI 없는 ${noKpi.length}개 예측 실행`}</button>}
      </div>
      {mixed && <div className="faint" style={{ fontSize: 12, margin: '0 0 8px' }}>⚠ KPI 출처가 섞여 있습니다 (실측 vs 계산). 설계 대안 비교는 “Simulation 통일”을 권장합니다.</div>}
      <CompareSummary items={summaryItems} metrics={metrics} />
    </section>
  )

  const table = (
    // full height: every row visible, the page (pl-main) is the only vertical scroller
    <div className="panel table-x fit cmp-table">
      {orient === 'items'
        ? <DataTable id={`compare.items.${ids.length}`} columns={itemCols} groups={groups} rowKey={(it) => it.id} />
        : <DataTable id="compare.variants" columns={varCols} rows={vrows} rowKey={(r) => r.id} rowClass={(r) => (r.i === 0 ? 'sel' : '')} />}
      {viewsQ.loading && <div className="empty">view 불러오는 중…</div>}
    </div>
  )
  const plots = (
    <div className="plot-grid">
      <section className="panel plot-card"><h3>KPI · 기준(점선) 대비 <span className="faint">evidence KPI · 없으면 즉석 예측</span></h3>
        {kpiRows.length ? kpiRows.map((r) => (
          <div key={r.field} className="kpi-mini"><div className="faint" style={{ fontSize: 11.5 }}>{r.label} ({r.unit})</div>
            <Bars unit={r.unit} base={r.values[0]} labelW={150} title={r.label} lowerIsBetter={r.field !== 'fps_effective'} data={ids.map((id, i) => {
              const v = r.values[i], b = r.values[0]
              return { id, label: labels[id], value: v, color: color(i), note: i > 0 && v !== null && b ? `(${v >= b ? '+' : ''}${(((v - b) / b) * 100).toFixed(1)}%)` : undefined }
            })} /></div>)) : <div className="empty">KPI evidence 없음 — 분석 요약의 “예측 실행”으로 계산</div>}
      </section>
      <section className="panel plot-card pm-card"><h3>전력 구성 · 어디서 달라지나 <span className="faint">CPU(cluster) · IP(동작/leakage/clock 초과) · 메모리(traffic/MIF base) · ★ 기준 대비</span></h3>
        {powerRows.length ? <>
          <PowerStack rows={powerRows} />
          {powerRows.length > 1 && <details open style={{ marginTop: 6 }}><summary className="faint" style={{ fontSize: 12 }}>구성별 값 · 기준 대비 Δ</summary><PowerDeltaTable rows={powerRows} /></details>}
        </> : <div className="empty">예측 evidence 없음 — 분석 요약의 “예측 실행”으로 계산하면 구성이 표시됩니다</div>}
      </section>
      <section className="panel plot-card"><h3>DMA traffic by IP (W+R MB/s) <span className="faint">view memory × fps · stat/size 미정 제외</span></h3>
        <StackedBars unit="MB/s" rows={dmaStack} labelW={150} /></section>
      <section className="panel plot-card"><h3>출력 buffer 간격 / target period (%) <span className="faint">100% = fps 충족 · 분포 폭 = jitter</span></h3>
        {cadRows.length ? <BoxPlot rows={cadRows} unit="%" target={100} targetLabel="100% (target)" labelW={170} /> : <div className="empty">timeline evidence 없음</div>}</section>
      <section className="panel plot-card"><h3>Sensor → Preview 지연 (ms)</h3>
        {latRows.length ? <BoxPlot rows={latRows} labelW={170} /> : <div className="empty">timeline evidence 없음</div>}</section>
    </div>
  )

  return (
    <PageLayout id="compare" top={
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span className="muted" style={{ fontSize: 13 }}>비교 대상</span>
        {ids.map((id, i) => (
          <span key={id} className="mono" title={itemLbl[i]?.full} style={{ fontSize: 12, padding: '5px 8px', borderRadius: 6, display: 'inline-flex', gap: 6, alignItems: 'center',
            background: i === 0 ? 'var(--primary)' : '#fff', color: i === 0 ? '#fff' : 'var(--text)', border: i === 0 ? 0 : '1px solid var(--line)', borderLeft: `4px solid ${color(i)}` }}>
            {labels[id]}{i === 0 ? ' · 기준' : <>
              <button className="btn" style={{ padding: '0 5px', fontSize: 11 }} onClick={() => makeRef(i)} title="기준으로">★</button>
              <button className="btn" style={{ padding: '0 5px', fontSize: 11 }} onClick={() => remove(i)} aria-label={`${labels[id]} 제거`}>×</button></>}
          </span>
        ))}
        <button className="btn" onClick={() => ctx.openPicker('compare')} title="과제 · scenario · variant 선택 (여러 과제/scenario 혼합 가능)">+ 항목 추가 (Ctrl K)</button>
        <span className="grow" />
        <div className="seg sm" role="group" aria-label="표시">
          {([['both', 'Plot + 표'], ['table', '표'], ['plot', 'Plot']] as const).map(([k, l]) => <button key={k} className={show === k ? 'on' : ''} onClick={() => setShow(k)}>{l}</button>)}
        </div>
        <div className="seg sm" role="group" aria-label="표 방향">
          <button className={orient === 'items' ? 'on' : ''} onClick={() => setOrient('items')} title="행 = 항목, 열 = variant">항목 × Variant</button>
          <button className={orient === 'variants' ? 'on' : ''} onClick={() => setOrient('variants')} title="행 = variant, 열 = 항목 (열 정렬로 순위 비교)">Variant × 항목</button>
        </div>
        <label className="muted" style={{ fontSize: 13, display: 'flex', gap: 6 }}><input type="checkbox" checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)} />다른 행만</label>
      </div>} main={<>
      {ids.length < 2 && <div className="empty panel fit">비교하려면 2개 이상 추가하세요. 과제 · scenario가 달라도 됩니다 — Ctrl K에서 과제/scenario를 바꾼 뒤 Shift+Enter, 또는 Scenario Matrix에서 여러 행 선택.</div>}
      {variantsQ.error && <div className="err">{variantsQ.error}</div>}
      {missing.length > 0 && <div className="err">DB에 없는 항목: {missing.join(', ')}</div>}
      {analysis}
      {[viewsQ.error, detailsQ.error, evQ.error].filter(Boolean).map((error, i) => <div className="err" key={i}>{error}</div>)}
      {show !== 'table' && plots}
      {show !== 'plot' && table}
      </>}
      bottomTabs={pmTarget ? [{ id: 'pm', label: <>예측 vs 실측 <span className="tab-note">{labels[ids[pmTarget.i]]}</span></>, content: <>
        <div className="panel-head"><h2>예측 vs 실측 · {itemLbl[pmTarget.i]?.full}</h2>
          <span className={`badge src-${evidenceSource(pmTarget.meas!)}`}>{evidenceSource(pmTarget.meas!)}</span>
          <span className="muted" style={{ fontSize: 12 }}>{pmTarget.sim!.id} ↔ {pmTarget.meas!.id}</span></div>
        {pmQ.error && <div className="err">{pmQ.error}</div>}
        {pmQ.data && <div className="table-scroll">
          <table className="grid"><thead><tr><th>metric</th><th>scope</th><th>unit</th><th style={{ textAlign: 'right' }}>예측</th><th style={{ textAlign: 'right' }}>실측</th><th style={{ textAlign: 'right' }}>Δ%</th><th>status</th></tr></thead>
            <tbody>{(pmQ.data.rows as Dict[]).filter((r) => String(r.metric_id).startsWith('power.domain') || String(r.metric_id).includes('total') || r.status === 'MATCHED').slice(0, 40).map((r, i) => (
              <tr key={i}><td className="mono">{String(r.metric_id)}</td><td>{String(r.scope_ref ?? '')}</td><td>{String(r.unit ?? '')}</td>
                <td className="mono" style={{ textAlign: 'right' }}>{typeof r.prediction === 'number' ? r.prediction.toFixed(1) : '—'}</td>
                <td className="mono" style={{ textAlign: 'right' }}>{typeof r.measurement === 'number' ? r.measurement.toFixed(1) : '—'}</td>
                <td className="mono" style={{ textAlign: 'right' }}>{typeof r.delta_pct === 'number' ? r.delta_pct.toFixed(1) : '—'}</td>
                <td className="faint">{String(r.status)}</td></tr>))}</tbody></table>
        </div>}
      </> }] : undefined} />
  )
}
