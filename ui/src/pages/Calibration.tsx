import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { fmt } from '../lib/timingBudget'
import { CAT_COLOR, CAT_LABEL, CONDITION_LABEL, calibrationApi, errClass, type Category, type Conditions, type MeasDetail, type MeasRow, type PredictionCmp, type Rail } from '../lib/calibration'
import { short } from '../lib/archExplore'
import { Card } from '../components/TimingCharts'
import { useWidth } from '../components/Charts'
import { DataTable, type Column } from '../components/DataTable'
import { ProvBadge } from '../components/Provenance'
import { categoryFit, powerScope, type CategoryFit } from '../lib/provenance'

const CATS: Category[] = ['cpu', 'ip', 'bw', 'other']
type Prov = Parameters<typeof ProvBadge>[0]['prov']
type WithFit = { delta_pct: number | null; category?: CategoryFit | null } | null | undefined
/** Sort by the category error when known, else by the total error. */
const fitSort = (p: WithFit) => Math.abs(p?.category?.worst_delta_pct ?? p?.delta_pct ?? -1)
const fitTitle = (f: CategoryFit | null | undefined) => (f ? `구성 최대 Δ: ${f.worst_category ?? '—'} ${f.worst_delta_pct ?? '—'}%${f.offsetting ? '\n상쇄: total은 맞지만 구성 오차가 큼' : ''}` : '구성 Δ 없음 (rail 또는 예측 split 없음)')

/** U6: colour by the worst category, not the total; flag compensation. */
function FitCell({ total, delta, fit }: { total: number | null; delta: number | null; fit?: CategoryFit | null }) {
  const worst = fit?.worst_delta_pct
  return (
    <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
      <span className="mono faint">{fmt(total, 0)}{worst !== null && worst !== undefined ? ` · ${pctText(delta)}` : ''}</span>
      {worst !== null && worst !== undefined && <span className={`badge ${errClass(worst)}`}>{fit?.worst_category?.toUpperCase()} {pctText(worst)}</span>}
      {(worst === null || worst === undefined) && <span className={`badge ${errClass(delta)}`}>{pctText(delta)}</span>}
      {fit?.offsetting && <span className="offset-flag">상쇄</span>}
    </span>
  )
}
const pctText = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`)

export function CalibrationPage({ ctx }: { ctx: Ctx }) {
  const all = ctx.params.all === '1'
  const realOnly = ctx.params.real === '1'
  const list = useAsync(() => calibrationApi.measurements(all ? undefined : ctx.scenario), [ctx.scenario, all])
  const synthCount = (list.data ?? []).filter((r) => r.synthetic).length
  const rows = (list.data ?? []).filter((r) => !realOnly || !r.synthetic)
  const selId = rows.find((r) => r.id === ctx.params.m)?.id ?? rows[0]?.id
  const detail = useAsync(() => (selId ? calibrationApi.detail(selId) : Promise.resolve(null)), [selId])
  const cols: Column<MeasRow>[] = [
    { key: 'v', label: 'Variant', width: 280, sticky: true, sort: (r) => r.variant_id, render: (r) => <span className="mono">{short(r.variant_id)}{r.synthetic && <span className="badge v-warn" style={{ marginLeft: 6 }} title="생성된 fixture — silicon 측정 아님">합성</span>}</span> },
    { key: 'at', label: '측정', width: 130, firstDir: -1, sort: (r) => r.measured_at ?? '', render: (r) => <span className="mono faint">{r.measured_at?.slice(0, 10) ?? '—'}</span> },
    { key: 'ctx', label: 'Silicon · SW', width: 190, sort: (r) => `${r.silicon_rev}${r.sw_baseline_ref}`, render: (r) => <span className="faint">{r.silicon_rev ?? '—'} · {r.sw_baseline_ref ?? '—'}</span> },
    { key: 'meas', label: '실측 mW', width: 110, align: 'right', firstDir: -1, sort: (r) => r.total.mean ?? -1, render: (r) => <span className="mono">{fmt(r.total.mean, 1)}{r.total.std ? <span className="faint"> ±{fmt(r.total.std, 1)}</span> : null}</span> },
    { key: 'cur', label: '등록 예측 Δ (total · 구성 최대)', width: 230, align: 'right', firstDir: -1, sort: (r) => fitSort(r.current_prediction), title: (r) => fitTitle(r.current_prediction?.category), render: (r) => r.current_prediction ? <FitCell total={r.current_prediction.total_mw} delta={r.current_prediction.delta_pct} fit={r.current_prediction.category} /> : <span className="faint">등록 없음</span> },
    { key: 'sim', label: 'Simulation Δ (total · 구성 최대)', width: 230, align: 'right', firstDir: -1, sort: (r) => fitSort(r.simulation), title: (r) => fitTitle(r.simulation?.category), render: (r) => r.simulation ? <FitCell total={r.simulation.total_mw} delta={r.simulation.delta_pct} fit={r.simulation.category} /> : <span className="faint">—</span> },
    { key: 'rails', label: 'rail', width: 60, align: 'right', sort: (r) => r.rails, render: (r) => r.rails },
  ]
  return (
    <div className="page tb-page">
      <div className="toolbar" style={{ gap: 12, flexWrap: 'wrap' }}>
        <div className="seg sm" role="group" aria-label="범위">
          <button className={!all ? 'on' : ''} onClick={() => ctx.navigate(undefined, { all: undefined, m: undefined }, true)}>현재 scenario</button>
          <button className={all ? 'on' : ''} onClick={() => ctx.navigate(undefined, { all: '1', m: undefined }, true)}>전체</button>
        </div>
        {synthCount > 0 && <div className="seg sm" role="group" aria-label="합성 fixture">
          <button className={!realOnly ? 'on' : ''} onClick={() => ctx.navigate(undefined, { real: undefined, m: undefined }, true)}>합성 포함 ({synthCount})</button>
          <button className={realOnly ? 'on' : ''} onClick={() => ctx.navigate(undefined, { real: '1', m: undefined }, true)}>실제 측정만</button>
        </div>}
        <span className="faint" style={{ fontSize: 12 }}>실측 rail을 CPU · IP · BW(MIF·DRAM) · 기타로 묶어 예측과 비교합니다. 색 = total이 아닌 <b>구성(CPU·IP·BW) 최대 |Δ|</b> 기준 · ≤10% 녹색 · ≤25% 주황 · 그 이상 빨강 · “상쇄” = total은 맞지만 구성 오차가 서로 상쇄</span>
      </div>
      {list.error && <div className="err">{list.error}</div>}
      {list.data && !rows.length && <div className="empty">{realOnly && synthCount ? '실제 측정 evidence가 없습니다 (합성 fixture만 있음).' : '실측 evidence가 없습니다. 측정 결과를 import하면 여기에 나타납니다.'}</div>}
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
  const curFit = cur ? categoryFit(cur.rows, cur.delta_pct) : null
  const simFit = sim ? categoryFit(sim.rows, sim.delta_pct) : null
  const kpis: [string, string, string, string, Prov | null][] = [
    ['실측 total', `${fmt(d.total.mean, 1)}`, totalStats(d.total), '',
      { kind: d.synthetic ? 'synthetic' : 'measured', id: d.id, at: d.measured_at, notes: [`rail map: ${d.rail_domain_map_ref ?? '이름 규칙'}${d.rail_map_basis === 'latest' ? ' (최신 profile — 측정 시점 미고정)' : ''}`] }],
    ['등록 예측', cur ? fmt(cur.total_mw, 1) : '—', cur ? `${pctText(cur.delta_pct)} · 구성 최대 ${pctText(curFit?.worst_delta_pct)} · ${cur.statistic ?? ''}${condText(cur.conditions)}` : '조합 탐색에서 등록 필요', cur ? errClass(curFit?.worst_delta_pct ?? cur.delta_pct) : '',
      cur ? { kind: 'registered', engine: 'Arch exploration', scope: powerScope(cur.split), id: cur.id, notes: [`선택: ${cur.selection_rule ?? '—'}`] } : null],
    ['Simulation evidence (최신)', sim ? fmt(sim.total_mw, 1) : '—', sim ? `${pctText(sim.delta_pct)} · 구성 최대 ${pctText(simFit?.worst_delta_pct)} · ${sims.length}건${condText(sim.conditions)}` : '없음', sim ? errClass(simFit?.worst_delta_pct ?? sim.delta_pct) : '',
      sim ? { kind: 'simulation', engine: 'Timeline sim (runner)', scope: powerScope(sim.split), id: sim.id, notes: sim.split && !(sim.split.cpu > 0) ? ['CPU power 미포함 — total 비교 시 주의'] : [] } : null],
    ['fps · latency', `${fmt(d.fps, 2)}`, d.frame_latency ? `latency mean ${fmt(d.frame_latency.mean, 1)} / p95 ${fmt(d.frame_latency.p95, 1)} ms` : '', '', null],
  ]
  const offset = [curFit?.offsetting ? '등록 예측' : null, simFit?.offsetting ? 'Simulation evidence' : null].filter(Boolean)
  return <>
    {d.synthetic && <div className="lib-note warn" style={{ gridColumn: '1 / -1' }}>합성 fixture — silicon 측정이 아닙니다. 기준 capture를 이 variant의 simulation(IP core · BW)과 SW 부하(CPU)로 rescale한 값이라 예측 오차는 모델 검증 근거가 되지 않습니다{d.derived_from?.length ? ` (source: ${d.derived_from.join(', ')})` : ''}.</div>}
    {offset.length > 0 && <div className="lib-note warn" style={{ gridColumn: '1 / -1' }}>{offset.join(' · ')}: total은 실측과 ±10% 안이지만 CPU · IP · BW 중 25% 넘게 틀린 항목이 있습니다. 구성 오차가 서로 상쇄된 결과라 what-if(예: BW 절감) 예측은 신뢰하기 어렵습니다.</div>}
    <section className="tb-kpis" style={{ gridColumn: '1 / -1' }} aria-label="요약">
      {kpis.map(([l, v, n, cls, prov]) => (
        <div key={l} className="panel tb-kpi"><div className="faint" style={{ fontSize: 12 }}>{l}{prov && <> <ProvBadge prov={prov} compact /></>}</div>
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
    {cols.some((p) => p.conditions) && <Card id="cal-cond" title="비교 조건 동등성" note="조건이 다르면 Δ는 참고 비교 · 미기록은 동등성 확인 불가" defaultWide>
      <ConditionTable preds={d.predictions.filter((p) => p.conditions)} />
      {d.origin === 'unknown' && <div className="lib-note warn" style={{ marginTop: 6 }}>측정 출처(provenance) 미기록 — 실측 정확도 근거에서 제외됩니다.</div>}
    </Card>}
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

/** n is shown even when std = 0 (a single capture is not a distribution). */
function totalStats(t: MeasDetail['total']): string {
  const parts = [t.std !== null && t.std !== undefined ? `±${fmt(t.std, 1)} mW` : 'mW', `n=${t.n ?? '—'}`]
  if (t.ci_95?.length === 2) parts.push(`CI ${fmt(t.ci_95[0], 1)}–${fmt(t.ci_95[1], 1)}`)
  return parts.join(' · ')
}

function condText(c: Conditions | undefined): string {
  return c ? ` · ${CONDITION_LABEL[c.overall]}` : ''
}

const COND_ITEM: Record<string, string> = { silicon_rev: 'Silicon', sw_baseline_ref: 'SW build', thermal: 'Thermal', power_state: 'Power state', ambient_temp_c: '온도 °C' }
const COND_MARK = { match: ['일치', 'v-ok'], mismatch: ['불일치', 'v-fail'], unrecorded: ['미기록', 'v-warn'] } as const

function ConditionTable({ preds }: { preds: PredictionCmp[] }) {
  const items = preds[0]?.conditions?.items.map((i) => i.item) ?? []
  return <table className="tb-mini-table" style={{ width: '100%' }}>
    <thead><tr><th>조건</th><th>실측</th>{preds.map((p) => <th key={p.id} title={p.id}>{predLabel(p)}</th>)}</tr></thead>
    <tbody>{items.map((k) => <tr key={k}><td>{COND_ITEM[k] ?? k}</td>
      <td className="mono">{String(preds[0].conditions?.items.find((i) => i.item === k)?.measured ?? '—')}</td>
      {preds.map((p) => { const it = p.conditions?.items.find((i) => i.item === k); const [label, cls] = COND_MARK[it?.status ?? 'unrecorded']
        return <td key={p.id}><span className="mono">{String(it?.predicted ?? '—')}</span> <span className={`badge ${cls}`}>{label}</span></td> })}</tr>)}
      <tr><td><b>판정</b></td><td />{preds.map((p) => <td key={p.id}><b>{p.conditions ? CONDITION_LABEL[p.conditions.overall] : '—'}</b></td>)}</tr>
    </tbody>
  </table>
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
