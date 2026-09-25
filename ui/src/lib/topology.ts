// IP connection overview. Columns follow the data path:
//   Sensor → ISP RT → Pre-NRT (CPU SW · M2M accel) → ISP NRT → Post-NRT (CPU SW · M2M accel) → Codec → Display
// CPU tasks and M2M accelerators are split by where they sit relative to ISP NRT (longest-path rank),
// so RTA / LME / VPS land before NRT and EIS / writers / GDC / M2M scaler after it.
import type { IpLink, IpModel, Lane, PipelineModel } from './model'

export const TOPO = { W: 122, H: 50, COL: 38, ROW: 14, TOP: 30, LEFT: 8, SEC_HEAD: 18, SEC_GAP: 16 }

export type ColumnId = 'sensor' | 'rt' | 'pre' | 'nrt' | 'post' | 'codec' | 'display' | 'other'
export type SectionId = 'main' | 'sw' | 'm2m'
export interface TopoNode { ip: IpModel; x: number; y: number; col: number; rank: number; column: ColumnId; section: SectionId }
export interface TopoSection { id: SectionId; label: string; y: number; h: number }
export interface TopoColumn { id: ColumnId; label: string; x: number; w: number; sections: TopoSection[] }
export interface TopoGhost { label: string; note: string; x: number; y: number; column: ColumnId }
export interface TopoLayout { nodes: TopoNode[]; columns: TopoColumn[]; ghosts: TopoGhost[]; links: IpLink[]; width: number; height: number }

const COLUMN_LABEL: Record<ColumnId, string> = {
  sensor: 'Sensor', rt: 'ISP RT', pre: 'Pre-NRT', nrt: 'ISP NRT', post: 'Post-NRT', codec: 'Codec', display: 'Display', other: 'Other',
}
const SECTION_LABEL: Record<SectionId, string> = { main: '', sw: 'CPU SW', m2m: 'M2M accel' }
const COLUMN_ORDER: ColumnId[] = ['sensor', 'rt', 'pre', 'nrt', 'post', 'codec', 'display', 'other']
const DIRECT: Partial<Record<Lane, ColumnId>> = { sensor: 'sensor', rt: 'rt', nrt: 'nrt', codec: 'codec', display: 'display', other: 'other' }
/** Post-NRT M2M slot kept visible for scenarios that route through the M2M scaler. */
export const M2M_SCALER_RE = /(^|[_-])(m2msc|m2m[_-]?scaler|m2m[_-]?sc|msc)([_-]|$)|m2m-scaler/i

/** Longest-path rank over the IP links (cycles are cut by an iteration cap). */
export function ranks(ids: string[], links: IpLink[]): Map<string, number> {
  const r = new Map(ids.map((id) => [id, 0]))
  const es = links.filter((l) => l.from !== l.to && r.has(l.from) && r.has(l.to))
  for (let it = 0; it < ids.length; it++) {
    let changed = false
    for (const e of es) {
      const want = (r.get(e.from) ?? 0) + 1
      if (want > (r.get(e.to) ?? 0)) { r.set(e.to, want); changed = true }
    }
    if (!changed) break
  }
  return r
}

/** Which column / section an IP belongs to. SW and M2M split at the first ISP NRT rank. */
export function placeOf(ip: IpModel, rank: number, nrtStart: number | null): { column: ColumnId; section: SectionId } {
  const direct = DIRECT[ip.lane]
  if (direct) return { column: direct, section: 'main' }
  const section: SectionId = ip.lane === 'sw' ? 'sw' : 'm2m'
  const scaler = M2M_SCALER_RE.test(ip.pid) || M2M_SCALER_RE.test(ip.ipRef)
  const pre = !scaler && nrtStart !== null && rank < nrtStart
  return { column: pre ? 'pre' : 'post', section }
}

export function topoLayout(model: PipelineModel): TopoLayout {
  const ips = model.ips
  const rank = ranks(ips.map((i) => i.pid), model.links)
  const nrt = ips.filter((i) => i.lane === 'nrt').map((i) => rank.get(i.pid) ?? 0)
  const nrtStart = nrt.length ? Math.min(...nrt) : null
  const placed = ips.map((ip) => ({ ip, r: rank.get(ip.pid) ?? 0, ...placeOf(ip, rank.get(ip.pid) ?? 0, nrtStart) }))
  const hasScaler = ips.some((i) => M2M_SCALER_RE.test(i.pid) || M2M_SCALER_RE.test(i.ipRef))
  const camera = nrtStart !== null
  const columns: TopoColumn[] = []
  const nodes: TopoNode[] = []
  const ghosts: TopoGhost[] = []
  let bottom = TOPO.TOP
  for (const id of COLUMN_ORDER) {
    const inCol = placed.filter((p) => p.column === id)
    const wantGhost = id === 'post' && camera && !hasScaler
    if (!inCol.length && !wantGhost) continue
    const col = columns.length
    const x = TOPO.LEFT + col * (TOPO.W + TOPO.COL)
    const sectionIds: SectionId[] = id === 'pre' || id === 'post' ? ['sw', 'm2m'] : ['main']
    const sections: TopoSection[] = []
    let y = TOPO.TOP
    for (const sid of sectionIds) {
      const list = inCol.filter((p) => p.section === sid).sort((a, b) => a.r - b.r || a.ip.label.localeCompare(b.ip.label))
      const ghost = wantGhost && sid === 'm2m'
      if (!list.length && !ghost) continue
      const head = sid === 'main' ? 0 : TOPO.SEC_HEAD
      const top = y
      y += head
      for (const p of list) {
        nodes.push({ ip: p.ip, x, y, col, rank: p.r, column: id, section: sid })
        y += TOPO.H + TOPO.ROW
      }
      if (ghost) {
        ghosts.push({ label: 'M2M SCALER', note: '이 variant 미사용 · M2M scaler scenario 자리', x, y, column: id })
        y += TOPO.H + TOPO.ROW
      }
      sections.push({ id: sid, label: SECTION_LABEL[sid], y: top, h: y - TOPO.ROW - top })
      y += TOPO.SEC_GAP
    }
    columns.push({ id, label: COLUMN_LABEL[id], x, w: TOPO.W, sections })
    bottom = Math.max(bottom, y - TOPO.SEC_GAP - TOPO.ROW)
  }
  const width = Math.max(TOPO.W, TOPO.LEFT * 2 + columns.length * (TOPO.W + TOPO.COL) - TOPO.COL)
  return { nodes, columns, ghosts, links: model.links, width, height: Math.max(bottom, TOPO.TOP + TOPO.H) + 30 }
}

/** SVG path between two nodes: forward across columns, down within a column, or a looping back edge. */
export function linkPath(a: TopoNode, b: TopoNode): string {
  const { W, H } = TOPO
  if (a.col === b.col) {
    if (b.y > a.y) return `M${a.x + W / 2} ${a.y + H} L${b.x + W / 2} ${b.y}`
    const xr = a.x + W
    return `M${xr} ${a.y + H / 2} C ${xr + 30} ${a.y + H / 2}, ${xr + 30} ${b.y + H / 2}, ${xr} ${b.y + H / 2}`
  }
  if (b.col > a.col) {
    const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2, dx = Math.max(24, (x2 - x1) / 2)
    return `M${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`
  }
  // back edge (e.g. accelerator → earlier CPU task): leave from the bottom, enter from below
  const x1 = a.x + W / 2, y1 = a.y + H, x2 = b.x + W / 2, y2 = b.y + H, low = Math.max(y1, y2) + 26
  return `M${x1} ${y1} C ${x1} ${low}, ${x2} ${low}, ${x2} ${y2}`
}

/** Stable categorical colours for a key set; unknown values stay grey. */
export const DOMAIN_PALETTE = ['#0072B2', '#E69F00', '#009E73', '#CC79A7', '#56B4E9', '#D55E00', '#8C6BB1', '#7A8B2A']
export function colorMap(values: (string | undefined)[]): Map<string, string> {
  const uniq = [...new Set(values.filter((v): v is string => !!v))].sort()
  return new Map(uniq.map((v, i) => [v, DOMAIN_PALETTE[i % DOMAIN_PALETTE.length]]))
}
