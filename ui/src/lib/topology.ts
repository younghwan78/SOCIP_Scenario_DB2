// IP connection overview: lanes as columns, chain (longest-path) order top→down inside a lane.
import { LANE_ORDER, type IpLink, type IpModel, type Lane, type PipelineModel } from './model'

export const TOPO = { W: 122, H: 50, COL: 38, ROW: 16, TOP: 30, LEFT: 8 }

export interface TopoNode { ip: IpModel; x: number; y: number; col: number; rank: number }
export interface TopoLane { lane: Lane; x: number; w: number }
export interface TopoLayout { nodes: TopoNode[]; lanes: TopoLane[]; links: IpLink[]; width: number; height: number }

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

/** Lanes are columns (sensor → RT → SW → NRT → M2M → codec → display); inside a lane IPs run top→down by rank. */
export function topoLayout(model: PipelineModel): TopoLayout {
  const ips = model.ips
  const rank = ranks(ips.map((i) => i.pid), model.links)
  const lanes: TopoLane[] = []
  const nodes: TopoNode[] = []
  let depth = 0
  for (const lane of LANE_ORDER) {
    const inLane = ips.filter((i) => i.lane === lane).sort((a, b) => (rank.get(a.pid) ?? 0) - (rank.get(b.pid) ?? 0) || a.label.localeCompare(b.label))
    if (!inLane.length) continue
    const col = lanes.length
    const x = TOPO.LEFT + col * (TOPO.W + TOPO.COL)
    inLane.forEach((ip, k) => nodes.push({ ip, col, rank: rank.get(ip.pid) ?? 0, x, y: TOPO.TOP + k * (TOPO.H + TOPO.ROW) }))
    lanes.push({ lane, x, w: TOPO.W })
    depth = Math.max(depth, inLane.length)
  }
  const width = Math.max(TOPO.W, TOPO.LEFT * 2 + lanes.length * (TOPO.W + TOPO.COL) - TOPO.COL)
  return { nodes, lanes, links: model.links, width, height: TOPO.TOP + depth * (TOPO.H + TOPO.ROW) - TOPO.ROW + 30 }
}

/** SVG path between two nodes: forward across lanes, down within a lane, or a looping back edge. */
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
  // back edge (e.g. M2M accel → CPU task): leave from the bottom, enter from below
  const x1 = a.x + W / 2, y1 = a.y + H, x2 = b.x + W / 2, y2 = b.y + H, low = Math.max(y1, y2) + 26
  return `M${x1} ${y1} C ${x1} ${low}, ${x2} ${low}, ${x2} ${y2}`
}

/** Stable categorical colours for a key set; unknown values stay grey. */
export const DOMAIN_PALETTE = ['#0072B2', '#E69F00', '#009E73', '#CC79A7', '#56B4E9', '#D55E00', '#8C6BB1', '#7A8B2A']
export function colorMap(values: (string | undefined)[]): Map<string, string> {
  const uniq = [...new Set(values.filter((v): v is string => !!v))].sort()
  return new Map(uniq.map((v, i) => [v, DOMAIN_PALETTE[i % DOMAIN_PALETTE.length]]))
}
