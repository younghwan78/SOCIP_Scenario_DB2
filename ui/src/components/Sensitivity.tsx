import { useState } from 'react'
import { fmt } from '../lib/timingBudget'

export type SensitivityRow = {
  key: string; label: string; source: string; step_pct: number; component_mw: number
  delta_low_mw: number; delta_high_mw: number; swing_mw: number; swing_pct: number | null
  break_even_pct: Record<string, number | null>; crosses: string[]
  timing?: { growth_tolerance: number; break_even_pct: number; at_least: boolean; fails_at_high: boolean }
  note?: string
}
export type Sensitivity = { method: string; pct: number; voltage_pct: number; total_mw: number; limits: Record<string, number>; rows: SensitivityRow[]; notes?: string[] }

/** X-13: source grade of a tornado input, read from the row's own key / source (sim/sensitivity.py):
 * SW timing says assumed vs profile / measured; a ratio names its source (catalog / spec / measured);
 * catalog unit power, the BW coefficient, declared loads and SAMPLE voltages are assumed inputs. */
export type SourceGrade = 'measured' | 'fitted' | 'spec' | 'assumed'
export const GRADE_LABEL: Record<SourceGrade, string> = { measured: '실측', fitted: '보정', spec: 'spec', assumed: '가정' }
export function sourceGrade(r: Pick<SensitivityRow, 'key' | 'source'>): SourceGrade {
  const s = r.source.toLowerCase()
  if (r.key === 'sw:runtime') return s === 'assumed' ? 'assumed' : 'measured'
  if (/measured|실측/.test(s)) return 'measured'
  if (/fitted|calibrat|보정/.test(s)) return 'fitted'
  if (/\bspec\b/.test(s)) return 'spec'
  return 'assumed'
}

/** S-03 tornado: Δ total power when one assumed input moves by ±step on its own, largest first. X-13: the
 * default view keeps assumed inputs only (what to measure first); "전체 입력" adds measured / spec ones. */
export function SensitivityTornado({ data, top = 8 }: { data: Sensitivity; top?: number }) {
  const [all, setAll] = useState(false)
  const graded = data.rows.map((r) => ({ r, g: sourceGrade(r) }))
  const hidden = graded.filter((x) => x.g !== 'assumed').length
  const rows = (all ? graded : graded.filter((x) => x.g === 'assumed')).slice(0, top)
  const toggle = hidden > 0 && <label className="faint t-caption" style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
    <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} data-testid="sens-all" />전체 입력 (실측 · spec {hidden}개 포함)</label>
  if (!rows.length) return <div className="empty">흔들 가정 입력이 없습니다.{toggle}</div>
  const span = Math.max(...rows.map(({ r }) => Math.max(Math.abs(r.delta_low_mw), Math.abs(r.delta_high_mw)))) || 1
  const limits = Object.entries(data.limits)
  return <div className="sens">
    {toggle}
    <table className="tb-mini-table sens-table" style={{ width: '100%' }}>
      <thead><tr><th>입력</th><th>출처</th><th style={{ width: '38%' }}>Δ total (−step ↔ +step)</th><th className="n">±mW</th><th>판정 영향</th></tr></thead>
      <tbody>{rows.map(({ r, g }) => {
        const lo = Math.min(r.delta_low_mw, r.delta_high_mw), hi = Math.max(r.delta_low_mw, r.delta_high_mw)
        const left = 50 + 50 * lo / span, right = 50 + 50 * hi / span
        const effects: string[] = []
        if (r.crosses.length) effects.push(`${r.crosses.join(', ')} 넘김`)
        for (const [name, pct] of Object.entries(r.break_even_pct)) if (pct != null && !r.crosses.includes(name)) effects.push(`${name}까지 ${pct > 0 ? '+' : ''}${fmt(pct, 0)}%`)
        if (r.timing) effects.push(r.timing.fails_at_high ? `SW +${data.pct}%면 timing 미달` : `timing 여유 ${r.timing.at_least ? '≥' : ''}+${fmt(r.timing.break_even_pct, 0)}%`)
        return <tr key={r.key} data-testid={`sens-${g}`}>
          <td>{r.label}<span className="faint"> · ±{r.step_pct}%{r.note ? ` · ${r.note}` : ''}</span></td>
          <td><span className={`badge ${g === 'assumed' ? 'v-na' : g === 'measured' ? 'v-ok' : 'v-info'}`}>{GRADE_LABEL[g]}</span> <span className="faint">{r.source}</span></td>
          <td><div className="sens-bar" role="img" aria-label={`${r.label}: ${fmt(lo, 1)} ~ +${fmt(hi, 1)} mW`}>
            <span className="sens-zero" /><span className={`sens-span${g === 'assumed' ? '' : ' graded'}`} style={{ left: `${left}%`, width: `${Math.max(0.5, right - left)}%` }} /></div></td>
          <td className="n">{fmt(r.swing_mw / 2, 1)}{r.swing_pct != null && <span className="faint"> ({fmt(r.swing_pct / 2, 1)}%)</span>}</td>
          <td className={r.crosses.length || r.timing?.fails_at_high ? 'err' : 'faint'} style={{ margin: 0 }}>{effects.join(' · ') || '—'}</td>
        </tr>
      })}</tbody>
    </table>
    {(data.notes ?? []).map((n) => <div key={n} className="faint" style={{ fontSize: 12 }}>{n}</div>)}
    <div className="faint" style={{ fontSize: 12 }}>
      기준 total {fmt(data.total_mw, 1)} mW{limits.map(([k, v]) => ` · ${k} ${fmt(v, 0)} mW`).join('')} · 입력 하나씩 ±{data.pct}% (SAMPLE 전압 ±{data.voltage_pct}%) · 예측 조합 기준 선형 추정 (재시뮬레이션 아님) — 위쪽 가정 입력부터 실측하면 결론의 불확실성이 가장 많이 줄어듭니다. IP unit power는 catalog 값이라 보정(power params) 여부와 관계없이 가정으로 표시합니다.
    </div>
  </div>
}
