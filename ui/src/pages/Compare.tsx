import { useMemo, useState, type ReactNode } from 'react'
import type { Ctx } from '../App'
import { api, type Dict, type Evidence, type VariantRow, type ViewResponse } from '../lib/api'
import { useAsync } from '../lib/route'
import { MISSING, evidenceSource, shortLabels, valueText, varyingKeys } from '../lib/conditions'
import { memoryText } from '../lib/graph'
import { buildModel, trafficByIp, type PipelineModel } from '../lib/model'
import { buildTimeline } from '../lib/timeline'
import { analyse, type CadenceResult } from '../lib/cadence'
import { SEVERITY_RANK } from '../lib/defaults'
import { toRows } from '../components/Picker'
import { PageLayout, usePref } from '../components/Layout'
import { DataTable, type Column, type RowGroup, type SortValue } from '../components/DataTable'
import { Bars, BoxPlot, SERIES, StackedBars } from '../components/Charts'

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

export function ComparePage({ ctx }: { ctx: Ctx }) {
  const ids = [...new Set((ctx.params.variants ?? ctx.variant).split(',').filter(Boolean))]
  const scenarioItem = ctx.catalog.find((c) => c.scenario_id === ctx.scenario)
  const variantsQ = useAsync(() => api.variants(ctx.scenario), [ctx.scenario])
  const scnQ = useAsync(() => api.scenario(ctx.scenario).catch(() => null), [ctx.scenario])
  const key = ids.join(',')
  const viewsQ = useAsync(() => Promise.all(ids.map((v) => api.view(ctx.scenario, v, 1))), [ctx.scenario, key])
  const detailsQ = useAsync(() => Promise.all(ids.map((v) => api.variant(ctx.scenario, v))), [ctx.scenario, key])
  const evQ = useAsync(() => Promise.all(ids.map((v) => api.evidenceList(ctx.scenario, v, ctx.project).then((r) => r.items))), [ctx.scenario, key, ctx.project])
  const [onlyDiff, setOnlyDiff] = useState(true)
  const [orient, setOrient] = usePref<'items' | 'variants'>('compare.orient', 'items')
  const [show, setShow] = usePref<'both' | 'table' | 'plot'>('compare.show', 'both')

  const rows = useMemo(() => toRows(scenarioItem, variantsQ.data?.items ?? []), [scenarioItem, variantsQ.data])
  const selected = ids.map((id): VariantRow => rows.find((r) => r.variant_id === id) ?? { project_id: ctx.project, scenario_id: ctx.scenario, variant_id: id, design_conditions: {} })
  const missing = variantsQ.data ? ids.filter((id) => !rows.some((r) => r.variant_id === id)) : []
  const labels = shortLabels(ids)
  const { varying, constant } = useMemo(() => varyingKeys(selected), [selected])
  const condKeys = onlyDiff ? varying : [...varying, ...Object.keys(constant)]
  const trans = (viewsQ.data ?? []).map((v) => transfers(v))
  const transKeys = [...new Set(trans.flatMap((t) => [...t.keys()]))].sort()
  const shownTrans = transKeys.filter((k) => !onlyDiff || new Set(trans.map((t) => t.get(k) ?? MISSING)).size > 1)
  const evidence = (evQ.data ?? []).map((items) => pickEvidence(items))
  const models: (PipelineModel | null)[] = useMemo(() => (viewsQ.data ?? []).map((v, i) => (v ? buildModel(v, scnQ.data, detailsQ.data?.[i]) : null)), [viewsQ.data, scnQ.data, detailsQ.data])
  const cadences = useMemo(() => (evQ.data ?? []).map((items, i) => {
    const t = pickTrace(items)
    if (!t) return null
    const tl = buildTimeline(t.timeline_events ?? [], { maxFrames: 64 })
    const fps = models[i]?.fps ?? null
    return { trace: t, fps, ...analyse(tl, viewsQ.data?.[i], fps) }
  }), [evQ.data, models, viewsQ.data])
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
  shownTrans.forEach((k) => add('dma', k, <span className="mono" style={{ fontSize: 12 }}>{k}</span>, k, trans.map((t) => t.get(k) ?? null), 'set'))
  add('kpi', 'src', 'evidence 출처', 'evidence', evidence.map((e) => (e ? evidenceSource(e) : null)), 'none')
  const kpiRows = KPI_FIELDS.map(([label, field, unit]) => ({ label, unit, field, values: evidence.map((e) => kpiNumber(e?.kpi?.[field])) })).filter((r) => r.values.some((v) => v !== null))
  kpiRows.forEach((r) => add('kpi', r.field, `${r.label} (${r.unit})`, r.label, r.values.map((v, i) => {
    if (v === null) return null
    const b = r.values[0]
    return i > 0 && b ? `${v.toFixed(1)} (${v >= b ? '+' : ''}${(((v - b) / b) * 100).toFixed(1)}%)` : v.toFixed(1)
  }), 'none', r.values))

  const SECTIONS: [string, string][] = [['cond', '조건 · 기준과 다른 값 강조'], ['perf', 'Timing · DMA 요약 (trace / 모델 계산)'], ['dma', 'DMA 전송 · 파랑 = 기준에 없음, 빨강 = 기준에만 있음'], ['kpi', 'KPI · 값 (기준 대비 Δ%) · evidence 출처']]
  const groups: RowGroup<Item>[] = SECTIONS.map(([s, title]) => ({ id: s, header: <span className="sec-h">{title}</span>, rows: items.filter((it) => it.section === s), className: 'sec-row' }))
    .filter((g) => g.rows.length)
  const itemCols: Column<Item>[] = [
    { key: 'item', label: '항목', width: 280, sticky: true, sort: (it) => it.sortLabel, title: (it) => it.sortLabel, render: (it) => <span className="muted">{it.label}</span> },
    ...ids.map((id, i): Column<Item> => ({
      key: `v:${id}`, label: <span className="mono" title={id}>{labels[id]}{i === 0 ? ' ★' : ''}</span>, width: 170, headClass: i === 0 ? 'ref-col' : '',
      sort: (it): SortValue => it.nums[i] ?? it.values[i], title: (it) => it.values[i] ?? '', cellClass: (it) => `mono ${it.cls[i]}`,
      render: (it) => it.values[i] ?? <span className="dim">—</span>,
    })),
  ]

  // ---------------- variant rows (non-transposed)
  interface VRow { id: string; i: number }
  const vrows: VRow[] = ids.map((id, i) => ({ id, i }))
  const perKeys = items.filter((it) => it.section !== 'dma')
  const varCols: Column<VRow>[] = [
    { key: 'variant', label: 'Variant', width: 250, sticky: true, sort: (r) => r.id, render: (r) => <span className="mono">{r.id}{r.i === 0 ? ' ★' : ''}</span> },
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

  const remove = (id: string) => ctx.navigate(undefined, { variants: ids.filter((x) => x !== id).join(',') })
  const makeRef = (id: string) => ctx.navigate(undefined, { variants: [id, ...ids.filter((x) => x !== id)].join(',') })

  const table = (
    <div className="panel table-scroll" style={show === 'table' ? { flex: '1 1 auto', minHeight: 160 } : { flex: '0 0 auto', maxHeight: '56vh', minHeight: 200 }}>
      {orient === 'items'
        ? <DataTable id={`compare.items.${ids.length}`} columns={itemCols} groups={groups} rowKey={(it) => it.id} />
        : <DataTable id="compare.variants" columns={varCols} rows={vrows} rowKey={(r) => r.id} rowClass={(r) => (r.i === 0 ? 'sel' : '')} />}
      {viewsQ.loading && <div className="empty">view 불러오는 중…</div>}
    </div>
  )
  const plots = (
    <div className="plot-grid">
      <section className="panel plot-card"><h3>KPI · 기준(점선) 대비 <span className="faint">evidence KPI</span></h3>
        {kpiRows.length ? kpiRows.map((r) => (
          <div key={r.field} className="kpi-mini"><div className="faint" style={{ fontSize: 11.5 }}>{r.label} ({r.unit})</div>
            <Bars unit={r.unit} base={r.values[0]} labelW={150} data={ids.map((id, i) => {
              const v = r.values[i], b = r.values[0]
              return { id, label: labels[id], value: v, color: color(i), note: i > 0 && v !== null && b ? `(${v >= b ? '+' : ''}${(((v - b) / b) * 100).toFixed(1)}%)` : undefined }
            })} /></div>)) : <div className="empty">KPI evidence 없음</div>}
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
          <span key={id} className="mono" style={{ fontSize: 12, padding: '5px 8px', borderRadius: 6, display: 'inline-flex', gap: 6, alignItems: 'center',
            background: i === 0 ? 'var(--primary)' : '#fff', color: i === 0 ? '#fff' : 'var(--text)', border: i === 0 ? 0 : '1px solid var(--line)', borderLeft: `4px solid ${color(i)}` }}>
            {id}{i === 0 ? ' · 기준' : <>
              <button className="btn" style={{ padding: '0 5px', fontSize: 11 }} onClick={() => makeRef(id)} title="기준으로">★</button>
              <button className="btn" style={{ padding: '0 5px', fontSize: 11 }} onClick={() => remove(id)} aria-label={`${id} 제거`}>×</button></>}
          </span>
        ))}
        <button className="btn" onClick={() => ctx.openPicker('compare')}>+ variant 추가 (Ctrl K)</button>
        <span className="grow" />
        <div className="seg sm" role="group" aria-label="표시">
          {([['both', '표 + Plot'], ['table', '표'], ['plot', 'Plot']] as const).map(([k, l]) => <button key={k} className={show === k ? 'on' : ''} onClick={() => setShow(k)}>{l}</button>)}
        </div>
        <div className="seg sm" role="group" aria-label="표 방향">
          <button className={orient === 'items' ? 'on' : ''} onClick={() => setOrient('items')} title="행 = 항목, 열 = variant">항목 × Variant</button>
          <button className={orient === 'variants' ? 'on' : ''} onClick={() => setOrient('variants')} title="행 = variant, 열 = 항목 (열 정렬로 순위 비교)">Variant × 항목</button>
        </div>
        <label className="muted" style={{ fontSize: 13, display: 'flex', gap: 6 }}><input type="checkbox" checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)} />다른 행만</label>
      </div>} main={<>
      {ids.length < 2 && <div className="empty panel fit">비교하려면 variant를 2개 이상 추가하세요. DB Explorer에서 행을 선택하거나 Ctrl K → Shift+Enter로 추가할 수 있습니다.</div>}
      {variantsQ.error && <div className="err">{variantsQ.error}</div>}
      {missing.length > 0 && <div className="err">이 scenario에 없는 variant: {missing.join(', ')}</div>}
      {[viewsQ.error, detailsQ.error, evQ.error].filter(Boolean).map((error, i) => <div className="err" key={i}>{error}</div>)}
      {show !== 'plot' && table}
      {show !== 'table' && plots}
      </>}
      bottomTabs={pmTarget ? [{ id: 'pm', label: <>예측 vs 실측 <span className="tab-note">{ids[pmTarget.i]}</span></>, content: <>
        <div className="panel-head"><h2>예측 vs 실측 · {ids[pmTarget.i]}</h2>
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
