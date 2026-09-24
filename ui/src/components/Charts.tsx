import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import type { BoxStats } from '../lib/cadence'

export function useWidth<T extends HTMLElement>(fallback = 600): [React.RefObject<T>, number] {
  const ref = useRef<T>(null)
  const [w, setW] = useState(fallback)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setW(Math.max(260, Math.floor(e.contentRect.width))))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w]
}

export const SERIES = ['#2F6F68', '#C2410C', '#4F46E5', '#B45309', '#0E7490', '#9D174D', '#4D7C0F', '#6B21A8']

function niceTicks(lo: number, hi: number, n = 6): number[] {
  const span = Math.max(hi - lo, 1e-6)
  const raw = span / n
  const p = Math.pow(10, Math.floor(Math.log10(raw)))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw) ?? raw
  const out: number[] = []
  for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) out.push(+t.toFixed(6))
  return out
}

export interface BoxRow { id: string; label: ReactNode; box: BoxStats | null; values: number[]; color?: string; note?: string }

/** Horizontal box plots (Tukey-less: whiskers = min/max) with raw points and an optional target line. */
export function BoxPlot({ rows, unit = 'ms', target, targetLabel, tolerance = 0.05, labelW = 210 }: { rows: BoxRow[]; unit?: string; target?: number | null; targetLabel?: string; tolerance?: number; labelW?: number }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const vals = rows.flatMap((r) => (r.box ? [r.box.min, r.box.max] : []))
  if (target) vals.push(target * (1 - tolerance * 2), target * (1 + tolerance * 2))
  const lo0 = Math.min(...vals), hi0 = Math.max(...vals)
  const pad = Math.max((hi0 - lo0) * 0.08, (target ?? hi0) * 0.02, 0.05)
  const lo = Math.max(0, lo0 - pad), hi = hi0 + pad
  const RH = 34, top = 18, plotW = Math.max(120, width - labelW - 70)
  const x = (v: number) => labelW + ((v - lo) / (hi - lo || 1)) * plotW
  const H = top + rows.length * RH + 24
  const ticks = vals.length ? niceTicks(lo, hi) : []
  return (
    <div ref={ref} style={{ width: '100%' }}>
      {!vals.length ? <div className="empty">데이터 없음</div> :
        <svg width={width} height={H} style={{ display: 'block' }}>
          {ticks.map((t) => <g key={t}><line x1={x(t)} y1={top - 6} x2={x(t)} y2={H - 20} stroke="#EFEAE2" />
            <text x={x(t)} y={H - 6} fontSize={9.5} textAnchor="middle" fill="var(--muted)" fontFamily="var(--mono)">{t}</text></g>)}
          <text x={labelW + plotW + 6} y={H - 6} fontSize={9.5} fill="var(--faint)">{unit}</text>
          {target && <g>
            <rect x={x(target * (1 - tolerance))} y={top - 8} width={x(target * (1 + tolerance)) - x(target * (1 - tolerance))} height={rows.length * RH + 8} fill="#E3EEEB" opacity={0.7} />
            <line x1={x(target)} y1={top - 10} x2={x(target)} y2={top + rows.length * RH} stroke="var(--primary)" strokeWidth={1.6} strokeDasharray="5 3" />
            <text x={x(target) + 4} y={top - 2} fontSize={9.5} fontWeight={700} fill="var(--primary-strong)">{targetLabel ?? `target ${target.toFixed(2)}`}</text>
          </g>}
          {rows.map((r, i) => {
            const cy = top + i * RH + RH / 2
            const c = r.color ?? SERIES[i % SERIES.length]
            const b = r.box
            return (
              <g key={r.id}>
                <foreignObject x={0} y={cy - 14} width={labelW - 8} height={28}><div className="bp-label">{r.label}</div></foreignObject>
                {b && <>
                  <line x1={x(b.min)} y1={cy} x2={x(b.max)} y2={cy} stroke={c} strokeWidth={1.2} />
                  <line x1={x(b.min)} y1={cy - 6} x2={x(b.min)} y2={cy + 6} stroke={c} />
                  <line x1={x(b.max)} y1={cy - 6} x2={x(b.max)} y2={cy + 6} stroke={c} />
                  <rect x={x(b.q1)} y={cy - 9} width={Math.max(2, x(b.q3) - x(b.q1))} height={18} fill={c} opacity={0.18} stroke={c} rx={2} />
                  <line x1={x(b.median)} y1={cy - 9} x2={x(b.median)} y2={cy + 9} stroke={c} strokeWidth={2.2} />
                  <path d={`M${x(b.mean)} ${cy - 4} l4 4 l-4 4 l-4 -4z`} fill="#fff" stroke={c} />
                </>}
                {r.values.map((v, k) => <circle key={k} cx={x(v)} cy={cy + ((k * 7) % 13) - 6} r={2.2} fill={c} opacity={0.55} />)}
                <text x={labelW + plotW + 6} y={cy + 4} fontSize={9.5} fill="var(--muted)" fontFamily="var(--mono)">{b ? `n${b.n}` : '—'}</text>
                <title>{b ? `min ${b.min.toFixed(3)} · q1 ${b.q1.toFixed(3)} · med ${b.median.toFixed(3)} · q3 ${b.q3.toFixed(3)} · max ${b.max.toFixed(3)} · mean ${b.mean.toFixed(3)} · σ ${b.std.toFixed(3)} ${unit}` : ''}</title>
              </g>
            )
          })}
        </svg>}
    </div>
  )
}

export interface BarDatum { id: string; label: string; value: number | null; color?: string; note?: string }

/** Horizontal bars with value labels; `base` draws a reference line (e.g. baseline variant). */
export function Bars({ data, unit, base, labelW = 180, format = (v: number) => v.toFixed(1) }: { data: BarDatum[]; unit: string; base?: number | null; labelW?: number; format?: (v: number) => string }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const vals = data.map((d) => d.value).filter((v): v is number => v !== null)
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals, base ?? 0) || 1
  const RH = 22, plotW = Math.max(100, width - labelW - 90)
  const x = (v: number) => labelW + ((v - lo) / (hi - lo)) * plotW
  const H = data.length * RH + 8
  return (
    <div ref={ref} style={{ width: '100%' }}>
      <svg width={width} height={H} style={{ display: 'block' }}>
        {data.map((d, i) => {
          const y = 4 + i * RH
          return <g key={d.id}>
            <text x={labelW - 8} y={y + 14} fontSize={10.5} textAnchor="end" fill="var(--text-2)" fontFamily="var(--mono)">{d.label.length > 26 ? d.label.slice(0, 25) + '…' : d.label}</text>
            {d.value !== null ? <>
              <rect x={Math.min(x(0), x(d.value))} y={y + 3} width={Math.max(1, Math.abs(x(d.value) - x(0)))} height={RH - 7} rx={3} fill={d.color ?? SERIES[i % SERIES.length]} opacity={0.85} />
              <text x={Math.max(x(0), x(d.value)) + 5} y={y + 14} fontSize={10} fill="var(--text-2)" fontFamily="var(--mono)">{format(d.value)} {unit}{d.note ? ` ${d.note}` : ''}</text>
            </> : <text x={x(0) + 4} y={y + 14} fontSize={10} fill="var(--faint)">없음</text>}
            <title>{`${d.label}: ${d.value === null ? '없음' : format(d.value)} ${unit}`}</title>
          </g>
        })}
        {base !== undefined && base !== null && <line x1={x(base)} y1={0} x2={x(base)} y2={H} stroke="var(--primary)" strokeDasharray="4 3" />}
        <line x1={x(0)} y1={0} x2={x(0)} y2={H} stroke="#CFC6B8" />
      </svg>
    </div>
  )
}

export interface StackRow { id: string; label: string; parts: { key: string; value: number }[] }

/** Horizontal stacked bars with shared legend (key → color). */
export function StackedBars({ rows, unit, labelW = 180 }: { rows: StackRow[]; unit: string; labelW?: number }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const keys = [...new Set(rows.flatMap((r) => r.parts.map((p) => p.key)))]
  const totals = rows.map((r) => r.parts.reduce((s, p) => s + p.value, 0))
  const hi = Math.max(1, ...totals)
  const RH = 26, plotW = Math.max(100, width - labelW - 90)
  const color = (k: string) => SERIES[keys.indexOf(k) % SERIES.length]
  return (
    <div ref={ref} style={{ width: '100%' }}>
      <div className="legend-row">{keys.map((k) => <span key={k} className="legend-item"><span className="sw" style={{ background: color(k) }} />{k}</span>)}</div>
      <svg width={width} height={rows.length * RH + 6} style={{ display: 'block' }}>
        {rows.map((r, i) => {
          const y = 3 + i * RH
          let acc = 0
          return <g key={r.id}>
            <text x={labelW - 8} y={y + 15} fontSize={10.5} textAnchor="end" fill="var(--text-2)" fontFamily="var(--mono)">{r.label.length > 26 ? r.label.slice(0, 25) + '…' : r.label}</text>
            {r.parts.map((p) => {
              const x0 = labelW + (acc / hi) * plotW
              acc += p.value
              const w = (p.value / hi) * plotW
              return <rect key={p.key} x={x0} y={y + 3} width={Math.max(0.5, w - 0.5)} height={RH - 8} fill={color(p.key)} opacity={0.85}><title>{`${r.label} · ${p.key}: ${p.value.toFixed(1)} ${unit}`}</title></rect>
            })}
            <text x={labelW + (totals[i] / hi) * plotW + 5} y={y + 15} fontSize={10} fill="var(--text-2)" fontFamily="var(--mono)">{totals[i].toFixed(0)} {unit}</text>
          </g>
        })}
      </svg>
    </div>
  )
}
