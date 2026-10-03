// Pipeline Timing "예측 ↔ 실측" view.
import { useMemo, useState } from 'react'
import type { Evidence, ViewResponse } from '../lib/api'
import { buildTimeline } from '../lib/timeline'
import { evidenceSource } from '../lib/conditions'
import { compareTimelines, errTone, factorJson, type IpDelta } from '../lib/timingCompare'
import { fmt } from '../lib/timingBudget'
import { useTip } from './ChartTip'
import { useWidth } from './Charts'

const f2 = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? '—' : fmt(v, d))
const sg = (v: number | null, d = 2) => (v === null ? '—' : `${v >= 0 ? '+' : ''}${fmt(v, d)}`)

function Overlay({ ips, period }: { ips: IpDelta[]; period: number | null }) {
  const [ref, width] = useWidth<HTMLDivElement>(600)
  const tip = useTip()
  const rows = ips.filter((d) => d.a || d.b)
  const end = Math.max(1, ...rows.map((d) => Math.max((d.a?.offset ?? 0) + (d.a?.dur ?? 0), (d.b?.offset ?? 0) + (d.b?.dur ?? 0))))
  const L = 92, RH = 18, W = Math.max(200, width - L - 10)
  const x = (t: number) => L + (t / end) * W
  return (
    <div ref={ref} style={{ width: '100%' }}>
      <div className="legend-row"><span className="legend-item"><svg width="22" height="10"><rect x="1" y="1" width="20" height="8" fill="none" stroke="#2563EB" strokeWidth="1.5" strokeDasharray="3 2" /></svg>예측</span>
        <span className="legend-item"><svg width="22" height="10"><rect x="1" y="1" width="20" height="8" fill="#E07B39" opacity="0.75" /></svg>실측</span>
        <span className="legend-item faint">frame 시작 기준 평균 · {period ? `┆ = 주기 ${fmt(period, 2)} ms` : ''}</span></div>
      <svg width={width} height={rows.length * RH + 22} role="img" aria-label="예측 실측 overlay">
        {period && Array.from({ length: Math.floor(end / period) + 1 }, (_, i) => <line key={i} x1={x(i * period)} x2={x(i * period)} y1={0} y2={rows.length * RH} stroke="#CFC6B8" strokeDasharray="2 3" />)}
        {rows.map((d, i) => (
          <g key={d.pid} {...tip({ title: d.pid, rows: [
            { k: '예측', v: d.a ? `+${f2(d.a.offset)} · ${f2(d.a.dur)} ms` : '—' }, { k: '실측', v: d.b ? `+${f2(d.b.offset)} · ${f2(d.b.dur)} ms (${f2(d.b.durMin)}–${f2(d.b.durMax)})` : '—' },
            { k: 'Δ 시작 / 길이', v: `${sg(d.dStart)} / ${sg(d.dDur)} ms`, tone: d.dDur !== null && d.dDur > 0 ? 'bad' : 'good' }, { k: 'Δ%', v: d.dDurPct === null ? '—' : `${sg(d.dDurPct, 1)}%` }] })}>
            <text x={L - 6} y={i * RH + 13} fontSize={10.5} textAnchor="end" fill="var(--text-2)" fontFamily="var(--mono)">{d.pid}</text>
            {d.b && <rect x={x(d.b.offset)} y={i * RH + 3} width={Math.max(1.5, x(d.b.offset + d.b.dur) - x(d.b.offset))} height={RH - 6} rx={2} fill="#E07B39" opacity={0.75} />}
            {d.a && <rect x={x(d.a.offset)} y={i * RH + 2} width={Math.max(1.5, x(d.a.offset + d.a.dur) - x(d.a.offset))} height={RH - 4} rx={2} fill="none" stroke="#2563EB" strokeWidth={1.5} strokeDasharray="3 2" />}
          </g>))}
        <text x={L} y={rows.length * RH + 15} fontSize={9.5} fill="var(--muted)">0 ms</text>
        <text x={L + W} y={rows.length * RH + 15} fontSize={9.5} textAnchor="end" fill="var(--muted)">{fmt(end, 1)} ms</text>
      </svg>
    </div>
  )
}

export function TimingCompare({ traces, view, fps, laneOfPid, onPickPid }: {
  traces: Evidence[]; view?: ViewResponse; fps: number | null; laneOfPid: (pid: string) => string | undefined; onPickPid?: (pid: string) => void
}) {
  const preds = traces.filter((t) => evidenceSource(t) === 'calculated')
  const meas = traces.filter((t) => evidenceSource(t) !== 'calculated')
  const [aId, setA] = useState(''), [bId, setB] = useState('')
  const A = preds.find((t) => t.id === aId) ?? preds[0], B = meas.find((t) => t.id === bId) ?? meas[0]
  const [copied, setCopied] = useState(false)
  const cmp = useMemo(() => (A && B ? compareTimelines(buildTimeline(A.timeline_events ?? [], { maxFrames: 16 }), buildTimeline(B.timeline_events ?? [], { maxFrames: 16 }), view, fps, laneOfPid) : null),
    [A, B, view, fps, laneOfPid])
  if (!A || !B) return <div className="empty">비교하려면 예측(simulation) trace와 실측(또는 합성) trace가 모두 필요합니다 — 예측 {preds.length}건 · 실측 {meas.length}건.</div>
  const ranked = [...(cmp?.ips ?? [])].filter((d) => d.dDurPct !== null).sort((p, q) => Math.abs(q.dDurPct!) - Math.abs(p.dDurPct!))
  return (
    <div className="tcmp">
      <div className="toolbar" style={{ gap: 8, fontSize: 12, flexWrap: 'wrap' }}>
        <span className="badge src-calculated">예측</span>
        <select aria-label="예측 trace" value={A.id} onChange={(e) => setA(e.target.value)}>{preds.map((t) => <option key={t.id} value={t.id}>{t.id}</option>)}</select>
        <span>↔</span>
        <span className={`badge src-${evidenceSource(B)}`}>{evidenceSource(B)}</span>
        <select aria-label="실측 trace" value={B.id} onChange={(e) => setB(e.target.value)}>{meas.map((t) => <option key={t.id} value={t.id}>{t.id}</option>)}</select>
        <span className="grow" />
        <button className="btn tb-mini" onClick={() => cmp && navigator.clipboard?.writeText(factorJson(cmp, { predicted: A.id, measured: B.id })).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) })}
          title="IP별 실측/예측 길이 비 — simulation profile 보정 후보">{copied ? '복사됨' : '보정계수 JSON 복사'}</button>
      </div>
      {cmp && <>
        <h4 className="cad-title">출력 stream <span className="faint">— 예측 → 실측 (Δ)</span></h4>
        <table className="tb-mini-table" style={{ width: '100%' }} aria-label="stream 비교">
          <thead><tr><th>stream</th><th style={{ textAlign: 'right' }}>fps</th><th style={{ textAlign: 'right' }}>평균 interval</th><th style={{ textAlign: 'right' }}>jitter σ</th><th style={{ textAlign: 'right' }}>평균 latency</th><th style={{ textAlign: 'right' }}>max latency</th><th style={{ textAlign: 'right' }}>drop</th></tr></thead>
          <tbody>{cmp.streams.map((s) => { const cell = (k: 'fps' | 'interval' | 'jitter' | 'latency' | 'latMax', d: number) => {
            const a = s.a?.[k] ?? null, b = s.b?.[k] ?? null
            return <td className="mono" style={{ textAlign: 'right' }}>{f2(a, d)} → <b>{f2(b, d)}</b>{a !== null && b !== null ? <span className="faint"> ({sg(b - a, d)})</span> : null}</td> }
            return <tr key={s.id}><td>{s.label}</td>{cell('fps', 2)}{cell('interval', 2)}{cell('jitter', 3)}{cell('latency', 1)}{cell('latMax', 1)}
              <td className="mono" style={{ textAlign: 'right' }}>{s.a?.drops ?? '—'} → {s.b?.drops ?? '—'}</td></tr> })}</tbody>
        </table>
        <div className="toolbar" style={{ gap: 10, fontSize: 12, margin: '8px 0', flexWrap: 'wrap' }}>
          <span className="faint">길이 합 (예측 → 실측)</span>
          {cmp.byLane.map((l) => <span key={l.lane} className="chip">{l.lane} {fmt(l.a, 1)} → {fmt(l.b, 1)} ms <b className={l.d > 0 ? 'pm-up' : 'pm-down'}>{sg(l.d, 1)}</b></span>)}
          {cmp.onlyA.length > 0 && <span className="chip" title={cmp.onlyA.join(', ')}>예측에만 {cmp.onlyA.length}</span>}
          {cmp.onlyB.length > 0 && <span className="chip" title={cmp.onlyB.join(', ')}>실측에만 {cmp.onlyB.length}</span>}
        </div>
        <h4 className="cad-title">1 frame overlay <span className="faint">— 점선 = 예측, 채움 = 실측</span></h4>
        <Overlay ips={cmp.ips} period={cmp.period} />
        <h4 className="cad-title">IP별 오차 <span className="faint">— |Δ%| 큰 순 · ±10% 녹색 · ±25% 주황 · 그 이상 빨강 · 행 클릭 = 그래프 선택</span></h4>
        <table className="tb-mini-table" style={{ width: '100%' }} aria-label="IP별 오차">
          <thead><tr><th>IP</th><th>lane</th><th style={{ textAlign: 'right' }}>예측 +start · dur</th><th style={{ textAlign: 'right' }}>실측 +start · dur</th><th style={{ textAlign: 'right' }}>Δ start</th><th style={{ textAlign: 'right' }}>Δ dur</th><th style={{ textAlign: 'right' }}>Δ%</th><th style={{ textAlign: 'right' }}>보정 ×</th></tr></thead>
          <tbody>{ranked.map((d) => <tr key={d.pid} className={onPickPid ? 'clickable' : ''} onClick={() => onPickPid?.(d.pid)}>
            <td className="mono">{d.pid}</td><td className="faint">{d.lane ?? '—'}</td>
            <td className="mono" style={{ textAlign: 'right' }}>+{f2(d.a?.offset)} · {f2(d.a?.dur)}</td>
            <td className="mono" style={{ textAlign: 'right' }}>+{f2(d.b?.offset)} · {f2(d.b?.dur)}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{sg(d.dStart)}</td><td className="mono" style={{ textAlign: 'right' }}>{sg(d.dDur)}</td>
            <td style={{ textAlign: 'right' }}><span className={`badge ${errTone(d.dDurPct)}`}>{sg(d.dDurPct, 1)}%</span></td>
            <td className="mono" style={{ textAlign: 'right' }}>{f2(d.factor, 3)}</td></tr>)}</tbody>
        </table>
      </>}
    </div>
  )
}
