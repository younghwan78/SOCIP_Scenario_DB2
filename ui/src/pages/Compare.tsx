import { useMemo, useState } from 'react'
import type { Ctx } from '../App'
import { api, type Dict, type Evidence, type ViewResponse } from '../lib/api'
import { useAsync } from '../lib/route'
import { MISSING, evidenceSource, shortLabels, valueText, varyingKeys } from '../lib/conditions'
import { memoryText } from '../lib/graph'
import { toRows } from '../components/Picker'
import { PageLayout } from '../components/Layout'

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

export function ComparePage({ ctx }: { ctx: Ctx }) {
  const ids = (ctx.params.variants ?? ctx.variant).split(',').filter(Boolean)
  const scenarioItem = ctx.catalog.find((c) => c.scenario_id === ctx.scenario)
  const variantsQ = useAsync(() => api.variants(ctx.scenario), [ctx.scenario])
  const key = ids.join(',')
  const viewsQ = useAsync(() => Promise.all(ids.map((v) => api.view(ctx.scenario, v, 1).catch(() => undefined))), [ctx.scenario, key])
  const evQ = useAsync(() => Promise.all(ids.map((v) => api.evidenceList(ctx.scenario, v).then((r) => r.items).catch(() => [] as Evidence[]))), [ctx.scenario, key])
  const [onlyDiff, setOnlyDiff] = useState(true)

  const rows = useMemo(() => toRows(scenarioItem, variantsQ.data?.items ?? []), [scenarioItem, variantsQ.data])
  const selected = ids.map((id) => rows.find((r) => r.variant_id === id)).filter((r): r is NonNullable<typeof r> => !!r)
  const labels = shortLabels(ids)
  const { varying, constant } = useMemo(() => varyingKeys(selected), [selected])
  const allKeys = onlyDiff ? varying : [...varying, ...Object.keys(constant)]
  const refDc = selected[0]?.design_conditions ?? {}
  const trans = (viewsQ.data ?? []).map((v) => transfers(v))
  const transKeys = [...new Set(trans.flatMap((t) => [...t.keys()]))].sort()
  const shownTrans = transKeys.filter((k) => !onlyDiff || new Set(trans.map((t) => t.get(k) ?? MISSING)).size > 1)
  const evidence = (evQ.data ?? []).map((items) => pickEvidence(items))
  const kpiRows = KPI_FIELDS.map(([label, field, unit]) => ({ label, unit, values: evidence.map((e) => kpiNumber(e?.kpi?.[field])) })).filter((r) => r.values.some((v) => v !== null))

  const pmTarget = (evQ.data ?? []).map((items, i) => ({ i, sim: items.find((e) => e.kind === 'evidence.simulation' && e.kpi), meas: items.find((e) => e.kind === 'evidence.measurement' && e.kpi && e.vdd_power) })).find((x) => x.sim && x.meas)
  const pmQ = useAsync(() => (pmTarget ? api.predMeas(pmTarget.sim!.id, pmTarget.meas!.id) : Promise.resolve(null)), [pmTarget?.sim?.id, pmTarget?.meas?.id])

  const remove = (id: string) => ctx.navigate(undefined, { variants: ids.filter((x) => x !== id).join(',') })
  const makeRef = (id: string) => ctx.navigate(undefined, { variants: [id, ...ids.filter((x) => x !== id)].join(',') })

  const colCount = ids.length + 1
  return (
    <PageLayout id="compare" top={
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span className="muted" style={{ fontSize: 13 }}>비교 대상</span>
        {ids.map((id, i) => (
          <span key={id} className="mono" style={{ fontSize: 12, padding: '5px 8px', borderRadius: 6, display: 'inline-flex', gap: 6, alignItems: 'center',
            background: i === 0 ? 'var(--primary)' : '#fff', color: i === 0 ? '#fff' : 'var(--text)', border: i === 0 ? 0 : '1px solid var(--line)' }}>
            {id}{i === 0 ? ' · 기준' : <>
              <button className="btn" style={{ padding: '0 5px', fontSize: 11 }} onClick={() => makeRef(id)} title="기준으로">★</button>
              <button className="btn" style={{ padding: '0 5px', fontSize: 11 }} onClick={() => remove(id)} aria-label={`${id} 제거`}>×</button></>}
          </span>
        ))}
        <button className="btn" onClick={() => ctx.openPicker('compare')}>+ variant 추가 (Ctrl K)</button>
        <span className="grow" />
        <label className="muted" style={{ fontSize: 13, display: 'flex', gap: 6 }}><input type="checkbox" checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)} />다른 행만</label>
      </div>} main={<>
      {ids.length < 2 && <div className="empty panel fit">비교하려면 variant를 2개 이상 추가하세요. DB Explorer에서 행을 선택하거나 Ctrl K → Shift+Enter로 추가할 수 있습니다.</div>}
      {variantsQ.error && <div className="err">{variantsQ.error}</div>}
      <div className="panel table-scroll">
        <table className="grid compare-grid">
          <thead><tr><th className="rowhead" style={{ minWidth: 260 }}>항목</th>
            {ids.map((id, i) => <th key={id} className="mono" title={id} style={i === 0 ? { background: 'var(--primary-soft)', color: 'var(--primary-strong)' } : undefined}>{labels[id]}{i === 0 ? ' ★' : ''}</th>)}</tr></thead>
          <tbody>
            <tr><td colSpan={colCount} style={{ fontSize: 12, fontWeight: 700, letterSpacing: '.06em', color: 'var(--muted)', background: '#fff' }}>조건 · 기준과 다른 값 강조</td></tr>
            <tr><td className="rowhead muted">Load</td>{selected.map((r) => <td key={r.variant_id}>{r.severity && <span className={`badge load-${r.severity}`}>{r.severity}</span>}</td>)}</tr>
            {allKeys.map((k) => (
              <tr key={k}><td className="rowhead muted">{k}</td>
                {selected.map((r, i) => { const v = valueText(r.design_conditions[k]); return <td key={r.variant_id} className={i > 0 && v !== valueText(refDc[k]) ? 'chg' : v === MISSING ? 'dim' : ''}>{v}</td> })}</tr>
            ))}
            <tr><td colSpan={colCount} style={{ fontSize: 12, fontWeight: 700, letterSpacing: '.06em', color: 'var(--muted)', background: '#fff' }}>DMA 전송 · 파랑 = 기준에 없음, 빨강 = 기준에만 있음</td></tr>
            {shownTrans.map((k) => (
              <tr key={k}><td className="rowhead mono" style={{ fontSize: 12 }}>{k}</td>
                {trans.map((t, i) => {
                  const v = t.get(k)
                  const refV = trans[0]?.get(k)
                  const cls = i === 0 ? '' : v && !refV ? 'add' : !v && refV ? 'del' : v !== refV ? 'chg' : ''
                  return <td key={i} className={`mono ${cls}`} style={{ fontSize: 12 }}>{v ?? MISSING}</td>
                })}</tr>
            ))}
            {viewsQ.loading && <tr><td colSpan={colCount} className="faint">view 불러오는 중…</td></tr>}
            <tr><td colSpan={colCount} style={{ fontSize: 12, fontWeight: 700, letterSpacing: '.06em', color: 'var(--muted)', background: '#fff' }}>KPI · 값 (기준 대비 Δ%) · evidence 출처</td></tr>
            <tr><td className="rowhead muted">evidence 출처</td>{evidence.map((e, i) => <td key={i}>{e ? <span className={`badge src-${evidenceSource(e)}`} title={e.id}>{evidenceSource(e)}</span> : <span className="dim">없음</span>}</td>)}</tr>
            {kpiRows.map((r) => (
              <tr key={r.label}><td className="rowhead muted">{r.label} ({r.unit})</td>
                {r.values.map((v, i) => {
                  const base = r.values[0]
                  const pct = i > 0 && v !== null && base ? ((v - base) / base) * 100 : null
                  return <td key={i} className="mono">{v === null ? <span className="dim">—</span> : v.toFixed(1)}{pct !== null && <span className="faint"> ({pct >= 0 ? '+' : ''}{pct.toFixed(1)}%)</span>}</td>
                })}</tr>
            ))}
          </tbody>
        </table>
      </div>

      </>}
      bottomTabs={pmTarget ? [{ id: 'pm', label: <>예측 vs 실측 <span className="tab-note">{ids[pmTarget.i]}</span></>, content: <>
        <div className="panel-head"><h2>예측 vs 실측 · {ids[pmTarget.i]}</h2>
          <span className={`badge src-${evidenceSource(pmTarget.meas!)}`}>{evidenceSource(pmTarget.meas!)}</span>
          <span className="muted" style={{ fontSize: 12 }}>{pmTarget.sim!.id} ↔ {pmTarget.meas!.id}</span></div>
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
