// Compare page: decision summary vs the reference (★) — Power / BW / Latency first.
import type { ReactNode } from 'react'
import { useTip, type TipRow } from './ChartTip'

export type MetricGroup = 'Power' | 'BW' | 'Latency · Timing'
export interface MetricRow {
  group: MetricGroup; key: string; label: string; unit: string; digits?: number
  values: (number | null)[]
  /** false for fps-like metrics (higher is better) */
  lowerIsBetter?: boolean
  /** relative change below this (%) counts as "같음" */
  tolerancePct?: number
  hint?: string
}
export interface ItemInfo {
  label: string; full?: string; color: string; source: string | null
  changed?: { conditions: number; ips: number; sizes: number }
  drivers?: string[]
  status?: ReactNode
}

const GROUPS: MetricGroup[] = ['Power', 'BW', 'Latency · Timing']
/** Headline metric per group (first row whose key matches and has data). */
const HEADLINE: Record<MetricGroup, string[]> = { Power: ['total_power_mw'], BW: ['total_bw_mbs', 'dma'], 'Latency · Timing': ['preview_lat', 'frame_latency_ms', 'video_lat'] }

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

export function CompareSummary({ items, metrics }: { items: ItemInfo[]; metrics: MetricRow[] }) {
  const tip = useTip()
  const rows = metrics.filter((m) => m.values.some((v) => v !== null))
  const headline = (g: MetricGroup) => HEADLINE[g].map((k) => rows.find((r) => r.key === k && r.values[0] !== null)).find(Boolean) ?? rows.find((r) => r.group === g && r.values[0] !== null)
  const best = (m: MetricRow) => {
    const vals = m.values.map((v, i) => ({ v, i })).filter((x): x is { v: number; i: number } => x.v !== null)
    if (vals.length < 2) return -1
    const lo = m.lowerIsBetter !== false
    return vals.reduce((a, b) => ((lo ? b.v < a.v : b.v > a.v) ? b : a)).i
  }
  return (
    <div className="cs">
      <div className="cs-cards">
        {items.slice(1).map((it, n) => {
          const i = n + 1
          return (
            <div key={i} className="cs-card" style={{ borderLeftColor: it.color }}>
              <div className="cs-card-h"><span className="mono" title={it.full}>{it.label}</span><span className="faint">vs ★ {items[0].label}</span></div>
              <div className="cs-heads">
                {GROUPS.map((g) => {
                  const m = headline(g)
                  const d = m ? delta(m.values[i], m.values[0], m.lowerIsBetter !== false, m.tolerancePct ?? 1) : null
                  return (
                    <div key={g} className={`cs-head t-${d?.tone ?? 'none'}`}
                      {...(m ? tip({ title: `${g} · ${m.label}`, color: it.color, head: { label: it.label, value: m.values[i] === null ? '—' : `${m.values[i]!.toFixed(m.digits ?? 1)} ${m.unit}`, tone: 'strong' },
                        rows: [{ k: `★ ${items[0].label}`, v: m.values[0] === null ? '—' : `${m.values[0]!.toFixed(m.digits ?? 1)} ${m.unit}`, tone: 'muted' },
                          ...(d ? [{ k: 'Δ', v: deltaText(d, m.unit, m.digits ?? 1), tone: d.tone === 'same' ? 'muted' as const : d.tone }] : [])], foot: m.hint }) : {})}>
                      <div className="cs-g">{g}</div>
                      {d && m ? <>
                        <div className="cs-v mono"><span className="cs-arrow">{ARROW[d.tone]}</span>{d.pct !== null ? `${sgn(d.pct, 1)}%` : sgn(d.abs, m.digits ?? 1)}</div>
                        <div className="cs-sub mono">{sgn(d.abs, m.digits ?? 1)} {m.unit} · {m.label}</div>
                      </> : <div className="cs-v faint">—</div>}
                    </div>
                  )
                })}
              </div>
              {it.drivers && it.drivers.length > 0 && <div className="cs-why"><b>주요 원인</b> {it.drivers.join(' · ')}</div>}
              <div className="cs-meta faint">
                {it.changed && <span>변경: 조건 {it.changed.conditions} · IP {it.changed.ips} · size {it.changed.sizes}</span>}
                <span>KPI {it.source ?? '없음'}</span>
              </div>
              {it.status}
            </div>
          )
        })}
      </div>
      <table className="cs-table">
        <thead><tr><th>지표</th>{items.map((it, i) => <th key={i} style={{ borderTop: `3px solid ${it.color}` }} title={it.full}><span className="mono">{it.label}</span>{i === 0 ? ' ★' : ''}</th>)}</tr></thead>
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
                    <td title={m.hint}>{m.label} <span className="faint">({m.unit})</span></td>
                    {m.values.map((v, i) => {
                      const d = i > 0 ? delta(v, m.values[0], m.lowerIsBetter !== false, m.tolerancePct ?? 1) : null
                      const tipRows: TipRow[] = [{ k: `★ ${items[0].label}`, v: m.values[0] === null ? '—' : `${m.values[0]!.toFixed(m.digits ?? 1)} ${m.unit}`, tone: 'muted' }]
                      if (d) tipRows.push({ k: 'Δ', v: deltaText(d, m.unit, m.digits ?? 1), tone: d.tone === 'same' ? 'muted' : d.tone })
                      if (b === i) tipRows.push({ k: '순위', v: m.lowerIsBetter !== false ? '최저 (best)' : '최고 (best)', tone: 'good' })
                      return (
                        <td key={i} className={`mono ${b === i ? 'cs-best' : ''}`}
                          {...(v !== null ? tip({ title: `${m.label} · ${items[i].label}`, color: items[i].color, head: { label: '값', value: `${v.toFixed(m.digits ?? 1)} ${m.unit}`, tone: 'strong' }, rows: tipRows, foot: m.hint }) : {})}>
                          {v === null ? <span className="faint">—</span> : <>
                            <span className="cs-val">{v.toFixed(m.digits ?? 1)}</span>
                            {d && <span className={`cs-chip t-${d.tone}`}>{ARROW[d.tone]} {d.pct !== null ? `${sgn(d.pct, 1)}%` : sgn(d.abs, m.digits ?? 1)}</span>}
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
      </table>
      <div className="faint" style={{ fontSize: 11.5 }}>▼ 개선 · ▲ 악화 · ＝ ±1% 이내 (fps는 높을수록 개선) · 굵은 테두리 = 행별 최선 · hover = 절대값·Δ</div>
    </div>
  )
}
