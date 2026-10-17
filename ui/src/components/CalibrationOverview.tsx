// Prediction ↔ measurement, model level (CAL-01..07): accuracy tiles, category bias strip with an
// automatic diagnosis, correction preview, variant × category error matrix, parity small multiples,
// and the per-measurement error waterfall (CAL-04).
import { useMemo } from 'react'
import { useWidth } from './Charts'
import { useTip } from './ChartTip'
import { CAT_COLOR } from '../lib/calibration'
import type { MeasDetail } from '../lib/calibration'
import { short } from '../lib/archExplore'
import {
  BIAS_CATS, GROUPS, absGapMw, band, groupOf, pctS, signed, sortRows, waterfall,
  type BiasCat, type CalSummary, type MatrixSort, type SummaryRow,
} from '../lib/calibrationSummary'

const fmt1 = (v: number | null | undefined) => (v === null || v === undefined ? '—' : v.toFixed(1))
const BADGE = { ok: 'v-ok', warn: 'v-warn', fail: 'v-fail', '': '' } as const
const VERDICT_BADGE: Record<string, string> = { ok: 'v-ok', bias: 'v-warn', model_common: 'v-fail', scenario: 'v-warn', insufficient: '' }

/** CAL-01 + CAL-06: what a reader needs before any table. */
export function SummaryTiles({ s }: { s: CalSummary }) {
  const t = s.bias.total
  const tile = (label: string, value: string, note: string, cls = '', key = label) => (
    <div key={key} className="panel tb-kpi"><div className="faint" style={{ fontSize: 12 }}>{label}</div>
      <div className={`mono ${cls}`} style={{ fontSize: 20, fontWeight: 600 }}>{value}</div>
      <div className="faint" style={{ fontSize: 11 }}>{note}</div></div>)
  const catTile = (k: 'cpu' | 'ip' | 'bw') => {
    const b = s.bias[k]
    const cls = b.median === null ? '' : `cal-t-${band(b.median)}`
    return tile(`${k.toUpperCase()} median Δ`, pctS(b.median), b.n ? `${b.label} · 같은 부호 ${fmt1(b.same_sign_pct)}% · ±10% ${b.within10}/${b.n}` : '비교 없음', cls)
  }
  const o = s.coverage.origin
  return (
    <section className="tb-kpis" aria-label="예측 정확도 요약">
      <div className="panel tb-kpi"><div className="faint" style={{ fontSize: 12 }}>모델 신뢰도</div>
        <div className={`mono cal-grade g-${s.confidence.grade}`} style={{ fontSize: 20, fontWeight: 700 }}>{s.confidence.grade}</div>
        <div className="faint" style={{ fontSize: 11 }} title={s.confidence.reasons.join('\n')}>{s.confidence.reasons[0] ?? s.confidence.meaning}</div></div>
      {tile('비교 variant', `${s.coverage.compared}`, `등록 예측 ${s.coverage.with_prediction} · 실측 ${s.coverage.with_measurement} / ${s.coverage.variants} variant · 출처 실측 ${o.physical_capture ?? 0} · 합성 ${o.synthetic ?? 0}${o.unknown ? ` · 미기록 ${o.unknown}` : ''}`)}
      {tile('Total |Δ| ≤ 10%', `${t.within10} / ${t.n}`, `${s.offsetting ? `상쇄 ${s.offsetting}건 포함 · ` : ''}≤ 25%: ${t.within25} · median ${pctS(t.median)}`, s.offsetting && s.offsetting >= t.within10 / 2 ? 'cal-t-warn' : '')}
      {catTile('cpu')}{catTile('ip')}{catTile('bw')}
      {tile('미모델 rail 비중', s.unmodeled_share_pct === null ? '—' : `${s.unmodeled_share_pct.toFixed(1)}%`, 'GPU · SRAM · ICPU 등 · 실측 total 대비 median')}
    </section>
  )
}

/** CAL-02: one row per category, one dot per variant; median tick; ±10 / ±25 % bands. */
export function BiasStrip({ s, onPick }: { s: CalSummary; onPick?: (r: SummaryRow) => void }) {
  const [ref, w] = useWidth<HTMLDivElement>(820)
  const tip = useTip()
  const rows = s.rows.filter((r) => r.delta_pct)
  const all = rows.flatMap((r) => BIAS_CATS.map((c) => r.delta_pct?.[c.k] ?? null)).filter((v): v is number => v !== null)
  const lo = Math.min(-40, Math.floor(Math.min(0, ...all) / 20) * 20)
  const hi = Math.max(40, Math.ceil(Math.max(0, ...all) / 20) * 20)
  const left = 136, right = 18, rowH = 50, top = 8
  const H = top + rowH * BIAS_CATS.length + 34
  const X = (v: number) => left + ((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * (w - left - right)
  const yB = top + rowH * BIAS_CATS.length
  const ticks: number[] = []
  const step = hi - lo > 200 ? 40 : 20
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) ticks.push(t)
  if (!rows.length) return <div className="empty">등록 예측과 비교할 실측이 없습니다.</div>
  return (
    <div ref={ref}>
      <svg width={w} height={H} role="img" aria-label="구성별 예측 오차 분포">
        <rect x={X(-25)} y={top} width={X(25) - X(-25)} height={yB - top} fill="#FBF0DA" />
        <rect x={X(-10)} y={top} width={X(10) - X(-10)} height={yB - top} fill="#E1EEEA" />
        {ticks.map((t) => <g key={t}>
          <line x1={X(t)} x2={X(t)} y1={top} y2={yB} stroke={t === 0 ? '#8A8274' : '#EFEAE2'} strokeDasharray={t === 0 ? '3 3' : undefined} />
          <text x={X(t)} y={yB + 14} fontSize={11} textAnchor="middle" className="mono" fill="#6B6558">{t > 0 ? '+' : t < 0 ? '−' : ''}{Math.abs(t)}%</text>
        </g>)}
        <text x={w - right} y={yB + 29} fontSize={11} textAnchor="end" fill="#6B6558">Δ% = (예측 − 실측) / 실측</text>
        {BIAS_CATS.map((c, i) => {
          const cy = top + i * rowH + rowH / 2
          const b = s.bias[c.k]
          return <g key={c.k}>
            {i > 0 && <line x1={left} x2={w - right} y1={top + i * rowH} y2={top + i * rowH} stroke="#EFEAE2" />}
            <rect x={4} y={cy - 12} width={10} height={10} rx={2} fill={c.color} />
            <text x={20} y={cy - 3} fontSize={12.5} fontWeight={600} fill="#1F2430">{c.label}</text>
            <text x={20} y={cy + 13} fontSize={11} className="mono" fill="#3B3F4A">median {pctS(b.median)}</text>
            {rows.map((r, j) => {
              const v = r.delta_pct?.[c.k]
              if (v === null || v === undefined) return null
              const jit = (((j * 37) % 23) / 22 - 0.5) * 24
              return <circle key={r.measurement_id} cx={X(v)} cy={cy + jit} r={4.2} fill={c.color} fillOpacity={0.78} stroke="#fff" strokeWidth={1}
                style={{ cursor: onPick ? 'pointer' : undefined }} onClick={() => onPick?.(r)}
                {...tip({ title: short(r.variant_id), color: c.color, head: { label: `${c.label} Δ`, value: pctS(v) },
                  rows: [{ k: '예측', v: `${fmt1(c.k === 'total' ? r.pred?.total : r.pred?.[c.k as 'cpu'])} mW` },
                    { k: '실측', v: `${fmt1(c.k === 'total' ? r.meas.total : r.meas[c.k as 'cpu'])} mW` },
                    ...(c.k === 'total' && r.fit?.offsetting ? [{ k: '상쇄', v: `${r.fit.worst_category?.toUpperCase()} ${pctS(r.fit.worst_delta_pct)}`, tone: 'bad' as const }] : [])],
                  foot: `${groupOf(r.variant_id, r.fps)} · ${r.synthetic ? '합성' : r.origin}${onPick ? ' · 클릭 = 상세' : ''}` })} />
            })}
            {b.median !== null && <line x1={X(b.median)} x2={X(b.median)} y1={cy - 19} y2={cy + 19} stroke="#1F2430" strokeWidth={2.5} />}
          </g>
        })}
      </svg>
      <div className="legend-row">{BIAS_CATS.map((c) => <span key={c.k} className="legend-item"><span style={{ width: 10, height: 10, borderRadius: 5, background: c.color }} />{c.label}</span>)}
        <span className="legend-item"><span style={{ width: 12, height: 10, background: '#E1EEEA' }} />±10%</span>
        <span className="legend-item"><span style={{ width: 12, height: 10, background: '#FBF0DA' }} />±25%</span></div>
    </div>
  )
}

/** CAL-02 diagnosis: per-category verdict sentence + the flat-term detector. */
export function BiasDiagnosis({ s }: { s: CalSummary }) {
  const items: { cat: BiasCat; text: string; cls: string }[] = []
  for (const c of BIAS_CATS) {
    if (c.k === 'total') continue
    const b = s.bias[c.k]
    if (!b.n) continue
    const range = `범위 ${pctS(b.min)} ~ ${pctS(b.max)}`
    const dir = b.sign > 0 ? '과대' : b.sign < 0 ? '과소' : '혼재'
    const text = b.verdict === 'model_common'
      ? `${b.n}건 중 ${fmt1(b.same_sign_pct)}%가 ${dir}예측, median ${pctS(b.median)} (${range}). 계수 · 모델 형태 · rail mapping을 먼저 확인합니다.`
      : b.verdict === 'bias'
        ? `${dir}예측 쪽으로 치우침 (같은 부호 ${fmt1(b.same_sign_pct)}%, median ${pctS(b.median)}, ${range}).`
        : b.verdict === 'scenario'
          ? `부호가 섞여 있어 공통 계수 하나로 맞지 않습니다 (median ${pctS(b.median)}, ${range}). 모드 · clock · 단위전력을 variant별로 봅니다.`
          : b.verdict === 'ok' ? `±10% 이내 ${b.within10}/${b.n}.` : `비교 ${b.n}건 — 판단 보류.`
    items.push({ cat: c.k, text, cls: VERDICT_BADGE[b.verdict] })
  }
  const flat = s.flat_cpu
  return (
    <div className="cal-diag">
      <b>자동 진단</b> <span className="faint">규칙: 같은 부호 ≥ 80% 이고 |median| &gt; 25% → 모델 공통 오차</span>
      <ul>
        {items.map((it) => <li key={it.cat}><span className={`badge ${it.cls}`}>{it.cat.toUpperCase()} · {s.bias[it.cat].label}</span> {it.text}</li>)}
        {flat && <li><span className="badge v-warn">CPU 예측 형태</span> {flat.n}건 중 {flat.count}건의 CPU 예측이 {flat.mw_at_base_fps} mW × fps/{flat.base_fps}입니다. SW 부하가 반영되지 않는 flat CPU 항이므로 측정 profile 기반 CPU 모델(<code>cpu_model=profile</code>)이 후보입니다.</li>}
        {s.offsetting > 0 && <li><span className="badge v-warn">상쇄</span> total ±10% 이내 {s.bias.total.within10}건 중 {s.offsetting}건은 구성 오차(&gt; 25%)가 서로 상쇄된 결과입니다. 이 variant들의 what-if 절감량은 신뢰하기 어렵습니다.</li>}
      </ul>
    </div>
  )
}

/** CAL-07 (preview): single-coefficient correction per category (median measured/predicted). */
export function CorrectionPreview({ s }: { s: CalSummary }) {
  const p = s.correction.previews
  if (!p.length) return <div className="empty">보정 preview를 계산할 비교가 없습니다.</div>
  const base = p[0]
  return (
    <div>
      <table className="tb-mini-table" style={{ width: '100%' }}>
        <thead><tr><th>보정 (median 실측/예측 비 적용)</th><th>CPU ×</th><th>IP ×</th><th>BW ×</th><th>total median Δ</th><th>±10% 이내</th><th>최대 |Δ|</th></tr></thead>
        <tbody>{p.map((r) => <tr key={r.label}>
          <td>{r.label}</td>
          {(['cpu', 'ip', 'bw'] as const).map((c) => <td key={c} className="mono">{r.factors[c] === 1 ? '—' : r.factors[c].toFixed(2)}</td>)}
          <td className="mono"><span className={`badge ${BADGE[band(r.median)]}`}>{pctS(r.median)}</span></td>
          <td className="mono">{r.within10} / {r.n}{r === base && s.offsetting ? <span className="faint"> (상쇄 {s.offsetting})</span> : null}</td>
          <td className="mono">{fmt1(r.max_abs)}%</td></tr>)}</tbody>
      </table>
      <div className="faint" style={{ fontSize: 12, marginTop: 6 }}>한 구성만 보정했을 때 total 오차가 커지면, 지금 total이 맞아 보이는 것은 구성 오차의 상쇄입니다. 구성은 함께 보정하고, 남는 잔차(최대 |Δ|)는 scenario별 원인으로 봅니다. 계수 확정은 아래 <b>Power fit</b> 카드에서 합니다.</div>
    </div>
  )
}

const MATRIX_SORTS: { k: MatrixSort; label: string }[] = [
  { k: 'group', label: '그룹순' }, { k: 'total', label: '|Total Δ| 큰 순' }, { k: 'worst', label: '구성 최대 |Δ| 큰 순' }, { k: 'mw', label: '|ΔmW| 합 큰 순' },
]

/** CAL-03: variant × category heatmap; row click = measurement detail. */
export function ErrorMatrix({ rows, sort, setSort, selected, onPick }: {
  rows: SummaryRow[]; sort: MatrixSort; setSort: (s: MatrixSort) => void; selected?: string; onPick: (r: SummaryRow) => void
}) {
  const sorted = useMemo(() => sortRows(rows, sort), [rows, sort])
  const cell = (v: number | null | undefined) => <td className={`mono cal-cell e-${band(v) || 'na'}`}>{v === null || v === undefined ? '미모델' : pctS(v)}</td>
  const med = (rs: SummaryRow[], k: BiasCat) => {
    const vs = rs.map((r) => r.delta_pct?.[k]).filter((v): v is number => v !== null && v !== undefined).sort((a, b) => a - b)
    if (!vs.length) return '—'
    const m = vs.length % 2 ? vs[(vs.length - 1) / 2] : (vs[vs.length / 2 - 1] + vs[vs.length / 2]) / 2
    return pctS(m)
  }
  const line = (r: SummaryRow) => (
    <tr key={r.measurement_id} className={r.measurement_id === selected ? 'selected' : ''} onClick={() => onPick(r)} tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPick(r) } }} style={{ cursor: 'pointer' }}>
      <td className="mono cal-mx-v">{short(r.variant_id)}
        {r.fit?.offsetting && <span className="offset-flag">상쇄</span>}
        {r.synthetic ? <span className="badge v-warn" style={{ marginLeft: 4 }}>합성</span> : r.origin === 'physical_capture' ? <span className="badge cov-meas" style={{ marginLeft: 4 }}>실측</span> : <span className="badge" style={{ marginLeft: 4 }}>출처 미상</span>}
        {r.captures > 1 && <span className="faint" title="같은 variant의 capture 수 (대표 1개만 표시)"> ×{r.captures}</span>}</td>
      <td className="mono">{fmt1(r.meas.total)}</td><td className="mono">{fmt1(r.pred?.total)}</td>
      {cell(r.delta_pct?.total)}{cell(r.delta_pct?.cpu)}{cell(r.delta_pct?.ip)}{cell(r.delta_pct?.bw)}
      <td className="mono">{fmt1(r.meas.other)}</td><td className="mono">{absGapMw(r)?.toFixed(0) ?? '—'}</td>
      <td className="mono">{r.fps === null ? '—' : r.fps.toFixed(0)}</td>
    </tr>)
  const body: JSX.Element[] = []
  if (sort === 'group') {
    for (const g of GROUPS) {
      const rs = sorted.filter((r) => groupOf(r.variant_id, r.fps) === g)
      if (!rs.length) continue
      body.push(<tr key={`g-${g}`} className="cal-mx-grp"><td colSpan={10}>{g} · {rs.length} variant · median Total {med(rs, 'total')} · CPU {med(rs, 'cpu')} · IP {med(rs, 'ip')} · BW {med(rs, 'bw')}</td></tr>)
      rs.forEach((r) => body.push(line(r)))
    }
  } else sorted.forEach((r) => body.push(line(r)))
  return (
    <div>
      <div className="seg sm" role="group" aria-label="matrix 정렬" style={{ marginBottom: 8 }}>
        {MATRIX_SORTS.map((s) => <button key={s.k} className={sort === s.k ? 'on' : ''} onClick={() => setSort(s.k)}>{s.label}</button>)}
      </div>
      <div className="cal-mx-wrap">
        <table className="cal-mx">
          <thead><tr><th>variant</th><th>실측 mW</th><th>예측 mW</th><th>Total Δ</th><th>CPU Δ</th><th>IP Δ</th><th>BW Δ</th><th title="scenario power model 밖 rail (GPU · SRAM · ICPU …)">미모델 mW</th><th title="|CPU| + |IP| + |BW| 차이 + 미모델 — total이 숨길 수 있는 오차">|ΔmW| 합</th><th>fps</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </div>
  )
}

/** CAL-07: per-category parity (predicted vs measured mW) with ±10 / ±25 % wedges. */
export function ParityGrid({ rows }: { rows: SummaryRow[] }) {
  const tip = useTip()
  const rs = rows.filter((r) => r.pred)
  if (!rs.length) return null
  return (
    <div className="cal-parity">
      {BIAS_CATS.map((c) => {
        const pts = rs.map((r) => ({ r, m: c.k === 'total' ? r.meas.total : r.meas[c.k], p: c.k === 'total' ? r.pred!.total : r.pred![c.k] }))
          .filter((x): x is { r: SummaryRow; m: number; p: number } => x.m !== null && x.p !== null)
        const W = 220, H = 210, l = 40, r = 8, t = 20, b = 30
        const mx = Math.max(1, ...pts.flatMap((x) => [x.m, x.p])) * 1.06
        const nice = mx > 1500 ? 500 : mx > 600 ? 200 : mx > 200 ? 100 : 50
        const top = Math.ceil(mx / nice) * nice
        const X = (v: number) => l + (v / top) * (W - l - r)
        const Y = (v: number) => t + (1 - v / top) * (H - t - b)
        const wedge = (k: number) => [[0, 0], [top / (1 + k), top], [top, top], [top, top * (1 - k)]].map(([a, bb]) => `${X(a)},${Y(bb)}`).join(' ')
        const vals = rs.map((x) => x.delta_pct?.[c.k]).filter((v): v is number => v !== null && v !== undefined).sort((a, z) => a - z)
        const med = vals.length ? (vals.length % 2 ? vals[(vals.length - 1) / 2] : (vals[vals.length / 2 - 1] + vals[vals.length / 2]) / 2) : null
        return (
          <svg key={c.k} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${c.label} 예측 vs 실측`}>
            <polygon points={wedge(0.25)} fill="#FBF0DA" /><polygon points={wedge(0.1)} fill="#E1EEEA" />
            <line x1={X(0)} y1={Y(0)} x2={X(top)} y2={Y(top)} stroke="#8A8274" />
            <line x1={X(0)} y1={Y(0)} x2={X(top)} y2={Y(0)} stroke="#DED8CF" /><line x1={X(0)} y1={Y(0)} x2={X(0)} y2={Y(top)} stroke="#DED8CF" />
            <text x={l} y={13} fontSize={12} fontWeight={600} fill="#1F2430">{c.label}</text>
            <text x={W - r} y={13} fontSize={10.5} textAnchor="end" className="mono" fill="#6B6558">median {pctS(med)}</text>
            <text x={X(0)} y={Y(0) + 13} fontSize={10} textAnchor="middle" fill="#6B6558">0</text>
            <text x={X(top)} y={Y(0) + 13} fontSize={10} textAnchor="end" className="mono" fill="#6B6558">{top}</text>
            <text x={X(0) - 4} y={Y(top) + 4} fontSize={10} textAnchor="end" className="mono" fill="#6B6558">{top}</text>
            <text x={(X(0) + X(top)) / 2} y={H - 6} fontSize={10} textAnchor="middle" fill="#6B6558">실측 mW</text>
            <text x={11} y={(Y(0) + Y(top)) / 2} fontSize={10} textAnchor="middle" fill="#6B6558" transform={`rotate(-90 11 ${(Y(0) + Y(top)) / 2})`}>예측 mW</text>
            {pts.map(({ r: row, m, p }) => {
              const hollow = c.k === 'total' && !!row.fit?.offsetting
              return <circle key={row.measurement_id} cx={X(m)} cy={Y(p)} r={hollow ? 3.6 : 3.2} fill={hollow ? '#fff' : c.color} fillOpacity={hollow ? 1 : 0.8}
                stroke={hollow ? c.color : '#fff'} strokeWidth={hollow ? 1.6 : 0.8}
                {...tip({ title: short(row.variant_id), color: c.color, head: { label: `${c.label} Δ`, value: pctS(row.delta_pct?.[c.k]) },
                  rows: [{ k: '예측', v: `${p.toFixed(1)} mW` }, { k: '실측', v: `${m.toFixed(1)} mW` }], foot: hollow ? 'total 일치 · 구성 상쇄' : undefined })} />
            })}
          </svg>)
      })}
    </div>
  )
}

/** CAL-04: registered prediction → category gaps → measured total. */
export function ErrorWaterfall({ d }: { d: MeasDetail }) {
  const [ref, w] = useWidth<HTMLDivElement>(560)
  const tip = useTip()
  const wf = waterfall(d)
  if (!wf) return <div className="empty">등록 예측(구성 split)이 없어 waterfall을 그릴 수 없습니다.</div>
  const H = 250, left = 46, right = 10, top = 22, bottom = 34
  const hi = Math.max(...wf.steps.map((s) => Math.max(s.from, s.to))) * 1.12
  const step = hi > 1200 ? 400 : hi > 600 ? 200 : hi > 250 ? 100 : 50
  const Y = (v: number) => top + (1 - v / hi) * (H - top - bottom)
  const bw = (w - left - right) / wf.steps.length
  const color = (c: string) => (c === 'total' ? '#4A5160' : CAT_COLOR[c as 'cpu'])
  const gridTicks: number[] = []
  for (let t = 0; t <= hi; t += step) gridTicks.push(t)
  const cur = d.predictions.find((p) => p.kind === 'current')
  const total = d.total.mean ?? 0
  const diff = total - (cur?.total_mw ?? 0)
  return (
    <div ref={ref}>
      <svg width={w} height={H} role="img" aria-label="예측에서 실측까지 구성별 차이">
        {gridTicks.map((t) => <g key={t}><line x1={left} x2={w - right} y1={Y(t)} y2={Y(t)} stroke="#EFEAE2" />
          <text x={left - 6} y={Y(t) + 4} fontSize={10.5} textAnchor="end" className="mono" fill="#6B6558">{t}</text></g>)}
        {wf.steps.map((s, i) => {
          const x = left + i * bw + bw * 0.18, bwid = bw * 0.64
          const yA = Y(Math.max(s.from, s.to)), yB = Y(Math.min(s.from, s.to))
          const neg = s.kind === 'delta' && s.value < 0
          return <g key={s.label}>
            <rect x={x} y={yA} width={bwid} height={Math.max(1.5, yB - yA)} rx={3} fill={color(s.cat)} fillOpacity={neg ? 0.45 : 1}
              stroke={neg ? color(s.cat) : 'none'} strokeDasharray={neg ? '4 2' : undefined}
              {...tip({ title: s.label, color: color(s.cat), head: { label: s.kind === 'total' ? 'total' : '실측 − 예측', value: s.kind === 'total' ? `${s.value.toFixed(1)} mW` : `${signed(s.value)} mW` } })} />
            <text x={x + bwid / 2} y={yA - 5} fontSize={11} textAnchor="middle" className="mono" fill="#1F2430">{s.kind === 'total' ? s.value.toFixed(1) : signed(s.value)}</text>
            <text x={x + bwid / 2} y={H - bottom + 15} fontSize={11} textAnchor="middle" fill="#3B3F4A">{s.label}</text>
            {i < wf.steps.length - 1 && <line x1={x + bwid} x2={x + bw} y1={Y(s.to)} y2={Y(s.to)} stroke="#8A8274" strokeDasharray="2 2" />}
          </g>
        })}
      </svg>
      <div className="faint" style={{ fontSize: 12 }}>구성 차이의 절대값 합 <b className="mono">{wf.gapAbs.toFixed(0)} mW</b> 중 <b className="mono">{(wf.offsetShare * 100).toFixed(0)}%</b>가 서로 상쇄되어 total 차이는 <b className="mono">{signed(diff, 0)} mW</b>로 보입니다.{wf.offsetShare > 0.5 ? ' total 일치만으로 모델을 믿을 수 없는 경우입니다.' : ''}</div>
    </div>
  )
}
