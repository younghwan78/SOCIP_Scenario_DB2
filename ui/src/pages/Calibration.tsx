import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { fmt } from '../lib/timingBudget'
import { CAT_COLOR, CAT_LABEL, calibrationApi, errClass, type Category, type MeasDetail, type MeasRow, type PredictionCmp, type Rail } from '../lib/calibration'
import { short } from '../lib/archExplore'
import { Card } from '../components/TimingCharts'
import { useWidth } from '../components/Charts'
import { DataTable, type Column } from '../components/DataTable'

const CATS: Category[] = ['cpu', 'ip', 'bw', 'other']
const pctText = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`)

export function CalibrationPage({ ctx }: { ctx: Ctx }) {
  const all = ctx.params.all === '1'
  const list = useAsync(() => calibrationApi.measurements(all ? undefined : ctx.scenario), [ctx.scenario, all])
  const rows = list.data ?? []
  const selId = ctx.params.m ?? rows[0]?.id
  const detail = useAsync(() => (selId ? calibrationApi.detail(selId) : Promise.resolve(null)), [selId])
  const cols: Column<MeasRow>[] = [
    { key: 'v', label: 'Variant', width: 220, sticky: true, sort: (r) => r.variant_id, render: (r) => <span className="mono">{short(r.variant_id)}</span> },
    { key: 'at', label: '측정', width: 130, firstDir: -1, sort: (r) => r.measured_at ?? '', render: (r) => <span className="mono faint">{r.measured_at?.slice(0, 10) ?? '—'}</span> },
    { key: 'ctx', label: 'Silicon · SW', width: 190, sort: (r) => `${r.silicon_rev}${r.sw_baseline_ref}`, render: (r) => <span className="faint">{r.silicon_rev ?? '—'} · {r.sw_baseline_ref ?? '—'}</span> },
    { key: 'meas', label: '실측 mW', width: 110, align: 'right', firstDir: -1, sort: (r) => r.total.mean ?? -1, render: (r) => <span className="mono">{fmt(r.total.mean, 1)}{r.total.std ? <span className="faint"> ±{fmt(r.total.std, 1)}</span> : null}</span> },
    { key: 'cur', label: '등록 예측 Δ', width: 130, align: 'right', firstDir: -1, sort: (r) => Math.abs(r.current_prediction?.delta_pct ?? -1), render: (r) => r.current_prediction ? <span className={`badge ${errClass(r.current_prediction.delta_pct)}`}>{fmt(r.current_prediction.total_mw, 0)} · {pctText(r.current_prediction.delta_pct)}</span> : <span className="faint">등록 없음</span> },
    { key: 'sim', label: 'Simulation Δ', width: 130, align: 'right', firstDir: -1, sort: (r) => Math.abs(r.simulation?.delta_pct ?? -1), render: (r) => r.simulation ? <span className={`badge ${errClass(r.simulation.delta_pct)}`}>{fmt(r.simulation.total_mw, 0)} · {pctText(r.simulation.delta_pct)}</span> : <span className="faint">—</span> },
    { key: 'rails', label: 'rail', width: 60, align: 'right', sort: (r) => r.rails, render: (r) => r.rails },
  ]
  return (
    <div className="page tb-page">
      <div className="toolbar" style={{ gap: 12, flexWrap: 'wrap' }}>
        <div className="seg sm" role="group" aria-label="범위">
          <button className={!all ? 'on' : ''} onClick={() => ctx.navigate(undefined, { all: undefined, m: undefined }, true)}>현재 scenario</button>
          <button className={all ? 'on' : ''} onClick={() => ctx.navigate(undefined, { all: '1', m: undefined }, true)}>전체</button>
        </div>
        <span className="faint" style={{ fontSize: 12 }}>실측 rail을 CPU · IP · BW(MIF·DRAM) · 기타로 묶어 예측과 비교합니다. |Δ| ≤10% 녹색 · ≤25% 주황 · 그 이상 빨강</span>
      </div>
      {list.error && <div className="err">{list.error}</div>}
      {list.data && !rows.length && <div className="empty">실측 evidence가 없습니다. 측정 결과를 import하면 여기에 나타납니다.</div>}
      {rows.length > 0 && <div className="tb-grid">
        <Card id="cal-list" title="실측 evidence" note="행 클릭 = 상세" defaultWide minHeight={140}>
          <div className="table-x">
            <DataTable id="cal.list" columns={cols} rows={rows} rowKey={(r) => r.id} onRowClick={(r) => ctx.navigate(undefined, { m: r.id }, true)}
              rowClass={(r) => (r.id === selId ? 'selected' : '')} defaultSort={{ key: 'at', dir: -1 }} />
          </div>
        </Card>
        {detail.error && <div className="err" style={{ gridColumn: '1 / -1' }}>{detail.error}</div>}
        {detail.data && <Detail d={detail.data} ctx={ctx} />}
      </div>}
    </div>
  )
}

function Detail({ d, ctx }: { d: MeasDetail; ctx: Ctx }) {
  const cur = d.predictions.find((p) => p.kind === 'current')
  const sims = d.predictions.filter((p) => p.kind === 'simulation')
  const sim = sims[sims.length - 1] // latest — same pick as the list row
  const cols = d.predictions.filter((p) => p.rows)
  const kpis: [string, string, string, string][] = [
    ['실측 total', `${fmt(d.total.mean, 1)}`, d.total.std ? `±${fmt(d.total.std, 1)} mW · n=${d.total.n ?? '—'}` : 'mW', ''],
    ['등록 예측', cur ? fmt(cur.total_mw, 1) : '—', cur ? `${pctText(cur.delta_pct)} · ${cur.statistic ?? ''} · ${cur.selection_rule ?? ''}` : '조합 탐색에서 등록 필요', cur ? errClass(cur.delta_pct) : ''],
    ['Simulation evidence (최신)', sim ? fmt(sim.total_mw, 1) : '—', sim ? `${pctText(sim.delta_pct)} · ${predLabel(sim)} · ${sims.length}건` : '없음', sim ? errClass(sim.delta_pct) : ''],
    ['fps · latency', `${fmt(d.fps, 2)}`, d.frame_latency ? `latency mean ${fmt(d.frame_latency.mean, 1)} / p95 ${fmt(d.frame_latency.p95, 1)} ms` : '', ''],
  ]
  return <>
    <section className="tb-kpis" style={{ gridColumn: '1 / -1' }} aria-label="요약">
      {kpis.map(([l, v, n, cls]) => (
        <div key={l} className="panel tb-kpi"><div className="faint" style={{ fontSize: 12 }}>{l}</div>
          <div className="mono" style={{ fontSize: 20, fontWeight: 600 }}>{v}</div>
          <div style={{ fontSize: 11 }}>{cls ? <span className={`badge ${cls}`}>{n}</span> : <span className="faint">{n}</span>}</div></div>))}
    </section>
    <Card id="cal-split" title={`${short(d.variant_id)} — CPU · IP · BW 예측 vs 실측`} note={`rail 합 ${fmt(d.measured.rail_total_mw, 1)} mW · 미귀속 ${fmt(d.unexplained_mw, 1)} mW · rail map ${d.rail_domain_map_ref ?? '이름 규칙'}`} defaultWide>
      <SplitChart d={d} />
      <table className="tb-mini-table" style={{ width: '100%', marginTop: 10 }}>
        <thead><tr><th>구분</th><th>실측 mW</th>{cols.map((p) => <th key={p.id} title={p.id}>{predLabel(p)} mW (Δ%)</th>)}</tr></thead>
        <tbody>{CATS.map((c) => (
          <tr key={c}><td><span className="legend-item"><span style={{ width: 10, height: 10, background: CAT_COLOR[c] }} />{CAT_LABEL[c]}</span></td>
            <td className="mono">{fmt(d.measured.categories[c], 1)} <span className="faint">±{fmt(d.measured.category_std[c], 1)}</span></td>
            {cols.map((p) => { const r = p.rows?.find((x) => x.category === c); return (
              <td key={p.id} className="mono">{r?.prediction_mw === null || r?.prediction_mw === undefined ? <span className="faint">미모델</span>
                : <>{fmt(r.prediction_mw, 1)} <span className={`badge ${errClass(r.delta_pct)}`}>{pctText(r.delta_pct)}</span></>}</td>) })}
          </tr>))}</tbody>
      </table>
      <div className="faint" style={{ fontSize: 12, marginTop: 6 }}>예측 BW 전력은 모델상 MIF·DRAM rail로 귀속됩니다 (MIF DVFS 미반영). 기타 rail(GPU·SRAM·ICPU 등)은 scenario power model 밖입니다.</div>
    </Card>
    <Card id="cal-rails" title="Rail별 실측" note="분류 = sim config rail map → 이름 규칙">
      <RailTable rails={d.measured.rails} />
    </Card>
    <Card id="cal-sw" title="SW task 실측" note="Timing Budget의 SW 가정과 비교">
      {d.sw_tasks.length ? <table className="tb-mini-table" style={{ width: '100%' }}>
        <thead><tr><th>task</th><th>mean ms</th><th>p95 ms</th><th>max ms</th><th>cluster</th></tr></thead>
        <tbody>{d.sw_tasks.map((t) => <tr key={t.task}><td className="mono">{t.task}</td><td className="mono">{fmt(t.mean_ms, 2)}</td><td className="mono">{fmt(t.p95_ms, 2)}</td><td className="mono">{fmt(t.max_ms, 2)}</td><td className="faint">{t.cluster ?? '—'}</td></tr>)}</tbody>
      </table> : <div className="empty">SW task 실측 없음</div>}
      <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
        <a className="btn" href={`#/timing?scenario=${encodeURIComponent(d.scenario_id)}&variant=${encodeURIComponent(d.variant_id)}`}>Timing Budget →</a>
        <a className="btn" href={`#/library?tab=sw&scenario=${encodeURIComponent(d.scenario_id)}`}>SW timing 가정 →</a>
        <button className="btn" onClick={() => ctx.navigate('predictions', { scenario: d.scenario_id, v: cur?.id })}>예측 현황 →</button>
      </div>
    </Card>
  </>
}

/** Column label; simulation evidence is disambiguated by its date suffix. */
function predLabel(p: PredictionCmp): string {
  if (p.kind === 'current') return '등록 예측'
  const date = /(\d{4})(\d{2})(\d{2})$/.exec(p.id)
  return date ? `Sim ${date[2]}-${date[3]}` : 'Simulation'
}

function SplitChart({ d }: { d: MeasDetail }) {
  const [ref, w] = useWidth<HTMLDivElement>(700)
  const series = [{ label: '실측', vals: d.measured.categories as Record<Category, number | null> },
    ...d.predictions.filter((p) => p.split).map((p) => ({ label: predLabel(p), vals: { ...(p.split as Record<'cpu' | 'ip' | 'bw', number>), other: null } as Record<Category, number | null> }))]
  const labelW = 90, valW = 90, rh = 22
  const plotW = Math.max(200, w - labelW - valW)
  const hi = Math.max(1, ...series.map((s) => CATS.reduce((a, c) => a + (s.vals[c] ?? 0), 0)))
  const k = plotW / hi
  return (
    <div ref={ref}>
      <svg width={labelW + plotW + valW} height={series.length * rh + 4} role="img" aria-label="CPU IP BW 비교">
        {series.map((s, i) => { let x = labelW; const tot = CATS.reduce((a, c) => a + (s.vals[c] ?? 0), 0); return (
          <g key={s.label} transform={`translate(0,${i * rh})`}>
            <text x={labelW - 8} y={15} fontSize={12} textAnchor="end" fill="#3B3F4A">{s.label}</text>
            {CATS.map((c) => { const v = s.vals[c]; if (!v) return null; const wv = v * k; const el = <rect key={c} x={x} y={3} width={wv} height={14} fill={CAT_COLOR[c]}><title>{`${CAT_LABEL[c]} ${v.toFixed(1)} mW`}</title></rect>; x += wv; return el })}
            <text x={x + 6} y={15} fontSize={11} className="mono" fill="#3B3F4A">{tot.toFixed(0)} mW</text>
          </g>) })}
      </svg>
      <div className="legend-row">{CATS.map((c) => <span key={c} className="legend-item"><span style={{ width: 10, height: 10, background: CAT_COLOR[c] }} />{CAT_LABEL[c]}</span>)}</div>
    </div>
  )
}

function RailTable({ rails }: { rails: Rail[] }) {
  const hi = Math.max(1, ...rails.map((r) => r.power_mw))
  return (
    <table className="tb-mini-table" style={{ width: '100%' }}>
      <thead><tr><th>rail</th><th>구분</th><th>mW</th><th /></tr></thead>
      <tbody>{rails.map((r) => (
        <tr key={r.rail}><td className="mono" style={{ fontSize: 11 }}>{r.rail}</td><td>{CAT_LABEL[r.category]}</td>
          <td className="mono">{fmt(r.power_mw, 1)}</td>
          <td style={{ width: 120 }}><svg width={110} height={8} aria-hidden="true"><rect width={(r.power_mw / hi) * 110} height={8} fill={CAT_COLOR[r.category]} /></svg></td></tr>))}</tbody>
    </table>
  )
}
