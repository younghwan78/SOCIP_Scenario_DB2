import { useMemo } from 'react'
import { edgePath, type Layout, type Placed } from '../lib/graph'

const EDGE_STYLE = {
  OTF: { stroke: 'var(--otf)', dash: undefined, marker: 'm-otf', width: 1.8 },
  M2M: { stroke: 'var(--m2m)', dash: '6 4', marker: 'm-m2m', width: 1.8 },
  control: { stroke: 'var(--control)', dash: '2 3', marker: 'm-ctl', width: 1.3 },
} as const

interface Props {
  layout: Layout
  selected: string | null
  related: ReadonlySet<string>
  onSelect: (id: string | null) => void
  onToggleGroup: (groupId: string) => void
  showOps: boolean
  zoom: number
}

function opsText(n: Placed): string {
  const ops = (n.data?.active_operations ?? {}) as Record<string, unknown>
  const out: string[] = []
  if (ops.scale) out.push(typeof ops.scale_ratio === 'number' ? `scale ×${ops.scale_ratio.toFixed(2)}` : 'scale')
  if (ops.crop) out.push('crop')
  if (ops.rotate) out.push(`rot ${ops.rotate}°`)
  if (ops.colorspace_convert) out.push('CSC')
  if (ops.compose) out.push('compose')
  return out.join(' · ')
}

export function GraphView({ layout, selected, related, onSelect, onToggleGroup, showOps, zoom }: Props) {
  const w = Math.max(layout.width, 400)
  const h = Math.max(layout.height, 200)
  const dim = selected !== null
  const edges = useMemo(() => [...layout.edges].sort((a, b) => Number(related.has(a.source) && related.has(a.target)) - Number(related.has(b.source) && related.has(b.target))), [layout.edges, related])
  return (
    <svg width={w * zoom} height={h * zoom} viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Pipeline graph" onClick={() => onSelect(null)} style={{ display: 'block' }}>
      <defs>
        {(['otf', 'm2m', 'ctl'] as const).map((k) => (
          <marker key={k} id={`m-${k}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0 0L10 5L0 10z" fill={k === 'otf' ? '#2563EB' : k === 'm2m' ? '#F97316' : '#A16207'} />
          </marker>
        ))}
      </defs>
      {layout.groups.map((g) => (
        <g key={g.id}>
          <rect x={g.x} y={g.y} width={g.width} height={g.height} rx={8} fill="rgba(255,255,255,0.65)" stroke={g.id === 'g:sw' ? '#D6C49A' : '#E6D3BC'} />
        </g>
      ))}
      {edges.map((e) => {
        const st = EDGE_STYLE[e.kind]
        const on = !dim || (related.has(e.source) && related.has(e.target))
        return <path key={e.id} d={edgePath(e.points)} fill="none" stroke={st.stroke} strokeWidth={on && dim ? st.width + 0.8 : st.width}
          strokeDasharray={st.dash} markerEnd={`url(#${st.marker})`} opacity={on ? 1 : 0.18}><title>{e.ports || e.kind}</title></path>
      })}
      {layout.nodes.map((n) => {
        const on = !dim || related.has(n.id)
        const isSel = selected === n.id
        const common = { opacity: on ? 1 : 0.3, className: 'node', onClick: (ev: React.MouseEvent) => { ev.stopPropagation(); if (n.kind === 'group') onToggleGroup(n.id); else onSelect(n.id) } }
        if (n.kind === 'buffer') {
          return (
            <g key={n.id} {...common}>
              <rect x={n.x} y={n.y} width={n.width} height={n.height} rx={5} fill="var(--buf-fill)" stroke={isSel ? 'var(--primary-strong)' : 'var(--buf-line)'} strokeWidth={isSel ? 2.4 : 1.1} />
              <text x={n.x + 6} y={n.y + 13} fontSize={10} fontWeight={700} fill="var(--buf-text)" fontFamily="var(--mono)">{n.label}</text>
              <text x={n.x + 6} y={n.y + 26} fontSize={9} fill="var(--buf-text)" fontFamily="var(--mono)">{n.sub}</text>
              <title>{`${n.bufferRef}\n${n.sub ?? ''}`}</title>
            </g>
          )
        }
        const style = n.kind === 'external' ? { fill: 'var(--ext-fill)', stroke: 'var(--ext-line)', text: '#1E293B', rx: 16 }
          : n.kind === 'sw' ? { fill: '#FFFFFF', stroke: 'var(--control)', text: '#1F2937', rx: 13 }
            : n.kind === 'group' ? { fill: '#FFF8F0', stroke: '#E6D3BC', text: '#9A4A12', rx: 8 }
              : { fill: 'var(--ip-fill)', stroke: 'var(--ip-line)', text: 'var(--ip-text)', rx: 6 }
        const ops = showOps && n.kind === 'ip' ? opsText(n) : ''
        return (
          <g key={n.id} {...common}>
            <rect x={n.x} y={n.y} width={n.width} height={n.height} rx={style.rx} fill={style.fill}
              stroke={isSel ? 'var(--primary-strong)' : style.stroke} strokeWidth={isSel ? 2.6 : n.kind === 'external' ? 1.6 : 1.2} strokeDasharray={n.kind === 'group' ? '4 3' : undefined} />
            {n.kind === 'external' && <rect x={n.x + 4} y={n.y + 4} width={n.width - 8} height={n.height - 8} rx={12} fill="none" stroke="var(--ext-line)" strokeWidth={0.8} strokeDasharray="2 2" />}
            <text x={n.x + n.width / 2} y={n.y + n.height / 2 + 4} textAnchor="middle" fontSize={n.kind === 'sw' ? 10.5 : 11.5} fontWeight={600} fill={style.text}>{n.label}</text>
            {n.kind === 'external' && <text x={n.x + n.width - 4} y={n.y - 3} textAnchor="end" fontSize={8.5} fontWeight={700} fill="var(--ext-line)">EXT</text>}
            {ops && <text x={n.x + n.width / 2} y={n.y + n.height + 11} textAnchor="middle" fontSize={9.5} fill="#9A4A12">{ops}</text>}
            <title>{n.data?.ip_ref ?? n.label}</title>
          </g>
        )
      })}
      {layout.groups.map((g) => (
        <text key={`t:${g.id}`} x={g.x + 10} y={g.y + 16} fontSize={10.5} fontWeight={700} fill={g.id === 'g:sw' ? '#8A5A0B' : '#9A4A12'} style={{ cursor: 'pointer', paintOrder: 'stroke' }}
          stroke="#FFFFFF" strokeWidth={3} onClick={(e) => { e.stopPropagation(); onToggleGroup(g.id) }}>▾ {g.label} · {g.count}</text>
      ))}
    </svg>
  )
}
