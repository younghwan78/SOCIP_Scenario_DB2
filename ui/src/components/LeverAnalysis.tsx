// 조합 탐색 · Lever 분석 (engine rev ≥ 11)
//   Q1 화질 손해 없이 얼마나 줄이나, 무엇이 제일 효과적인가 → milestone tiles + IQ-first path (waterfall)
//   Q2 knob별 효과 → lever table: 단독 Δ (baseline 대비) vs 최종 조합 안에서의 Δ (중첩 · 무효화 표시)
//   Q3 power 분포 → every design point (option set × compression choice) on one mW axis, by IQ class,
//      with the SW-condition band (statistic × growth = 불확실성, knob 아님) and the measured total.
import { Fragment, useMemo, useState } from 'react'
import { LeverSelect, lookupPoint, milestoneSelection, type Selection } from './LeverSelect'
import { useWidth } from './Charts'
import { useTip } from './ChartTip'
import { fmt } from '../lib/timingBudget'
import { IQ_COLOR, IQ_LABEL, PCOL, type IqClass, type LeverAnalysis, type LeverDelta, type LeverPoint, type LeverRow, type LeverStep } from '../lib/archExplore'
import { maText, type Battery } from '../lib/battery'

const PHASES: IqClass[] = ['neutral', 'eval', 'trade']
const signed = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${fmt(v, d)}`)
const shortMode = (m: string) => (m.toUpperCase().endsWith('LOSSLESS') ? 'lossless' : m.toUpperCase().endsWith('LOSSY') ? 'lossy' : m)

export interface Measured { total_mw: number; label: string }

export interface RegisterCtx { runId: string; scenarioId: string; variantId: string; projectRef?: string | null; readOnly: boolean }

export function LeverAnalysisView({ la, battery, measured, reg }: { la: LeverAnalysis | undefined; battery: Battery; measured?: Measured | null; reg?: RegisterCtx }) {
  if (!la || la.status !== 'ok' || !la.baseline) {
    return <div className="empty">이 run에는 lever 분석이 없습니다 (engine rev 11 이후 다시 탐색하면 표시).</div>
  }
  return <LeverBody la={la} battery={battery} measured={measured} reg={reg} />
}

function LeverBody({ la, battery, measured, reg }: { la: LeverAnalysis; battery: Battery; measured?: Measured | null; reg?: RegisterCtx }) {
  const [sel, setSel] = useState<Selection>(() => milestoneSelection(la, 'neutral'))
  const picked = lookupPoint(la.points ?? [], sel).point
  const base = la.baseline!
  const ms = la.milestones ?? {}
  const levers = la.levers ?? []
  const best = (c: IqClass) => levers.find((l) => l.key === la.best_lever?.[c])
  return (
    <div className="lever">
      <div className="lever-tiles">
        <Tile title="baseline" sub="변경 없음 · 현재 DVFS" mw={base.total_mw} bw={base.bw_mbs} battery={battery} />
        {PHASES.map((c) => ms[c] && <Tile key={c} title={c === 'neutral' ? IQ_LABEL.neutral + ' 최적' : `+ ${IQ_LABEL[c]}`} color={IQ_COLOR[c]}
          mw={ms[c]!.total_mw} bw={ms[c]!.bw_mbs} delta={ms[c]!.delta_mw} pct={ms[c]!.delta_pct} battery={battery}
          sub={describe(ms[c]!.options, ms[c]!.compression)} />)}
        {measured && <Tile title="실측" sub={measured.label} mw={measured.total_mw} battery={battery} dashed />}
      </div>
      <ul className="lever-answer">
        <li><b>화질 손해 없이</b>: {ms.neutral && ms.neutral.delta_mw < -0.05
          ? <>baseline 대비 <b className="mono">{signed(ms.neutral.delta_mw)} mW</b> ({signed(ms.neutral.delta_pct)}%, {maText(ms.neutral.delta_mw, battery, true)}) — 가장 효과적인 단일 lever는 <b>{best('neutral')?.label ?? '—'}</b> ({signed(best('neutral')?.alone?.total_mw)} mW)</>
          : <>줄일 수 있는 무손실 lever가 없습니다 (lossless 지원 DMA 없음).</>}</li>
        {best('eval') && <li><b>IQ 평가가 필요한 lever</b> 중 단독 효과 최대: <b>{best('eval')!.label}</b> ({signed(best('eval')!.alone?.total_mw)} mW) — 채택 전 화질 평가 필요</li>}
        {ms.trade && ms.eval && ms.trade.total_mw < ms.eval.total_mw - 0.05 && <li><b>lossy까지 허용</b>하면 추가 {signed(ms.trade.total_mw - ms.eval.total_mw)} mW</li>}
        {levers.some((l) => l.moot || l.overlap) && <li className="faint">중첩: {levers.filter((l) => l.moot || l.overlap).map((l) => l.label).join(', ')} — 같은 traffic을 줄이는 lever라 함께 쓰면 단독 효과의 합보다 작습니다.</li>}
      </ul>
      {reg && (la.points ?? []).some((p) => p.option_keys) && <LeverSelect la={la} battery={battery} sel={sel} setSel={setSel} {...reg} />}
      <div className="lever-grid">
        <section>
          <h4>IQ 우선 경로 <span className="faint">(각 단계 = 남은 lever 중 가장 큰 절감 · 무손실 → IQ 평가 → lossy)</span></h4>
          <PathChart steps={la.steps ?? []} />
        </section>
        <section>
          <h4>Power 분포 <span className="faint">({la.point_count ?? 0}개 설계 조합 · SW {la.basis?.statistic} ×{la.basis?.runtime_scale} · DVFS 해석 level)</span></h4>
          <Distribution la={la} measured={measured} picked={picked} />
        </section>
      </div>
      <h4 style={{ margin: '10px 0 4px' }}>Lever별 효과 <span className="faint">(단독 = baseline에 이것만 · 최종 조합 내 = 경로 끝에서 on/off)</span></h4>
      <LeverTable levers={levers} battery={battery} chosen={chosenKeys(la)} />
      {(la.costs ?? []).length > 0 && <div className="faint" style={{ fontSize: 12, marginTop: 6 }}>
        비용 lever (성능 여유용, 절감 아님): {(la.costs ?? []).map((c) => `${c.label} ${signed(c.delta_mw, 1)} mW`).join(' · ')}
        {(la.costs ?? []).some((c) => Math.abs(c.delta_mw) < 0.05) && ' · 0 mW = 같은 rail(VDD)을 다른 IP가 더 높은 전압으로 잡고 있음'}</div>}
    </div>
  )
}

function describe(options: string[], comp: Record<string, string>): string {
  const c = Object.entries(comp).map(([b, m]) => `${b} ${shortMode(m)}`)
  return [...options.map((o) => o.replace(/: [^:]+$/, '')), ...c].join(' · ') || '—'
}

function Tile({ title, sub, mw, bw, delta, pct, battery, color, dashed }: {
  title: string; sub: string; mw: number; bw?: number; delta?: number; pct?: number | null; battery: Battery; color?: string; dashed?: boolean
}) {
  return (
    <div className="lever-tile" style={{ borderTopColor: color ?? '#4A5160', borderTopStyle: dashed ? 'dashed' : 'solid' }}>
      <div className="lever-tile-h">{title}</div>
      <div><span className="mono lever-tile-v">{fmt(mw, 1)}</span> mW <span className="faint">{maText(mw, battery)}</span></div>
      {delta !== undefined && <div className="mono" style={{ color: delta < 0 ? 'var(--primary-strong)' : 'var(--del-text)', fontSize: 12 }}>{signed(delta)} mW ({signed(pct)}%)</div>}
      {bw !== undefined && <div className="faint mono" style={{ fontSize: 11 }}>{fmt(bw / 1000, 2)} GB/s</div>}
      <div className="faint" style={{ fontSize: 11, lineHeight: 1.3 }} title={sub}>{sub}</div>
    </div>
  )
}

interface Row { label: string; start: number; end: number; kind: 'total' | IqClass; note?: string }

export function pathRows(steps: LeverStep[]): Row[] {
  if (!steps.length) return []
  const rows: Row[] = [{ label: 'baseline', start: 0, end: steps[0].total_mw, kind: 'total' }]
  let prev = steps[0].total_mw
  for (const [i, s] of steps.slice(1).entries()) {
    rows.push({ label: s.label, start: prev, end: s.total_mw, kind: s.iq, note: s.dropped?.length ? `${s.dropped.join(', ')} 압축 무효` : undefined })
    prev = s.total_mw
    const next = steps[i + 2]
    if (!next || next.phase !== s.phase) rows.push({ label: s.phase === 'neutral' ? '= 화질 무손실 최적' : s.phase === 'eval' ? '= + IQ 평가 lever' : '= + lossy', start: 0, end: prev, kind: 'total' })
  }
  return rows
}

function PathChart({ steps }: { steps: LeverStep[] }) {
  const [ref, w] = useWidth<HTMLDivElement>(560)
  const rows = pathRows(steps)
  if (!rows.length) return <div className="empty">경로 없음</div>
  const labelW = 190, valW = 64, rh = 21
  const plotW = Math.max(140, w - labelW - valW)
  const vals = rows.flatMap((r) => (r.kind === 'total' ? [r.end] : [r.start, r.end]))
  const lo = Math.min(...vals), hi = Math.max(...vals)
  const pad = (hi - lo) * 0.12 || 1
  const x0 = Math.max(0, lo - pad), x1 = hi + pad * 0.3
  const X = (v: number) => labelW + ((Math.max(v, x0) - x0) / (x1 - x0)) * plotW
  // a row with a note (e.g. "L0 압축 무효") gets an extra line under its bar
  const ys = rows.reduce<number[]>((acc, _r, i) => [...acc, i === 0 ? 0 : acc[i - 1] + rh + (rows[i - 1].note ? 12 : 0)], [])
  const height = ys[ys.length - 1] + rh + (rows[rows.length - 1].note ? 12 : 0) + 4
  return (
    <div ref={ref}>
      <svg width={labelW + plotW + valW} height={height} role="img" aria-label="IQ-first lever path">
        {rows.map((r, i) => {
          const total = r.kind === 'total'
          const a = total ? x0 : r.start, b = r.end
          const xa = X(Math.min(a, b)), xb = X(Math.max(a, b))
          const col = total ? '#4A5160' : IQ_COLOR[r.kind as IqClass]
          return (
            <g key={`${r.label}${i}`} transform={`translate(0,${ys[i]})`}>
              <title>{total ? `${r.label} ${fmt(r.end, 1)} mW` : `${IQ_LABEL[r.kind as IqClass]} · ${r.label} ${signed(r.end - r.start, 2)} mW → ${fmt(r.end, 1)} mW${r.note ? ` · ${r.note}` : ''}`}</title>
              <text x={labelW - 6} y={14} fontSize={11} textAnchor="end" fill="#3B3F4A" fontWeight={total ? 600 : 400}>{r.label.length > 28 ? `${r.label.slice(0, 27)}…` : r.label}</text>
              <rect x={xa} y={4} width={Math.max(1.5, xb - xa)} height={13} fill={col} fillOpacity={total ? 0.75 : 0.85} />
              {!total && i > 0 && <line x1={X(r.start)} x2={X(r.start)} y1={ys[i - 1] - ys[i] + 17} y2={4} stroke="#B9B2A6" strokeDasharray="2 2" />}
              <text x={labelW + plotW + 6} y={14} fontSize={11} className="mono" fill={total ? '#3B3F4A' : r.end < r.start ? '#174D47' : '#7F1D1D'}>
                {total ? fmt(r.end, 1) : signed(r.end - r.start, 1)}</text>
              {r.note && <text x={labelW - 6} y={rh + 7} fontSize={10} fill="#8A8274" textAnchor="end">↳ {r.note}</text>}
            </g>
          )
        })}
      </svg>
      <div className="legend-row">{PHASES.map((c) => <span key={c} className="legend-item"><span style={{ width: 10, height: 10, background: IQ_COLOR[c] }} />{IQ_LABEL[c]}</span>)}</div>
    </div>
  )
}

function Distribution({ la, measured, picked }: { la: LeverAnalysis; measured?: Measured | null; picked?: LeverPoint | null }) {
  const [ref, w] = useWidth<HTMLDivElement>(560)
  const tip = useTip()
  const pts = la.points ?? []
  const base = la.baseline!.total_mw
  const band = la.basis?.sw_band_mw ?? null
  const lanes = PHASES.filter((c) => pts.some((p) => p.iq === c))
  const labelW = 112, padR = 16, laneH = 34, top = 18
  const plotW = Math.max(160, w - labelW - padR)
  const vals = [...pts.map((p) => p.total_mw), base, ...(band ? [base + band[0], base + band[1]] : []), ...(measured ? [measured.total_mw] : [])]
  const lo = Math.min(...vals), hi = Math.max(...vals)
  const pad = (hi - lo) * 0.06 || 1
  const x0 = lo - pad, x1 = hi + pad
  const X = (v: number) => labelW + ((v - x0) / (x1 - x0)) * plotW
  const h = top + lanes.length * laneH + 22
  const ticks = useMemo(() => {
    const step = [1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 250, 500].find((s) => (x1 - x0) / s <= 7) ?? 500
    const out: number[] = []
    for (let t = Math.ceil(x0 / step) * step; t <= x1; t += step) out.push(t)
    return out
  }, [x0, x1])
  const laneY = (c: IqClass) => top + lanes.indexOf(c) * laneH
  return (
    <div ref={ref}>
      <svg width={labelW + plotW + padR} height={h} role="img" aria-label="design-space power distribution">
        {band && <g>
          <rect x={X(base + band[0])} y={top - 4} width={Math.max(1, X(base + band[1]) - X(base + band[0]))} height={lanes.length * laneH + 4} fill="#E9E4DA" opacity={0.7} />
          <text x={Math.min(X(base + band[0]) + 3, labelW + plotW - 4)} y={top - 7} fontSize={9.5} fill="#8A8274"
            textAnchor={X(base + band[0]) + 150 > labelW + plotW ? 'end' : 'start'}>SW 불확실성 (stat × growth)</text>
        </g>}
        {ticks.map((t) => <g key={t}><line x1={X(t)} x2={X(t)} y1={top - 4} y2={top + lanes.length * laneH} stroke="#EFEAE1" />
          <text x={X(t)} y={h - 6} fontSize={10} fill="#8A8274" textAnchor="middle">{fmt(t, 0)}</text></g>)}
        {lanes.map((c) => <g key={c}>
          <text x={labelW - 8} y={laneY(c) + laneH / 2 + 3} fontSize={11} textAnchor="end" fill={IQ_COLOR[c]} fontWeight={600}>{IQ_LABEL[c]}</text>
          <line x1={labelW} x2={labelW + plotW} y1={laneY(c) + laneH} y2={laneY(c) + laneH} stroke="#F3EFE8" />
        </g>)}
        {pts.map((p, i) => {
          const jitter = ((i * 37) % 11) / 10 - 0.5
          const cy = laneY(p.iq) + laneH / 2 + jitter * (laneH - 14)
          return <circle key={i} cx={X(p.total_mw)} cy={cy} r={4.2} fill={IQ_COLOR[p.iq]} fillOpacity={0.55} stroke={IQ_COLOR[p.iq]} strokeWidth={0.8}
            {...tip({ title: `${fmt(p.total_mw, 1)} mW`, color: IQ_COLOR[p.iq],
              head: { label: 'baseline 대비', value: `${signed(p.total_mw - base)} mW`, tone: p.total_mw < base ? 'good' : 'bad' },
              rows: [{ k: 'option', v: p.options.join(', ') || '—' },
                     { k: 'compression', v: Object.entries(p.comp).map(([b, m]) => `${b} ${shortMode(m)}`).join(', ') || '—' },
                     { k: 'CPU / IP / BW', v: `${fmt(p.cpu_mw, 0)} / ${fmt(p.hw_mw, 0)} / ${fmt(p.bw_mw, 0)} mW` },
                     { k: 'DRAM BW', v: `${fmt(p.bw_mbs / 1000, 2)} GB/s` }] })} />
        })}
        {picked && lanes.includes(picked.iq) && <g pointerEvents="none">
          <circle cx={X(picked.total_mw)} cy={laneY(picked.iq) + laneH / 2} r={9} fill="none" stroke="#1F2430" strokeWidth={2} />
          <text x={X(picked.total_mw)} y={laneY(picked.iq) + 6} fontSize={10} fill="#1F2430" textAnchor="middle" fontWeight={600}>선택</text>
        </g>}
        <line x1={X(base)} x2={X(base)} y1={top - 4} y2={top + lanes.length * laneH} stroke="#3B3F4A" strokeWidth={1.5} />
        <text x={X(base) + 3} y={top + lanes.length * laneH - 3} fontSize={10} fill="#3B3F4A">baseline</text>
        {measured && <g><line x1={X(measured.total_mw)} x2={X(measured.total_mw)} y1={top - 4} y2={top + lanes.length * laneH} stroke="#2563EB" strokeWidth={1.5} strokeDasharray="4 3" />
          <text x={X(measured.total_mw) - 3} y={top + 9} fontSize={10} fill="#2563EB" textAnchor="end">실측</text></g>}
      </svg>
      <div className="faint" style={{ fontSize: 11 }}>점 = option 조합 × buffer별 압축(off · lossless · lossy). 회색 띠 = 같은 설계에서 SW 통계·증가율만 바뀔 때의 폭 (설계 선택이 아님).</div>
    </div>
  )
}

/** Levers in the IQ-keeping end state (neutral + eval path) and the lossy ones the trade step adds. */
export function chosenKeys(la: LeverAnalysis): Set<string> {
  const out = new Set<string>()
  const keep = la.milestones?.eval ?? la.milestones?.neutral
  for (const l of la.levers ?? []) {
    const ms = l.iq === 'trade' ? la.milestones?.trade : keep
    if (!ms) continue
    if (l.kind === 'compression' ? ms.compression[l.buffer ?? ''] === l.mode : ms.options.includes(l.label)) out.add(l.key)
  }
  return out
}

const CONF: Record<string, string> = { typical: 'typical ratio (SAMPLE)', catalog: 'catalog ratio', assumed: '가정 ratio', override: 'override', synthetic: 'synthetic mode', model: 'model' }

function SplitDelta({ d }: { d: LeverDelta | null }) {
  if (!d) return <span className="faint">—</span>
  const parts: [string, number, string][] = [['CPU', d.cpu_mw, PCOL.cpu], ['IP', d.hw_mw, PCOL.hw], ['BW', d.bw_mw, PCOL.bw]]
  return <span className="mono" style={{ fontSize: 11 }}>{parts.filter(([, v]) => Math.abs(v) >= 0.05).map(([k, v, c]) =>
    <span key={k} style={{ marginRight: 6 }}><span style={{ display: 'inline-block', width: 7, height: 7, background: c, marginRight: 2 }} />{k} {signed(v)}</span>)}</span>
}

function LeverTable({ levers, battery, chosen }: { levers: LeverRow[]; battery: Battery; chosen: Set<string> }) {
  const maxAbs = Math.max(1, ...levers.map((l) => Math.abs(l.alone?.total_mw ?? 0)))
  return (
    <table className="tb-mini-table lever-table" style={{ width: '100%' }}>
      <thead><tr><th>Lever</th><th style={{ textAlign: 'right' }}>단독 Δ mW</th><th style={{ width: 120 }} /><th style={{ textAlign: 'right' }}>mA</th>
        <th style={{ textAlign: 'right' }}>BW MB/s</th><th>성분</th><th style={{ textAlign: 'right' }} title="경로 끝 조합에서 이 lever를 켰을 때 vs 껐을 때">최종 조합 내 Δ</th><th>근거</th></tr></thead>
      <tbody>{PHASES.map((c) => {
        const rows = levers.filter((l) => l.iq === c)
        if (!rows.length) return null
        return <Fragment key={c}>
          <tr className="lever-group"><td colSpan={8} style={{ color: IQ_COLOR[c] }}>{IQ_LABEL[c]}</td></tr>
          {rows.map((l) => {
            const a = l.alone?.total_mw ?? 0
            return (
              <tr key={l.key}>
                <td>{l.label}{chosen.has(l.key) && <span className="badge v-ok" style={{ marginLeft: 4 }} title={l.iq === 'trade' ? 'lossy 단계에서 선택' : 'IQ 우선 경로(무손실 + IQ 평가 lever)의 끝 조합에 포함'}>선택</span>}</td>
                <td className="mono" style={{ textAlign: 'right', color: a < 0 ? 'var(--primary-strong)' : undefined }}>{signed(l.alone?.total_mw)}</td>
                <td><svg width={120} height={10}><rect width={120} height={10} fill="#F3EFE8" /><rect x={120 - (Math.abs(a) / maxAbs) * 120} width={(Math.abs(a) / maxAbs) * 120} height={10} fill={IQ_COLOR[c]} fillOpacity={0.7} /></svg></td>
                <td className="mono faint" style={{ textAlign: 'right' }}>{l.alone ? maText(l.alone.total_mw, battery, true) : '—'}</td>
                <td className="mono" style={{ textAlign: 'right' }}>{signed(l.alone?.bw_mbs, 0)}</td>
                <td><SplitDelta d={l.alone} /></td>
                <td className="mono" style={{ textAlign: 'right' }}>{l.moot ? <span className="badge v-info" title="최종 조합의 option이 이 buffer를 없앰 (예: L0 skip)">무효</span> : signed(l.in_context?.total_mw)}
                  {l.overlap && !l.moot && <span className="badge v-warn" style={{ marginLeft: 4 }} title="다른 lever와 같은 traffic/연산을 줄임 — 단독 효과보다 작음">중첩</span>}</td>
                <td className="faint" style={{ fontSize: 11 }} title={l.note ?? undefined}>{CONF[l.confidence] ?? l.confidence}</td>
              </tr>)
          })}
        </Fragment>
      })}</tbody>
    </table>
  )
}
