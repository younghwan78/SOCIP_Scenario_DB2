import { useMemo } from 'react'
import { LANE_LABEL, parseSize, type IpLink, type IpModel, type PipelineModel, type Port, type Via } from '../lib/model'
import { TOPO, colorMap, linkPath, topoLayout } from '../lib/topology'
import { usePref } from './Layout'
import { DataTable, type Column } from './DataTable'

// Two independent visual axes (UX 2026-10-09):
//   line / box border = how the data moves  → OTF (thin blue) · DMA (thick orange, memory) · SW (dotted violet, CPU trigger)
//   box fill + tag    = what the data is    → IMG (image) · STAT (statistics) · HIST (previous-frame reference) · TRIG (SW trigger)
// so a stat WDMA is drawn with the same solid DMA line as an image WDMA and only its tag / fill differ.
export type PathKind = 'OTF' | 'DMA' | 'SW' | 'off'
export type DataKind = 'image' | 'stat' | 'history' | 'trigger' | 'off'
export const PATH_STYLE: Record<PathKind, { stroke: string; width: number; dash?: string; label: string }> = {
  OTF: { stroke: '#2563EB', width: 1.4, label: 'OTF (on-the-fly)' },
  DMA: { stroke: '#EA580C', width: 2.4, label: 'DMA (memory)' },
  SW: { stroke: '#7C3AED', width: 1.4, dash: '1.5 3', label: 'SW (CPU trigger)' },
  off: { stroke: '#A1A1AA', width: 1.2, dash: '4 3', label: 'off (disabled)' },
}
export const DATA_STYLE: Record<DataKind, { fill: string; tag: string; tagColor: string; label: string }> = {
  image: { fill: '#FFFFFF', tag: 'IMG', tagColor: '#1F2430', label: 'image' },
  stat: { fill: '#FEF3C7', tag: 'STAT', tagColor: '#92400E', label: 'stat (3A · histogram …)' },
  history: { fill: '#E0E7FF', tag: 'HIST', tagColor: '#3730A3', label: 'history (prev frame)' },
  trigger: { fill: '#F5F3FF', tag: 'TRIG', tagColor: '#6D28D9', label: 'SW trigger · IRQ' },
  off: { fill: '#F4F4F5', tag: 'OFF', tagColor: '#71717A', label: 'disabled' },
}
export const pathOf = (v: Via): PathKind => (v === 'OTF' ? 'OTF' : v === 'ctrl' ? 'SW' : v === 'optional' ? 'off' : 'DMA')
export const dataOf = (v: Via): DataKind => (v === 'stat' ? 'stat' : v === 'history' ? 'history' : v === 'ctrl' ? 'trigger' : v === 'optional' ? 'off' : 'image')
/** "WDMA · STAT", "RDMA · HIST", "OTF out · IMG", "SW · TRIG" */
export function portKindLabel(p: Pick<Port, 'via' | 'dir'>): string {
  const path = pathOf(p.via), data = DATA_STYLE[dataOf(p.via)].tag
  const how = path === 'DMA' ? (p.dir === 'in' ? 'RDMA' : 'WDMA') : path === 'OTF' ? `OTF ${p.dir}` : path === 'SW' ? 'SW' : 'off'
  return `${how} · ${data}`
}

const ROW = 44, GAP = 8, PW = 250, CW = 250, COL_GAP = 70, TOP = 38

function ratio(a: string, b: string | undefined): string {
  const x = parseSize(a), y = parseSize(b)
  if (!x || !y) return ''
  if (x.w === y.w && x.h === y.h) return '1:1'
  const r = x.w / y.w
  return r > 1 ? `↓${r.toFixed(2)}` : `↑${(1 / r).toFixed(2)}`
}

function PortBox({ p, x, y, inSize }: { p: Port; x: number; y: number; inSize?: string }) {
  const ps = PATH_STYLE[pathOf(p.via)], ds = DATA_STYLE[dataOf(p.via)]
  const l2 = [p.buffer, [p.size, p.format, p.bit ? `${p.bit}b` : '', p.comp && p.comp !== 'COMP_OFF' ? p.comp.replace('COMP_', '') : ''].filter(Boolean).join(' ')].filter(Boolean).join(' · ')
  const r = p.dir === 'out' && p.size && inSize ? ratio(inSize, p.size) : ''
  // keep the port name clear of the right-aligned "WDMA · STAT ↓2.00" tag (mono 11px ≈ 6.7 px/char, tag 9px ≈ 5.6)
  const tagChars = portKindLabel(p).length + (r ? r.length + 1 : 0)
  const nameMax = Math.max(12, Math.floor((PW - 24 - tagChars * 5.6) / 6.7))
  return (
    <g opacity={p.enabled ? 1 : 0.55}>
      <rect x={x} y={y} width={PW} height={ROW} rx={6} fill={ds.fill} stroke={ps.stroke} strokeWidth={ps.width > 2 ? 1.8 : 1.1} strokeDasharray={ps.dash} />
      <text x={x + 8} y={y + 15} fontSize={11} fontWeight={700} fontFamily="var(--mono)" fill="#1F2430">{p.port.length > nameMax ? p.port.slice(0, nameMax - 1) + '…' : p.port}</text>
      <text x={x + PW - 8} y={y + 15} fontSize={9} textAnchor="end" fontWeight={700}><tspan fill={ps.stroke}>{portKindLabel(p).split(' · ')[0]}</tspan><tspan fill={ds.tagColor}> · {ds.tag}</tspan>{r ? <tspan fill="#3B3F4A"> {r}</tspan> : null}</text>
      <text x={x + 8} y={y + 29} fontSize={9.5} fontFamily="var(--mono)" fill="#3B3F4A">{(l2 || p.peer || '').slice(0, 42)}</text>
      <text x={x + 8} y={y + 40} fontSize={9} fill="var(--muted)">{p.dir === 'in' ? '← ' : '→ '}{p.peer ?? ''}{p.mb ? ` · ${p.mb.toFixed(2)} MB/f` : ''}{p.enabled ? '' : ' · disabled'}</text>
      <title>{[p.port, `${PATH_STYLE[pathOf(p.via)].label} · ${ds.label}`, p.buffer, l2, p.peer, p.note].filter(Boolean).join('\n')}</title>
    </g>
  )
}

/** Merge per-plane ports of one buffer: MLSC_W_GLPG1_Y/U/V → MLSC_W_GLPG1_{Y,U,V}. */
export function groupPorts(ports: Port[]): Port[] {
  const out: Port[] = []
  const names: string[][] = []
  const idx = new Map<string, number>()
  for (const p of ports) {
    const k = `${p.dir}|${p.via}|${p.buffer ?? p.port}|${p.peer ?? ''}`
    const i = idx.get(k)
    if (i === undefined || !p.buffer) { idx.set(k, out.length); out.push({ ...p }); names.push([p.port]); continue }
    names[i].push(p.port)
    const all = names[i]
    let pre = all[0]
    for (const n of all) while (!n.startsWith(pre)) pre = pre.slice(0, -1)
    out[i].port = pre.length >= 4 ? `${pre}{${all.map((n) => n.slice(pre.length)).join(',')}}` : all.join(', ')
  }
  return out
}

export function IpDiagram({ ip }: { ip: IpModel }) {
  const ins = groupPorts(ip.ports.filter((p) => p.dir === 'in'))
  const outs = groupPorts(ip.ports.filter((p) => p.dir === 'out'))
  const usedNames = new Set(ip.ports.map((p) => p.port))
  const spare = (dir: 'in' | 'out') => ip.channels.filter((c) => c.dir === dir && !usedNames.has(c.name) && c.status !== 'used')
  const spareIn = spare('in'), spareOut = spare('out')
  const order = (v: Via) => ['OTF', 'DMA', 'history', 'stat', 'ctrl', 'optional'].indexOf(v)
  ins.sort((a, b) => order(a.via) - order(b.via)); outs.sort((a, b) => order(a.via) - order(b.via))
  const coreLines: [string, string][] = [
    ['처리 크기', ip.inSize || '—'],
    ...(ip.mode ? [['mode', ip.mode] as [string, string]] : []),
    ...ip.flags.slice(0, 6),
    ...(ip.sw ? [['SW time', `${ip.sw.mean ?? '?'} ms (${ip.sw.min ?? '?'}–${ip.sw.max ?? '?'}) · ${ip.sw.source ?? ''}`] as [string, string]] : []),
  ]
  const stages = ['IN', ...ip.ops, 'OUT']
  const rows = Math.max(ins.length, outs.length, Math.ceil((coreLines.length * 16 + stages.length * 30 + 40) / (ROW + GAP)), 2)
  const SP = 17, spareTop = TOP + rows * (ROW + GAP) + 18
  const H = spareTop + Math.max(spareIn.length, spareOut.length) * SP + (spareIn.length || spareOut.length ? 8 : -8)
  const cx = PW + COL_GAP, ox = cx + CW + COL_GAP
  const W = ox + PW + 10
  const coreH = rows * (ROW + GAP) - GAP
  const midY = TOP + coreH / 2
  return (
    <svg width={W} height={H} style={{ display: 'block' }} role="img" aria-label={`${ip.label} 내부 구조`}>
      <defs><marker id="ipa" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#8A8274" /></marker></defs>
      <text x={0} y={16} fontSize={11} fontWeight={700} fill="var(--muted)">입력 · OTF in / RDMA / history read</text>
      <text x={cx} y={16} fontSize={11} fontWeight={700} fill="var(--muted)">Core</text>
      <text x={ox} y={16} fontSize={11} fontWeight={700} fill="var(--muted)">출력 · OTF out / WDMA / stat</text>
      {ins.map((p, i) => {
        const y = TOP + i * (ROW + GAP)
        return <g key={`i${i}`}><PortBox p={p} x={0} y={y} />
          <path d={`M${PW} ${y + ROW / 2} C ${PW + 35} ${y + ROW / 2}, ${cx - 35} ${midY}, ${cx} ${midY}`} fill="none" stroke={PATH_STYLE[pathOf(p.via)].stroke} strokeDasharray={PATH_STYLE[pathOf(p.via)].dash} strokeWidth={PATH_STYLE[pathOf(p.via)].width} markerEnd="url(#ipa)" opacity={0.75} /></g>
      })}
      {!ins.length && <text x={10} y={TOP + 20} fontSize={11} fill="var(--faint)">입력 port 정보 없음</text>}
      <rect x={cx} y={TOP} width={CW} height={coreH} rx={10} fill="var(--ip-fill)" stroke="var(--ip-line)" strokeWidth={1.4} />
      <text x={cx + 12} y={TOP + 20} fontSize={13} fontWeight={700} fill="var(--ip-text)">{ip.label}</text>
      <text x={cx + CW - 10} y={TOP + 20} fontSize={9} textAnchor="end" fill="var(--ip-text)" fontFamily="var(--mono)">{ip.ipRef.replace(/^ip-/, '')}</text>
      {stages.map((s, i) => {
        const y = TOP + 32 + i * 30
        return <g key={s + i}>
          <rect x={cx + 14} y={y} width={CW - 28} height={22} rx={5} fill={i === 0 || i === stages.length - 1 ? '#FFFFFF' : '#FDE7D2'} stroke="#E8B48A" />
          <text x={cx + CW / 2} y={y + 15} textAnchor="middle" fontSize={10.5} fontWeight={600} fill="#7C2D12" fontFamily="var(--mono)">
            {i === 0 ? `IN ${ip.inSize || ''}` : i === stages.length - 1 ? `OUT ${ip.outSizes.slice(0, 2).join(' / ')}${ip.outSizes.length > 2 ? ` +${ip.outSizes.length - 2}` : ''}${!ip.outSizes.length && outs.some((o) => o.via === 'OTF') ? 'OTF' : ''}` : s}</text>
          {i < stages.length - 1 && <line x1={cx + CW / 2} y1={y + 22} x2={cx + CW / 2} y2={y + 30} stroke="#E8B48A" markerEnd="url(#ipa)" />}
        </g>
      })}
      {coreLines.map(([k, v], i) => (
        <text key={k} x={cx + 14} y={TOP + 44 + stages.length * 30 + i * 16} fontSize={10} fill="#5B3A1E"><tspan fontWeight={700}>{k}</tspan> <tspan fontFamily="var(--mono)">{v.length > 34 ? v.slice(0, 33) + '…' : v}</tspan></text>
      ))}
      {outs.map((p, i) => {
        const y = TOP + i * (ROW + GAP)
        return <g key={`o${i}`}>
          <path d={`M${cx + CW} ${midY} C ${cx + CW + 35} ${midY}, ${ox - 35} ${y + ROW / 2}, ${ox} ${y + ROW / 2}`} fill="none" stroke={PATH_STYLE[pathOf(p.via)].stroke} strokeDasharray={PATH_STYLE[pathOf(p.via)].dash} strokeWidth={PATH_STYLE[pathOf(p.via)].width} markerEnd="url(#ipa)" opacity={0.75} />
          <PortBox p={p} x={ox} y={y} inSize={ip.inSize} /></g>
      })}
      {!outs.length && <text x={ox + 10} y={TOP + 20} fontSize={11} fill="var(--faint)">출력 port 정보 없음</text>}
      {([[spareIn, 0], [spareOut, ox]] as const).map(([list, x0]) => list.length > 0 && <g key={x0}>
        <text x={x0} y={spareTop - 5} fontSize={10.5} fontWeight={700} fill="var(--faint)">미사용 {x0 ? 'WDMA/FIFO out' : 'RDMA/FIFO in'} · {list.length} (catalog)</text>
        {list.map((c, i) => <g key={c.name} opacity={0.75}>
          <rect x={x0} y={spareTop + i * SP} width={PW} height={SP - 3} rx={4} fill="#FAFAFA" stroke="#C4C4C8" strokeDasharray="3 3" />
          <text x={x0 + 7} y={spareTop + i * SP + 10.5} fontSize={9.5} fontFamily="var(--mono)" fill="#71717A">{c.name}</text>
          <text x={x0 + PW - 6} y={spareTop + i * SP + 10.5} fontSize={8.5} textAnchor="end" fill="#A1A1AA">{c.status === 'off' ? 'off' : c.kind === 'FIFO' ? 'FIFO' : '미사용'}</text>
          <title>{[c.name, c.purpose, c.status].filter(Boolean).join('\n')}</title>
        </g>)}
      </g>)}
    </svg>
  )
}

const portCols: Column<Port>[] = [
  { key: 'use', label: '상태', width: 64, sort: (p) => (p.unused ? 2 : p.enabled ? 0 : 1), render: (p) => (p.unused ? <span className="badge buf-optional">미사용</span> : p.enabled ? <span className="badge buf-data">사용</span> : <span className="badge buf-stat">off</span>) },
  { key: 'dir', label: 'Dir', width: 52, sort: (p) => p.dir, render: (p) => (p.dir === 'in' ? 'IN' : 'OUT') },
  { key: 'via', label: '경로 · 데이터', width: 116, sort: (p) => `${pathOf(p.via)}|${dataOf(p.via)}`, render: (p) => <span style={{ fontWeight: 600 }}><span style={{ color: PATH_STYLE[pathOf(p.via)].stroke }}>{portKindLabel(p).split(' · ')[0]}</span> · <span style={{ color: DATA_STYLE[dataOf(p.via)].tagColor, background: DATA_STYLE[dataOf(p.via)].fill, padding: '0 3px', borderRadius: 3 }}>{DATA_STYLE[dataOf(p.via)].tag}</span></span> },
  { key: 'port', label: 'Port', width: 210, sort: (p) => p.port, title: (p) => p.port, render: (p) => <span className="mono">{p.port}</span> },
  { key: 'buf', label: 'Buffer', width: 150, sort: (p) => p.buffer ?? null, render: (p) => <span className="mono">{p.buffer ?? '—'}</span> },
  { key: 'peer', label: 'Peer', width: 130, sort: (p) => p.peer ?? null, render: (p) => p.peer ?? '—' },
  { key: 'size', label: 'W×H', width: 100, sort: (p) => { const s = parseSize(p.size); return s ? s.w * s.h : null }, render: (p) => <span className="mono">{p.size || '—'}</span> },
  { key: 'fmt', label: 'Format', width: 86, sort: (p) => p.format ?? null, render: (p) => p.format || '—' },
  { key: 'bit', label: 'Bit', width: 50, sort: (p) => Number(p.bit) || null, render: (p) => p.bit || '—' },
  { key: 'comp', label: 'Comp', width: 90, sort: (p) => p.comp ?? null, render: (p) => p.comp || '—' },
  { key: 'mb', label: 'MB/f', width: 70, align: 'right', sort: (p) => p.mb ?? null, render: (p) => <span className="mono">{p.mb?.toFixed(2) ?? '—'}</span> },
  { key: 'note', label: 'Note', width: 260, title: (p) => p.note, render: (p) => <span className="faint">{p.note ?? ''}</span> },
]

type ColorKey = 'vdd' | 'blk'
const LINK_STYLE: Record<IpLink['kind'], { stroke: string; dash?: string; label: string }> = {
  OTF: { stroke: PATH_STYLE.OTF.stroke, label: 'OTF' },
  M2M: { stroke: PATH_STYLE.DMA.stroke, label: 'M2M (DMA · memory)' },
  ctrl: { stroke: PATH_STYLE.SW.stroke, dash: PATH_STYLE.SW.dash, label: 'SW trigger (CPU)' },
}

/** All IPs and how they connect. Fill = voltage domain or BLK (translucent), click = details below. */
export function IpTopology({ model, selectedPid, onSelect, colorBy }: { model: PipelineModel; selectedPid: string | null; onSelect: (viewId: string) => void; colorBy: ColorKey }) {
  const lay = useMemo(() => topoLayout(model), [model])
  const colors = useMemo(() => colorMap(model.ips.map((i) => (colorBy === 'vdd' ? i.vdd : i.blk))), [model, colorBy])
  const pos = new Map(lay.nodes.map((n) => [n.ip.pid, n]))
  const { W, H } = TOPO
  return (
    <svg className="ipt-svg" viewBox={`0 0 ${lay.width} ${lay.height}`} width={lay.width} height={lay.height} role="group" aria-label="IP 연결 구조">
      <defs>{(Object.keys(LINK_STYLE) as IpLink['kind'][]).map((k) => (
        <marker key={k} id={`ipt-${k}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill={LINK_STYLE[k].stroke} /></marker>))}</defs>
      {lay.columns.map((c) => <g key={c.id}>
        <rect x={c.x - 8} y={4} width={c.w + 16} height={lay.height - 8} rx={8} fill="#F6F3EE" opacity={0.7} />
        <text x={c.x} y={20} fontSize={11} fontWeight={700} fill="var(--muted)">{c.label}</text>
        {c.sections.filter((s) => s.id !== 'main').map((s) => <g key={s.id}>
          <rect x={c.x - 5} y={s.y - 2} width={c.w + 10} height={s.h + 8} rx={6} fill={s.id === 'sw' ? '#FBF3E2' : '#EAF1F6'}
            stroke={s.id === 'sw' ? '#E6CFA0' : '#C6D6E3'} strokeDasharray="3 3" />
          <text x={c.x + 2} y={s.y + 11} fontSize={10} fontWeight={700} fill={s.id === 'sw' ? '#8A5A12' : '#2F5673'}>{s.label}</text>
        </g>)}
      </g>)}
      {lay.ghosts.map((g) => <g key={g.label} opacity={0.75}>
        <rect x={g.x} y={g.y} width={W} height={H} rx={7} fill="#FFFFFF" stroke="#9FB3C2" strokeDasharray="4 3" />
        <text x={g.x + 8} y={g.y + 17} fontSize={12} fontWeight={700} fill="#6B7C88">{g.label}</text>
        <text x={g.x + 8} y={g.y + 31} fontSize={9} fill="#8A97A0">이 variant 미사용</text>
        <text x={g.x + 8} y={g.y + 43} fontSize={9} fill="#8A97A0">scaler 경로 scenario 자리</text>
        <title>{g.note}</title>
      </g>)}
      {lay.links.map((e, i) => {
        const a = pos.get(e.from), b = pos.get(e.to)
        if (!a || !b || e.from === e.to) return null
        const st = LINK_STYLE[e.kind]
        const hot = selectedPid !== null && (e.from === selectedPid || e.to === selectedPid)
        return <path key={i} d={linkPath(a, b)} fill="none" stroke={st.stroke} strokeDasharray={st.dash} strokeWidth={hot ? 2.4 : e.kind === 'M2M' ? 1.6 : 1.3}
          opacity={selectedPid === null || hot ? 0.9 : 0.22} markerEnd={`url(#ipt-${e.kind})`}>
          <title>{`${model.byPid.get(e.from)?.label ?? e.from} → ${model.byPid.get(e.to)?.label ?? e.to} · ${st.label}${e.buffer ? ` · ${e.buffer}` : ''}${e.mbs ? ` · ${e.mbs.toFixed(0)} MB/s` : ''}`}</title></path>
      })}
      {lay.nodes.map(({ ip, x, y }) => {
        const key = colorBy === 'vdd' ? ip.vdd : ip.blk
        const c = key ? colors.get(key) ?? '#9A9387' : '#9A9387'
        const on = ip.pid === selectedPid
        return <g key={ip.pid} className="ipt-node" onClick={() => onSelect(ip.viewId)} role="button" tabIndex={0} aria-label={ip.label} aria-pressed={on}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(ip.viewId) } }}>
          <rect x={x} y={y} width={W} height={H} rx={7} fill={c} fillOpacity={ip.type === 'sw' ? 0.08 : 0.2} stroke={on ? '#1F2430' : c}
            strokeWidth={on ? 2.2 : 1.2} strokeDasharray={ip.type === 'sw' ? '4 3' : undefined} />
          <text x={x + 8} y={y + 17} fontSize={12} fontWeight={700} fill="#1F2430">{ip.label.length > 14 ? ip.label.slice(0, 13) + '…' : ip.label}</text>
          <text x={x + 8} y={y + 31} fontSize={9.5} fontFamily="var(--mono)" fill="#3B3F4A">{[ip.blk, ip.vdd?.replace(/^VDD_/, '')].filter(Boolean).join(' · ') || (ip.type === 'sw' ? 'CPU task' : '—')}</text>
          <text x={x + 8} y={y + 43} fontSize={9} fill="var(--muted)">{ip.type === 'sw' ? (ip.sw?.mean !== undefined ? `${ip.sw.mean} ms` : '') : `R${ip.rdma.used} · W${ip.wdma.used}${ip.inSize ? ` · ${ip.inSize}` : ''}`}</text>
          <title>{[ip.label, ip.ipRef, ip.blk ? `BLK ${ip.blk}${ip.blkSource === 'hierarchy_group' ? ' (hierarchy_group)' : ''}` : 'BLK —', `VDD ${ip.vdd ?? '—'} · DVFS ${ip.dvfsGroup ?? '—'}`].join('\n')}</title>
        </g>
      })}
    </svg>
  )
}

function Legend({ model, colorBy }: { model: PipelineModel; colorBy: ColorKey }) {
  const colors = colorMap(model.ips.map((i) => (colorBy === 'vdd' ? i.vdd : i.blk)))
  const missing = model.ips.filter((i) => i.type !== 'sw' && !(colorBy === 'vdd' ? i.vdd : i.blk)).length
  return <div className="ipv-legend">
    {[...colors].map(([k, c]) => <span key={k} className="legend-item"><span className="ipt-swatch" style={{ background: c + '33', borderColor: c }} />{k}</span>)}
    {missing > 0 && <span className="legend-item"><span className="ipt-swatch" style={{ background: '#9A938733', borderColor: '#9A9387' }} />미정 ({missing})</span>}
    <span className="vsep" />
    {(Object.keys(LINK_STYLE) as IpLink['kind'][]).map((k) => <span key={k} className="legend-item"><svg width="22" height="8"><line x1="1" y1="4" x2="21" y2="4" stroke={LINK_STYLE[k].stroke} strokeWidth="2" strokeDasharray={LINK_STYLE[k].dash} /></svg>{LINK_STYLE[k].label}</span>)}
    <span className="legend-item"><span className="ipt-swatch" style={{ borderStyle: 'dashed' }} />SW task</span>
  </div>
}

export function IpInternalView({ model, selectedPid, onSelect }: { model: PipelineModel; selectedPid: string | null; onSelect: (viewId: string) => void }) {
  const [colorBy, setColorBy] = usePref<ColorKey>('pipeline.ipt.color', 'vdd')
  const hw = useMemo(() => model.ips.filter((i) => i.type !== 'sw'), [model])
  const ip = model.ips.find((i) => i.pid === selectedPid) ?? hw.find((i) => i.lane === 'rt' && i.ports.some((p) => p.via === 'DMA')) ?? hw[0]
  const blkNote = hw.some((i) => i.blkSource === 'hierarchy_group')
  const rows = ip ? [...ip.ports, ...ip.channels.filter((c) => c.status !== 'used' && !ip.ports.some((p) => p.port === c.name))
    .map((c): Port => ({ port: c.name, dir: c.dir, via: c.kind === 'FIFO' ? 'OTF' : 'DMA', enabled: false, unused: c.status === 'unused', peer: c.status === 'off' ? 'disabled' : '—', note: c.purpose }))] : []
  const inputs = ip ? [...new Set(model.links.filter((l) => l.to === ip.pid).map((l) => model.byPid.get(l.from)?.label ?? l.from))] : []
  const outputs = ip ? [...new Set(model.links.filter((l) => l.from === ip.pid).map((l) => model.byPid.get(l.to)?.label ?? l.to))] : []
  return (
    <div className="ipv-page">
      <section className="panel">
        <div className="pane-head"><h2>IP 연결 구조</h2>
          <span className="faint" style={{ fontSize: 12 }}>열 = 데이터 경로 (Pre/Post-NRT = CPU SW · M2M accel) · 열 안 = 연결 순서 · IP 클릭 = 아래 상세</span>
          <span className="grow" />
          <div className="seg sm" role="group" aria-label="색 기준">
            <button className={colorBy === 'vdd' ? 'on' : ''} onClick={() => setColorBy('vdd')}>Voltage domain</button>
            <button className={colorBy === 'blk' ? 'on' : ''} onClick={() => setColorBy('blk')}>BLK</button>
          </div>
        </div>
        <Legend model={model} colorBy={colorBy} />
        <div className="ipt-wrap"><IpTopology model={model} selectedPid={ip?.pid ?? null} onSelect={onSelect} colorBy={colorBy} /></div>
        {blkNote && colorBy === 'blk' && <div className="faint" style={{ fontSize: 11, padding: '0 14px 10px' }}>BLK: IP catalog에 `properties.blk`가 없어 `hierarchy_group`(ISP · Codec · Display …)으로 표시합니다. 실제 BLK 이름은 catalog에 추가하면 반영됩니다.</div>}
      </section>
      {ip ? <section className="panel">
        <div className="pane-head" style={{ flexWrap: 'wrap' }}><h2>{ip.label}</h2>
          <span className="mono faint" style={{ fontSize: 11 }}>{ip.ipRef.replace(/^ip-/, '')}</span>
          <span className="chip">BLK {ip.blk ?? '—'}{ip.blkSource === 'hierarchy_group' ? '*' : ''}</span>
          <span className="chip">{ip.vdd ?? 'VDD —'}</span>
          <span className="chip">DVFS {ip.dvfsGroup ?? '—'}</span>
          <span className="chip">{LANE_LABEL[ip.lane]}</span>
          <span className="faint" style={{ fontSize: 12 }}>← {inputs.join(', ') || '—'} · → {outputs.join(', ') || '—'}</span>
          <span className="grow" />
          {ip.type !== 'sw' && <b className="mono" style={{ fontSize: 11 }}>RDMA {ip.rdma.used}{ip.rdma.total !== null ? `/${ip.rdma.total}` : ''} · WDMA {ip.wdma.used}{ip.wdma.total !== null ? `/${ip.wdma.total}` : ''} 사용</b>}
        </div>
        <div className="ipv-legend">
          <b className="faint" style={{ fontSize: 11 }}>전달 경로 (선)</b>
          {(['OTF', 'DMA', 'SW', 'off'] as PathKind[]).map((k) => <span key={k} className="legend-item"><svg width="24" height="8"><line x1="1" y1="4" x2="23" y2="4" stroke={PATH_STYLE[k].stroke} strokeWidth={PATH_STYLE[k].width} strokeDasharray={PATH_STYLE[k].dash} /></svg>{PATH_STYLE[k].label}</span>)}
          <span className="vsep" />
          <b className="faint" style={{ fontSize: 11 }}>데이터 종류 (칸 색 · tag)</b>
          {(['image', 'stat', 'history', 'trigger'] as DataKind[]).map((k) => <span key={k} className="legend-item"><span style={{ fontSize: 10, fontWeight: 700, color: DATA_STYLE[k].tagColor, background: DATA_STYLE[k].fill, border: '1px solid #D4D4D8', borderRadius: 3, padding: '0 4px' }}>{DATA_STYLE[k].tag}</span>{DATA_STYLE[k].label}</span>)}
          <span className="faint">예: stat WDMA = 주황 실선(DMA) + STAT · ↓/↑ = 입력 대비 출력 scale · 회색 점선 칸 = catalog에 있으나 이 variant 미사용</span>
        </div>
        <div className="ipv-svg"><IpDiagram ip={ip} /></div>
        <div className="ipv-table"><DataTable id="ip.ports" columns={portCols} rows={rows} rowKey={(p) => `${p.dir}|${p.port}|${p.buffer ?? ''}|${p.peer ?? ''}`} /></div>
      </section> : <div className="empty">IP 정보가 없습니다.</div>}
    </div>
  )
}
