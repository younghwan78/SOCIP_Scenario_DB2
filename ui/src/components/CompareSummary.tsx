// Compare page: decision summary vs the reference (★) — Power / BW / Latency first.
import type { ReactNode } from 'react'
import { useTip, type TipRow } from './ChartTip'
import { DEFAULT_BATTERY, batteryNote, deltaMaText, maText, sameBattery, type Battery } from '../lib/battery'

export type MetricGroup = 'Power' | 'BW' | 'Latency · Timing'
export interface MetricRow {
  group: MetricGroup; key: string; label: string; unit: string; digits?: number
  values: (number | null)[]
  /** false for fps-like metrics (higher is better) */
  lowerIsBetter?: boolean
  /** relative change below this (%) counts as "같음" */
  tolerancePct?: number
  hint?: string
  /** where each column's value comes from; a Δ between different sources is not shown */
  sources?: (string | null)[]
  /** text for a column without a value (e.g. '미모델'), instead of '—' */
  blank?: (string | null)[]
}

/** Δ vs ★ is meaningful only when both values come from the same source (model / measurement). */
export function sameSource(m: Pick<MetricRow, 'sources'>, i: number): boolean {
  const a = m.sources?.[0], b = m.sources?.[i]
  return !a || !b || a === b
}
export interface ItemInfo {
  label: string; full?: string; color: string; source: string | null
  changed?: { conditions: number; ips: number; sizes: number }
  /** biggest contributors to the change vs ★ (power parts in mW, DMA traffic per IP in MB/s) */
  drivers?: Driver[]
  status?: ReactNode
}

export interface Driver { kind: 'power' | 'bw'; label: string; delta: number; unit: 'mW' | 'MB/s' }

/** 주요 원인: one line per contributor — direction, name, signed Δ (+ mA for power), bar ∝ |Δ| within its kind. */
function Drivers({ list, battery, mixed }: { list: Driver[]; battery: Battery; mixed: boolean }) {
  const maxOf = (k: Driver['kind']) => Math.max(1e-9, ...list.filter((d) => d.kind === k).map((d) => Math.abs(d.delta)))
  return <div className="cs-why">
    <b>주요 원인</b>
    <table className="cs-drv"><tbody>{list.map((d) => {
      const up = d.delta > 0
      return <tr key={`${d.kind}${d.label}`}>
        <td className="cs-drv-k">{d.kind === 'power' ? 'Power' : 'DMA'}</td>
        <td className="cs-drv-l" title={d.label}>{d.label}</td>
        <td className={`mono cs-drv-v ${up ? 't-bad' : 't-good'}`}>{up ? '▲' : '▼'} {up ? '+' : '−'}{Math.abs(d.delta).toFixed(d.unit === 'mW' ? 1 : 0)} {d.unit}
          {d.unit === 'mW' && !mixed && <span className="faint"> ({maText(d.delta, battery, true)})</span>}</td>
        <td className="cs-drv-bar"><span style={{ width: `${Math.round((Math.abs(d.delta) / maxOf(d.kind)) * 100)}%`, background: up ? 'var(--del-text, #C2410C)' : 'var(--add-text, #15803D)' }} /></td>
      </tr> })}</tbody></table>
  </div>
}

const GROUPS: MetricGroup[] = ['Power', 'BW', 'Latency · Timing']
/** Headline metric per group: the first listed row with any value. Never another row of the group —
 *  a missing Total power reads "미계산", not a CPU part that happens to be 0. */
const HEADLINE: Record<MetricGroup, string[]> = { Power: ['total_power_mw'], BW: ['dram', 'dma', 'total_bw_mbs'], 'Latency · Timing': ['preview_lat', 'frame_latency_ms', 'video_lat'] }

export interface Delta { abs: number; pct: number | null; tone: 'good' | 'bad' | 'same' }
export function delta(v: number | null, ref: number | null, lowerIsBetter = true, tolPct = 1): Delta | null {
  if (v === null || ref === null) return null
  const abs = v - ref
  const pct = ref ? (abs / Math.abs(ref)) * 100 : null
  const small = pct !== null ? Math.abs(pct) < tolPct : Math.abs(abs) < 1e-9
  return { abs, pct, tone: small ? 'same' : (abs < 0) === lowerIsBetter ? 'good' : 'bad' }
}
const sgn = (x: number, d: number) => `${x >= 0 ? '+' : '−'}${Math.abs(x).toFixed(d)}`
export function deltaText(d: Delta, unit: string, digits: number): string {
  return `${sgn(d.abs, digits)} ${unit}${d.pct !== null ? ` (${sgn(d.pct, 1)}%)` : ''}`
}
const ARROW = { good: '▼', bad: '▲', same: '＝' } as const

export function CompareSummary({ items, metrics, battery = DEFAULT_BATTERY, batteries, onUnify }: { items: ItemInfo[]; metrics: MetricRow[]; battery?: Battery
  /** per-column Vbat / efficiency (each result's project); ΔI = I(column) − I(★) with each column's own setting */
  batteries?: Battery[]
  /** recompute every column with the same simulation model (shown where a headline mixes sources) */
  onUnify?: () => void }) {
  const bat = (i: number) => batteries?.[i] ?? battery
  const mixedAt = (i: number) => !sameBattery(bat(i), bat(0))
  const anyMixed = items.some((_, i) => mixedAt(i))
  const ma = (v: number | null, unit: string, i = 0) => (unit === 'mW' && v !== null ? maText(v, bat(i)) : null)
  const dma = (m: MetricRow, i: number) => (m.unit === 'mW' ? deltaMaText(m.values[i], bat(i), m.values[0], bat(0)) : null)
  const tip = useTip()
  const rows = metrics.filter((m) => m.values.some((v) => v !== null))
  // no row with data: the group's first headline row still answers ("미계산"), so the card never borrows another metric
  const headline = (g: MetricGroup) => HEADLINE[g].map((k) => rows.find((r) => r.key === k)).find(Boolean) ?? metrics.find((r) => r.key === HEADLINE[g][0])
  const valText = (m: MetricRow, i: number) => (m.values[i] === null ? m.blank?.[i] ?? '—' : `${m.values[i]!.toFixed(m.digits ?? 1)} ${m.unit}`)
  const best = (m: MetricRow) => {
    if (m.values.some((_, i) => !sameSource(m, i))) return -1  // a ranking across sources is not a design ranking
    const vals = m.values.map((v, i) => ({ v, i })).filter((x): x is { v: number; i: number } => x.v !== null)
    if (vals.length < 2) return -1
    const lo = m.lowerIsBetter !== false
    return vals.reduce((a, b) => ((lo ? b.v < a.v : b.v > a.v) ? b : a)).i
  }
  return (
    <div className={`cs ${items.length >= 4 ? 'cs-compact' : ''}`}>
      <div className="cs-cards">
        {items.slice(1).map((it, n) => {
          const i = n + 1
          const mixedHeads = GROUPS.map(headline).filter((m): m is MetricRow => !!m && !sameSource(m, i))
          return (
            <div key={i} className="cs-card" style={{ borderLeftColor: it.color }}>
              <div className="cs-card-h"><span className="mono" title={it.full}>{it.label}</span><span className="faint">vs ★ {items[0].label}</span></div>
              <div className="cs-heads">
                {GROUPS.map((g) => {
                  const m = headline(g)
                  const mixed = !!m && !sameSource(m, i)
                  const d = m && !mixed ? delta(m.values[i], m.values[0], m.lowerIsBetter !== false, m.tolerancePct ?? 1) : null
                  return (
                    <div key={g} className={`cs-head t-${d?.tone ?? 'none'}`}
                      {...(m ? tip({ title: `${g} · ${m.label}`, color: it.color, head: { label: it.label, value: valText(m, i), tone: 'strong' },
                        rows: [{ k: `★ ${items[0].label}`, v: valText(m, 0), tone: 'muted' },
                          ...(d ? [{ k: 'Δ', v: deltaText(d, m.unit, m.digits ?? 1), tone: d.tone === 'same' ? 'muted' as const : d.tone }] : []),
                          ...(mixed ? [{ k: '출처', v: `★ ${m.sources![0]} · ${m.sources![i]}`, tone: 'bad' as const }] : [])],
                        foot: mixed ? '출처(모델 범위)가 달라 Δ를 표시하지 않음 — Simulation 통일로 같은 모델 비교' : m.hint }) : {})}>
                      <div className="cs-g">{g}</div>
                      {mixed && m ? <>
                        <div className="cs-v cs-mixed">출처 다름</div>
                        <div className="cs-sub">★ {m.sources![0]} · {m.sources![i]}</div>
                      </> : d && m ? <>
                        <div className="cs-v mono"><span className="cs-arrow">{ARROW[d.tone]}</span>{d.pct !== null ? `${sgn(d.pct, 1)}%` : sgn(d.abs, m.digits ?? 1)}</div>
                        <div className="cs-sub mono">{sgn(d.abs, m.digits ?? 1)} {m.unit}{dma(m, i) ? ` (${dma(m, i)})` : ''} · {m.label}</div>
                      </> : <>
                        <div className="cs-v faint">{m ? '미계산' : '—'}</div>
                        {m && <div className="cs-sub">{m.label}{m.values[0] === null ? ' · ★ 값 없음' : ' · 값 없음'}</div>}
                      </>}
                    </div>
                  )
                })}
              </div>
              {mixedHeads.length > 0 && onUnify && <button className="btn sm cs-unify" onClick={onUnify}
                title="모든 항목을 같은 simulation 모델(같은 기본 조건)로 다시 계산해 Δ를 비교">Simulation 통일로 다시 계산</button>}
              {it.drivers && it.drivers.length > 0 && <Drivers list={it.drivers} battery={bat(i)} mixed={mixedAt(i)} />}
              <div className="cs-meta faint">
                {it.changed && <span>변경: 조건 {it.changed.conditions} · IP {it.changed.ips} · size {it.changed.sizes}</span>}
                <span>KPI {it.source ?? '없음'}</span>
              </div>
              {it.status}
            </div>
          )
        })}
      </div>
      <div className="cs-table-wrap"><table className="cs-table">
        <thead><tr><th>지표</th>{items.map((it, i) => <th key={i} style={{ borderTop: `3px solid ${it.color}` }} title={it.full}><span className="mono cs-th-l">{it.label}</span>{i === 0 ? ' ★' : ''}</th>)}</tr></thead>
        {GROUPS.map((g) => {
          const gr = rows.filter((r) => r.group === g)
          if (!gr.length) return null
          return (
            <tbody key={g}>
              <tr className="cs-grp"><td colSpan={items.length + 1}>{g}</td></tr>
              {gr.map((m) => {
                const b = best(m)
                return (
                  <tr key={m.key}>
                    <td title={m.unit === 'mW' ? `${m.hint ? `${m.hint} · ` : ''}${batteryNote(battery)}` : m.hint}>{m.label} <span className="faint">({m.unit}{m.unit === 'mW' ? ' · mA@Vbat' : ''})</span></td>
                    {m.values.map((v, i) => {
                      const mixed = i > 0 && !sameSource(m, i)
                      const d = i > 0 && !mixed ? delta(v, m.values[0], m.lowerIsBetter !== false, m.tolerancePct ?? 1) : null
                      const tipRows: TipRow[] = [{ k: `★ ${items[0].label}`, v: valText(m, 0), tone: 'muted' }]
                      if (d) tipRows.push({ k: 'Δ', v: deltaText(d, m.unit, m.digits ?? 1), tone: d.tone === 'same' ? 'muted' : d.tone })
                      if (m.sources?.[i]) tipRows.push({ k: '출처', v: m.sources[i]!, tone: mixed ? 'bad' : 'muted' })
                      if (b === i) tipRows.push({ k: '순위', v: m.lowerIsBetter !== false ? '최저 (best)' : '최고 (best)', tone: 'good' })
                      return (
                        <td key={i} className={`mono ${b === i ? 'cs-best' : ''}`}
                          {...(v !== null ? tip({ title: `${m.label} · ${items[i].label}`, color: items[i].color, head: { label: '값', value: `${v.toFixed(m.digits ?? 1)} ${m.unit}`, tone: 'strong' }, rows: tipRows,
                            foot: mixed ? '★와 출처가 달라 Δ 생략' : m.hint }) : {})}>
                          {v === null ? <span className="faint">{m.blank?.[i] ?? '—'}</span> : <>
                            <span className="cs-val">{v.toFixed(m.digits ?? 1)}</span>{ma(v, m.unit, i) && <span className="cs-ma" title={batteryNote(bat(i))}>{ma(v, m.unit, i)}</span>}
                            {d && <span className={`cs-chip t-${d.tone}`}>{ARROW[d.tone]} {d.pct !== null ? `${sgn(d.pct, 1)}%` : sgn(d.abs, m.digits ?? 1)}</span>}
                            {mixed && <span className="cs-chip t-none">출처 다름</span>}
                          </>}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          )
        })}
      </table></div>
      <div className="faint" style={{ fontSize: 11.5 }}>▼ 개선 · ▲ 악화 · ＝ ±1% 이내 (fps는 높을수록 개선) · 출처 다름 = ★와 다른 모델·측정이라 Δ 생략 · 굵은 테두리 = 행별 최선 · hover = 절대값·Δ · {anyMixed ? '열마다 Vbat·효율이 다름 — 전류는 각 열의 과제 설정으로 환산, ΔI = 각 전류의 차' : batteryNote(bat(0))}</div>
    </div>
  )
}
