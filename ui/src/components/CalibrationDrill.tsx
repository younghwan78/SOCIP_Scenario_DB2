// Prediction ↔ measurement drill-down (CAL-09 · CAL-10 · CAL-11): where the error sits by rail,
// measured SW task tail vs the Timing Budget assumption, and IP clock / latency against the prediction.
import { Fragment, useState } from 'react'
import { CAT_COLOR, type Drilldown, type SwCompareRow } from '../lib/calibration'
import { band, pctS, signed, type CalSummary } from '../lib/calibrationSummary'

const fmt1 = (v: number | null | undefined) => (v === null || v === undefined ? '—' : v.toFixed(1))
const fmt2 = (v: number | null | undefined) => (v === null || v === undefined ? '—' : v.toFixed(2))
const BADGE = { ok: 'v-ok', warn: 'v-warn', fail: 'v-fail', '': '' } as const
const VERDICT_BADGE: Record<string, string> = { ok: 'v-ok', bias: 'v-warn', model_common: 'v-fail', scenario: 'v-warn', insufficient: '' }

/** CAL-09 (model level): median Δ per rail group over all compared variants, largest |ΔmW| first. */
export function RailBiasTable({ s }: { s: CalSummary }) {
  const rows = s.rail_bias ?? []
  if (!rows.length) return <div className="empty">rail 단위 비교 없음 (예측 IP node 분해 또는 실측 rail 필요)</div>
  const hi = Math.max(1, ...rows.map((r) => r.median_abs_delta_mw ?? 0))
  const lat = s.latency_bias
  return (
    <div>
      <table className="tb-mini-table cal-rb" style={{ width: '100%' }}>
        <thead><tr><th>rail 그룹</th><th>판정</th><th>median Δ%</th><th>p25 ~ p75</th><th>같은 부호</th><th>±10%</th><th>실측 median mW</th><th>median |ΔmW|</th></tr></thead>
        <tbody>{rows.map((r) => <tr key={r.key}>
          <td><span className="legend-item"><span style={{ width: 10, height: 10, background: CAT_COLOR[r.category as 'ip'] ?? '#999' }} /><b>{r.label}</b></span></td>
          <td><span className={`badge ${VERDICT_BADGE[r.verdict]}`}>{r.label_verdict}</span></td>
          <td className="mono"><span className={`badge ${BADGE[band(r.median)]}`}>{pctS(r.median)}</span></td>
          <td className="mono faint">{pctS(r.p25)} ~ {pctS(r.p75)}</td>
          <td className="mono">{fmt1(r.same_sign_pct)}%</td>
          <td className="mono">{r.within10} / {r.n}</td>
          <td className="mono">{fmt1(r.median_meas_mw)}</td>
          <td style={{ minWidth: 150 }}><span className="mono" style={{ display: 'inline-block', width: 44 }}>{fmt1(r.median_abs_delta_mw)}</span>
            <svg width={100} height={8} aria-hidden="true"><rect width={((r.median_abs_delta_mw ?? 0) / hi) * 100} height={8} fill={CAT_COLOR[r.category as 'ip'] ?? '#999'} /></svg></td>
        </tr>)}
        {lat && lat.n > 0 && <tr className="cal-rb-lat"><td><b>Latency (video)</b></td>
          <td><span className={`badge ${VERDICT_BADGE[lat.verdict]}`}>{lat.label}</span></td>
          <td className="mono"><span className={`badge ${BADGE[band(lat.median)]}`}>{pctS(lat.median)}</span></td>
          <td className="mono faint">{pctS(lat.p25)} ~ {pctS(lat.p75)}</td><td className="mono">{fmt1(lat.same_sign_pct)}%</td>
          <td className="mono">{lat.within10} / {lat.n}</td><td className="faint" colSpan={2}>예측 pipeline latency vs 실측 frame latency p95</td></tr>}
        </tbody>
      </table>
      <div className="faint" style={{ fontSize: 12, marginTop: 6 }}>IP는 예측 node의 vdd(simulation dvfs_breakdown)로 rail에 귀속합니다. 같은 rail에서 계속 같은 방향으로 틀리면(모델 공통) 그 domain IP의 단위전력 · clock 가정 또는 rail mapping부터 확인합니다.</div>
    </div>
  )
}

/** CAL-09 (one measurement): measured vs attributed prediction per rail group, error share, expandable. */
export function RailDrill({ d }: { d: Drilldown }) {
  const [open, setOpen] = useState<string | null>(null)
  const gs = d.rails.groups
  if (!gs.length) return <div className="empty">rail 실측 없음</div>
  const hi = Math.max(1, ...gs.flatMap((g) => [g.meas_mw, g.pred_mw ?? 0]))
  const W = 170
  return (
    <div>
      <table className="tb-mini-table cal-drill" style={{ width: '100%' }}>
        <thead><tr><th>rail 그룹 (|Δ| 큰 순)</th><th>실측 mW</th><th>예측 mW</th><th>Δ mW</th><th>Δ%</th><th title="|Δ mW| / Σ|Δ mW|">오차 기여</th><th>실측 ▬ · 예측 ▭</th></tr></thead>
        <tbody>{gs.map((g) => <Fragment key={g.key}>
          <tr onClick={() => setOpen(open === g.key ? null : g.key)} style={{ cursor: 'pointer' }} aria-expanded={open === g.key}>
            <td><span className="legend-item"><span style={{ width: 10, height: 10, background: CAT_COLOR[g.category] }} /><b>{g.label}</b></span>
              <span className="faint" style={{ fontSize: 11 }}> {open === g.key ? '▾' : '▸'} rail {g.rails.length}{g.pred_items.length ? ` · 예측 항목 ${g.pred_items.length}` : ''}</span>
              {g.note && <div className="faint" style={{ fontSize: 11 }}>{g.note}</div>}</td>
            <td className="mono">{fmt1(g.meas_mw)}</td>
            <td className="mono">{g.pred_mw === null ? <span className="faint">—</span> : fmt1(g.pred_mw)}</td>
            <td className="mono">{signed(g.delta_mw)}</td>
            <td>{g.delta_pct === null ? <span className="faint">—</span> : <span className={`badge ${BADGE[band(g.delta_pct)]}`}>{pctS(g.delta_pct)}</span>}</td>
            <td className="mono">{g.share_pct === null ? '—' : `${g.share_pct.toFixed(0)}%`}</td>
            <td><svg width={W} height={18} aria-hidden="true">
              <rect y={2} width={(g.meas_mw / hi) * W} height={7} fill={CAT_COLOR[g.category]} />
              {g.pred_mw !== null && <rect y={10} width={Math.max(1, (g.pred_mw / hi) * W)} height={6} fill="none" stroke={CAT_COLOR[g.category]} strokeWidth={1.4} />}
            </svg></td>
          </tr>
          {open === g.key && <tr className="cal-drill-sub"><td colSpan={7}>
            <div className="cal-drill-cols">
              <div><b>실측 rail</b>{g.rails.length ? <ul>{g.rails.map((r) => <li key={r.rail}><span className="mono">{r.rail}</span> {fmt1(r.mw)} mW</li>)}</ul> : <div className="faint">없음</div>}</div>
              <div><b>{g.category === 'cpu' ? '예측 (task별)' : g.category === 'ip' ? '예측 (IP node별)' : '예측'}</b>
                {g.pred_items.length ? <ul>{g.pred_items.map((p) => <li key={p.name}><span className="mono">{p.name}</span> {fmt1(p.mw)} mW{p.vdd && p.vdd !== g.label ? <span className="faint"> ({p.vdd})</span> : null}</li>)}</ul>
                  : <div className="faint">{g.category === 'bw' ? 'BW(DMA) 항 1개 — MIF · DRAM rail 합과 비교' : g.category === 'other' ? '모델 범위 밖' : '분해 없음'}</div>}</div>
              {g.category === 'cpu' && d.rails.cpu_clusters.length > 0 && <div><b>실측 cluster 비중</b>
                <ul>{d.rails.cpu_clusters.map((c) => <li key={c.rail}><span className="mono">{c.cluster}</span> {fmt1(c.mw)} mW · {c.share_pct.toFixed(0)}%</li>)}</ul>
                <div className="faint" style={{ fontSize: 11 }}>예측은 CPU를 task 단위로만 계산 — cluster 배치 비교는 CPU what-if에서</div></div>}
            </div>
          </td></tr>}
        </Fragment>)}</tbody>
      </table>
      {d.rails.notes.length > 0 && <ul className="faint" style={{ fontSize: 12, margin: '6px 0 0', paddingLeft: 18 }}>{d.rails.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
      {!d.rails.vdd_source && <div className="faint" style={{ fontSize: 12, marginTop: 4 }}>IP node → vdd: simulation dvfs_breakdown 없음 — DVFS group 이름으로 추정</div>}
    </div>
  )
}

const SW_STATUS: Record<SwCompareRow['status'], [string, string]> = {
  within: ['가정 이내', 'v-ok'], under_assumed: ['가정 초과', 'v-warn'], over_budget: ['예산 초과', 'v-fail'],
  measured_only: ['가정 없음', ''], assumed_only: ['실측 없음', ''],
}

/** CAL-10: measured task p95 vs the assumed value (prediction statistic) with stage margin. */
export function SwCompare({ d }: { d: Drilldown }) {
  const sw = d.sw
  if (!sw || !sw.rows.length) return <div className="empty">SW task 실측 · 가정 없음</div>
  const hi = Math.max(1, ...sw.rows.flatMap((r) => [r.assumed_ms ?? 0, r.p95_ms ?? 0, r.max_ms ?? 0]), sw.budget_ms ?? 0)
  const W = 200
  const X = (v: number) => (v / hi) * W
  return (
    <div>
      <div className="faint" style={{ fontSize: 12, marginBottom: 6 }}>
        가정 = 예측이 쓴 정의 SW timing의 <b>{sw.statistic}</b> · 실측 비교점 = p95 (frame 마감은 tail이 결정)
        {sw.budget_ms ? <> · {d.sw_stage?.toUpperCase()} stage 예산 {fmt1(sw.budget_ms)} ms</> : null}
        {sw.compared > 0 && <> · <b className={sw.optimistic ? 'warn-text' : ''}>가정보다 긴 task {sw.optimistic}/{sw.compared}</b></>}
      </div>
      <table className="tb-mini-table" style={{ width: '100%' }}>
        <thead><tr><th>task (Δ 큰 순)</th><th>가정 ms</th><th>실측 mean</th><th>p95</th><th>max</th><th>Δ ms (p95 − 가정)</th><th>margin 가정 → 실측</th><th>판정</th><th>▮ 가정 · ▬ p95 · | 예산</th></tr></thead>
        <tbody>{sw.rows.map((r) => { const [label, cls] = SW_STATUS[r.status]; return <tr key={r.task}>
          <td className="mono">{r.task}</td><td className="mono">{fmt2(r.assumed_ms)}</td><td className="mono">{fmt2(r.mean_ms)}</td>
          <td className="mono">{fmt2(r.p95_ms)}</td><td className="mono faint">{fmt2(r.max_ms)}</td>
          <td className="mono">{r.delta_ms === null ? '—' : `${signed(r.delta_ms, 2)} (${pctS(r.delta_pct)})`}</td>
          <td className="mono">{r.assumed_margin_pct === null ? '—' : `${r.assumed_margin_pct.toFixed(0)}%`} → {r.measured_margin_pct === null ? '—' : `${r.measured_margin_pct.toFixed(0)}%`}</td>
          <td>{cls ? <span className={`badge ${cls}`}>{label}</span> : <span className="faint">{label}</span>}</td>
          <td><svg width={W + 4} height={16} aria-hidden="true">
            {r.assumed_ms !== null && <rect y={2} width={X(r.assumed_ms)} height={5} fill="#9AA3B2" />}
            {r.p95_ms !== null && <rect y={9} width={X(r.p95_ms)} height={5} fill={r.status === 'within' ? '#0072B2' : '#D55E00'} />}
            {sw.budget_ms ? <line x1={X(sw.budget_ms)} x2={X(sw.budget_ms)} y1={0} y2={16} stroke="#1F2430" strokeDasharray="2 2" /> : null}
          </svg></td></tr> })}</tbody>
      </table>
    </div>
  )
}

/** CAL-11: predicted pipeline latency vs measured p95, predicted IP clock vs measured residency. */
export function ClockLatency({ d }: { d: Drilldown }) {
  const l = d.latency
  const clock = d.clock ?? []
  const measured = clock.filter((c) => c.meas_mhz !== null).length
  return (
    <div>
      <table className="tb-mini-table" style={{ width: '100%' }}>
        <thead><tr><th>항목</th><th>예측</th><th>실측</th><th>Δ%</th></tr></thead>
        <tbody>
          <tr><td><b>Pipeline latency (video)</b></td><td className="mono">{fmt1(l?.pred_ms)} ms</td>
            <td className="mono">{l?.meas_p95_ms !== null && l?.meas_p95_ms !== undefined ? `p95 ${fmt1(l.meas_p95_ms)} · mean ${fmt1(l.meas_mean_ms)} ms` : '—'}</td>
            <td>{l?.delta_pct === null || l?.delta_pct === undefined ? '—' : <span className={`badge ${BADGE[band(l.delta_pct)]}`}>{pctS(l.delta_pct)}</span>}</td></tr>
          {clock.map((c) => <tr key={c.group}><td>IP clock · <span className="mono">{c.group}</span> <span className="faint">({c.nodes} IP{c.dvfs_level !== null ? ` · L${c.dvfs_level}` : ''})</span></td>
            <td className="mono">{fmt1(c.pred_mhz)} MHz</td>
            <td className="mono">{c.meas_mhz === null ? <span className="faint">residency 없음</span> : `mean ${fmt1(c.meas_mhz)} · p50 ${fmt1(c.meas_p50_mhz)} MHz`}</td>
            <td>{c.delta_pct === null ? '—' : <span className={`badge ${BADGE[band(c.delta_pct)]}`}>{pctS(c.delta_pct)}</span>}</td></tr>)}
        </tbody>
      </table>
      {clock.length > 0 && measured === 0 && <div className="faint" style={{ fontSize: 12, marginTop: 6 }}>이 capture에는 IP domain(CAM · INT 등) clock residency가 없습니다. 측정 import에 <code>&lt;domain&gt;.freq_residency</code>가 있으면 예측 clock(DVFS level)과 나란히 표시됩니다.</div>}
      <div className="faint" style={{ fontSize: 12, marginTop: 4 }}>예측 latency가 실측 p95보다 크면 stage 직렬 가정이 보수적(pipelining 미반영)이고, 작으면 SW tail 또는 queueing이 누락된 것입니다.</div>
    </div>
  )
}
