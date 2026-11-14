import { useState } from 'react'
import type { ExpCase, VariantResult } from '../lib/archExplore'
import { fmt } from '../lib/timingBudget'

export type ScatterAxis = 'bw' | 'iq' | 'growth'
const AXIS_LABEL: Record<ScatterAxis, string> = { bw: 'BW MB/s', iq: 'IQ risk', growth: 'SW 증가 여유 (DVFS 고정)' }
const IQ_TEXT = ['무압축', 'lossless', '가정 ratio', 'lossy']

export type ScatterPoint = { key: string; x: number; y: number; roles: string[] }

function iqRisk(c: ExpCase): number {
  if (!c.compression.length) return 0
  return c.lossy ? 3 : c.assumed_ratio ? 2 : 1
}

/** Distinct cases a variant lists (registered, recommended, alternatives, Pareto, baseline) on power vs one other axis. */
export function scatterPoints(v: VariantResult, axis: ScatterAxis, marks: Record<string, string>): ScatterPoint[] {
  const cases: ExpCase[] = [v.recommended, v.min_power_case, ...v.alternatives, ...(v.pareto ?? []), v.baseline]
    .filter((c): c is ExpCase => !!c)
  const growth = (c: ExpCase) => (c as ExpCase & { growth_fixed?: number }).growth_fixed
  const out = new Map<string, ScatterPoint>()
  for (const c of cases) {
    if (out.has(c.key)) continue
    const y = axis === 'bw' ? c.bw_mbs : axis === 'iq' ? iqRisk(c) : growth(c)
    if (y == null) continue
    out.set(c.key, { key: c.key, x: c.total_mw, y, roles: [] })
  }
  for (const [key, role] of Object.entries(marks)) out.get(key)?.roles.push(role)
  return [...out.values()]
}

/** Two-axis view of the trade-off: total power against BW, IQ risk or SW growth headroom (U-03). */
export function ParetoScatter({ v, marks }: { v: VariantResult; marks: Record<string, string> }) {
  const growthKnown = [v.recommended, ...v.alternatives].some((c) => c && (c as ExpCase & { growth_fixed?: number }).growth_fixed != null)
  const [axis, setAxis] = useState<ScatterAxis>('bw')
  const pts = scatterPoints(v, axis, marks)
  const W = 520, H = 220, L = 56, B = 32, T = 10, R = 12
  if (pts.length < 2) return <div className="empty">비교할 조합이 2개 미만입니다.</div>
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y)
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)]
  const [y0, y1] = [Math.min(...ys), Math.max(...ys)]
  const px = (x: number) => L + (x1 === x0 ? 0.5 : (x - x0) / (x1 - x0)) * (W - L - R)
  const py = (y: number) => H - B - (y1 === y0 ? 0.5 : (y - y0) / (y1 - y0)) * (H - B - T)
  const yText = (y: number) => (axis === 'iq' ? IQ_TEXT[y] ?? String(y) : axis === 'growth' ? `×${fmt(y, 1)}` : fmt(y, 0))
  return <div className="pareto-scatter">
    <div className="seg sm" role="tablist" aria-label="세로축">
      {(['bw', 'iq', 'growth'] as const).filter((a) => a !== 'growth' || growthKnown).map((a) =>
        <button key={a} role="tab" aria-selected={axis === a} className={axis === a ? 'on' : ''} onClick={() => setAxis(a)}>{AXIS_LABEL[a]}</button>)}
    </div>
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`total mW 대 ${AXIS_LABEL[axis]}`}>
      <line x1={L} y1={H - B} x2={W - R} y2={H - B} className="axis" />
      <line x1={L} y1={T} x2={L} y2={H - B} className="axis" />
      <text x={L} y={H - 8} className="tick">{fmt(x0, 0)}</text>
      <text x={W - R} y={H - 8} className="tick" textAnchor="end">{fmt(x1, 0)} mW</text>
      <text x={L - 6} y={H - B} className="tick" textAnchor="end">{yText(y0)}</text>
      <text x={L - 6} y={T + 8} className="tick" textAnchor="end">{yText(y1)}</text>
      {pts.map((p) => <g key={p.key}>
        <circle cx={px(p.x)} cy={py(p.y)} r={p.roles.length ? 6 : 4} className={p.roles.length ? 'pt mark' : 'pt'}>
          <title>{`${fmt(p.x, 1)} mW · ${AXIS_LABEL[axis]} ${yText(p.y)}${p.roles.length ? ` · ${p.roles.join(' · ')}` : ''}\n${p.key}`}</title>
        </circle>
        {p.roles.length > 0 && <text x={px(p.x) + 8} y={py(p.y) - 6} className="lbl">{p.roles.join(' · ')}</text>}
      </g>)}
    </svg>
    <div className="faint" style={{ fontSize: 12 }}>
      점 = 이 variant가 나열한 조합 (추천 · 대안 · Pareto · baseline). 왼쪽 아래일수록 power와 {AXIS_LABEL[axis]} 모두 낮음{axis === 'growth' ? ' (SW 증가 여유는 위가 좋음)' : ''}.
    </div>
  </div>
}
