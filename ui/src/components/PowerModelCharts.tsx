import { useWidth } from './Charts'
import { FAMILY_COLOR, compareCpu, partColor, type Family, type PowerPart } from '../lib/powerModel'
import { fmt } from '../lib/timingBudget'

export interface PowerRow { id: string; label: string; parts: PowerPart[]; sub?: string | null }

const FAMILY_LABEL: Record<Family, string> = { cpu: 'CPU', ip: 'IP', mem: '메모리(BW)' }

function orderKeys(rows: PowerRow[]): { keys: string[]; labels: Record<string, string>; family: Record<string, Family>; cpuOrder: string[] } {
  const labels: Record<string, string> = {}, family: Record<string, Family> = {}
  const keys: string[] = []
  for (const r of rows) for (const p of r.parts) if (!(p.key in labels)) { labels[p.key] = p.label; family[p.key] = p.family; keys.push(p.key) }
  const rank: Record<Family, number> = { cpu: 0, ip: 1, mem: 2 }
  keys.sort((a, b) => rank[family[a]] - rank[family[b]] || (family[a] === 'cpu' ? compareCpu(a, b) : 0))
  return { keys, labels, family, cpuOrder: keys.filter((k) => family[k] === 'cpu') }
}

/** Stacked power per row (CPU → IP → memory), first row = reference: dashed line + Δ per row. */
export function PowerStack({ rows, selected, onPick }: { rows: PowerRow[]; selected?: string; onPick?: (id: string) => void }) {
  const [ref, w] = useWidth<HTMLDivElement>(720)
  const { keys, labels, family, cpuOrder } = orderKeys(rows)
  const hasSub = rows.some((r) => r.sub)
  const labelW = Math.min(300, Math.max(200, Math.round(w * 0.24))), valW = 170, rh = hasSub ? 34 : 26
  const maxChars = Math.floor((labelW - 16) / 6.6)
  const totals = rows.map((r) => r.parts.reduce((s, p) => s + p.mw, 0))
  const hi = Math.max(1, ...totals)
  const plotW = Math.max(160, w - labelW - valW - 8)
  const k = plotW / hi
  const base = totals[0]
  return (
    <div ref={ref} style={{ width: '100%' }}>
      <div className="legend-row pm-legend">
        {(['cpu', 'ip', 'mem'] as Family[]).map((f) => keys.some((key) => family[key] === f) && (
          <span key={f} className="pm-legend-group"><b style={{ color: FAMILY_COLOR[f] }}>{FAMILY_LABEL[f]}</b>
            {keys.filter((key) => family[key] === f).map((key) => <span key={key} className="legend-item"><span className="sw" style={{ background: partColor(key, cpuOrder) }} />{labels[key]}</span>)}
          </span>))}
      </div>
      <svg width={labelW + plotW + valW} height={rows.length * rh + 6} role="img" aria-label="power composition">
        {rows.map((r, i) => {
          let x = labelW
          const byKey = new Map(r.parts.map((p) => [p.key, p]))
          const delta = totals[i] - base
          return (
            <g key={r.id} transform={`translate(0,${i * rh + 2})`} style={{ cursor: onPick ? 'pointer' : undefined }} onClick={() => onPick?.(r.id)}>
              <rect x={0} y={0} width={labelW + plotW + valW} height={rh - 2} fill={selected === r.id ? '#F3EFE8' : 'transparent'} />
              <text x={labelW - 8} y={hasSub ? 13 : 15} fontSize={11} textAnchor="end" fill="#3B3F4A" className="mono">{i === 0 ? '★ ' : ''}{r.label.length > maxChars ? `${r.label.slice(0, maxChars - 1)}…` : r.label}<title>{r.label}</title></text>
              {r.sub && <text x={labelW - 8} y={26} fontSize={10} textAnchor="end" fill="#8A8274">{r.sub}</text>}
              {keys.map((key) => {
                const p = byKey.get(key)
                if (!p || p.mw <= 0) return null
                const wq = p.mw * k
                const el = <rect key={key} x={x} y={hasSub ? 7 : 4} width={Math.max(0.5, wq - 0.5)} height={hasSub ? rh - 16 : rh - 10} fill={partColor(key, cpuOrder)}>
                  <title>{`${r.label} · ${p.label}: ${fmt(p.mw, 1)} mW (${fmt((100 * p.mw) / Math.max(totals[i], 1e-9), 1)}%)${p.note ? ` — ${p.note}` : ''}`}</title></rect>
                x += wq
                return el
              })}
              <text x={labelW + plotW + 8} y={hasSub ? 20 : 16} fontSize={11} fill="#3B3F4A" className="mono">{fmt(totals[i], 1)} mW
                {i > 0 && <tspan fill={delta > 0.05 ? '#B42318' : delta < -0.05 ? '#2F6F68' : '#8A8274'}>{`  ${delta >= 0 ? '+' : ''}${fmt(delta, 1)}${base > 0 ? ` (${delta >= 0 ? '+' : ''}${fmt((100 * delta) / base, 1)}%)` : ''}`}</tspan>}
              </text>
            </g>)
        })}
        {rows.length > 1 && <line x1={labelW + base * k} x2={labelW + base * k} y1={0} y2={rows.length * rh + 4} stroke="#4A5160" strokeDasharray="4 3"><title>★ 기준 합계</title></line>}
      </svg>
    </div>
  )
}

/** Part-by-part values with Δ vs the first (reference) row: where the difference comes from. */
export function PowerDeltaTable({ rows }: { rows: PowerRow[] }) {
  const { keys, labels, family, cpuOrder } = orderKeys(rows)
  const val = (r: PowerRow, key: string) => r.parts.find((p) => p.key === key)?.mw ?? 0
  const total = (r: PowerRow) => r.parts.reduce((s, p) => s + p.mw, 0)
  const cell = (v: number, b: number, i: number) => {
    const d = v - b
    return <td key={i} className="mono" style={{ textAlign: 'right' }}>{fmt(v, 1)}
      {i > 0 && Math.abs(d) >= 0.05 && <span className={d > 0 ? 'pm-up' : 'pm-down'}> {d > 0 ? '+' : ''}{fmt(d, 1)}</span>}</td>
  }
  return (
    <div className="table-x">
      <table className="grid pm-table">
        <thead><tr><th>구성</th>{rows.map((r, i) => <th key={r.id} style={{ textAlign: 'right' }} title={r.label}>{i === 0 ? '★ ' : ''}{r.label.length > 18 ? `${r.label.slice(0, 17)}…` : r.label}</th>)}</tr></thead>
        <tbody>
          {keys.map((key) => (
            <tr key={key}><td><span className="sw pm-sw" style={{ background: partColor(key, cpuOrder) }} />{labels[key]} <span className="faint">{FAMILY_LABEL[family[key]]}</span></td>
              {rows.map((r, i) => cell(val(r, key), val(rows[0], key), i))}</tr>))}
          <tr className="pm-total"><td><b>합계</b></td>{rows.map((r, i) => cell(total(r), total(rows[0]), i))}</tr>
        </tbody>
      </table>
    </div>
  )
}
