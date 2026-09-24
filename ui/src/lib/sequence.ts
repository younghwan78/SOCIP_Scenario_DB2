// Sequence lens: Sensor → Panel/Storage HW/SW execution order as a swimlane.
// Column = execution step. OTF edges keep producer/consumer in the same step
// (streaming, same frame time); M2M and SW control edges advance one step.
// So RT OTF chain = one column, SW hand-offs (3A / ME / EIS) appear exactly
// where they gate the next HW stage.
import type { ViewResponse } from './api'
import type { GEdge, GNode, Layout, Placed, PlacedEdge } from './graph'
import { pipelineIdOf, isExternal } from './graph'
import { LANE_LABEL, LANE_ORDER, laneOf, chains, type Lane, type PipelineModel } from './model'
import type { StageTiming } from './cadence'
import type { ScenarioDef } from './api'

export const SEQ = { laneLabelW: 96, headerH: 44, nodeW: 118, nodeH: 36, swH: 36, gapY: 8, colGap: 42, lanePad: 12 }

export interface SeqOptions {
  showSw: boolean
  timing?: Map<string, StageTiming>
  model?: PipelineModel | null
  scenario?: ScenarioDef | null
  /** pane width (px): columns shrink (down to MIN_COL) so the sequence fits without horizontal scroll */
  fitWidth?: number
  /** pipeline ids executed inside a SW stage (sw_timing.includes_hw_nodes) → same step as that stage */
  merged?: Map<string, string>
}
const MIN_NODE_W = 82, MIN_GAP = 22

const fmt = (x: number) => (x >= 10 ? x.toFixed(1) : x.toFixed(2))

/** Longest-path rank with OTF weight 0, others 1. Back edges (cycles) ignored. */
export function sequenceRanks(ids: string[], edges: { source: string; target: string; kind: string }[]): Map<string, number> {
  const out = new Map<string, { t: string; w: number }[]>()
  const indeg = new Map(ids.map((i) => [i, 0]))
  for (const e of edges) {
    if (!indeg.has(e.source) || !indeg.has(e.target) || e.source === e.target) continue
    out.set(e.source, [...(out.get(e.source) ?? []), { t: e.target, w: e.kind === 'OTF' ? 0 : 1 }])
    indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1)
  }
  const rank = new Map(ids.map((i) => [i, 0]))
  const queue = ids.filter((i) => indeg.get(i) === 0)
  const seen = new Set<string>()
  while (queue.length) {
    const n = queue.shift()!
    seen.add(n)
    for (const { t, w } of out.get(n) ?? []) {
      rank.set(t, Math.max(rank.get(t)!, rank.get(n)! + w))
      indeg.set(t, indeg.get(t)! - 1)
      if (indeg.get(t) === 0) queue.push(t)
    }
  }
  // nodes in cycles: place after their highest ranked resolved predecessor
  for (const i of ids) if (!seen.has(i)) {
    let r = 0
    for (const e of edges) if (e.target === i && seen.has(e.source)) r = Math.max(r, rank.get(e.source)! + (e.kind === 'OTF' ? 0 : 1))
    rank.set(i, r)
  }
  return rank
}

function phaseLabel(lanes: Set<Lane>, col: number, firstNrt: number, lastNrt: number): { label: string; tone: number } {
  if (lanes.has('rt') || (lanes.has('sensor') && firstNrt >= 0 && col < firstNrt && lanes.size === 1)) return { label: 'RT · sensor V-sync (OTF)', tone: 0 }
  if (lanes.has('nrt')) return { label: 'NRT (M2M)', tone: 2 }
  if (firstNrt >= 0 && col < firstNrt) return { label: 'RT → NRT hand-off', tone: 1 }
  if (lanes.has('codec') || lanes.has('display')) return { label: 'Output', tone: 4 }
  if (lastNrt >= 0 && col > lastNrt) return { label: 'NRT 이후', tone: 3 }
  return { label: '', tone: 5 }
}

export function sequenceLayout(view: ViewResponse, opts: SeqOptions): Layout {
  const ch = chains(opts.scenario)
  const units = view.nodes.map((n) => n.data).filter((n) => n.type === 'ip' || n.type === 'sw')
  const order = new Map(units.map((n, i) => [n.id, i]))
  const rawEdges = view.edges.map((e) => e.data).filter((e) => order.has(e.source) && order.has(e.target))
  // HW executed inside a SW stage (e.g. preME includes LME) shares that stage's step
  const idOfPid = new Map(units.map((n) => [pipelineIdOf(n.id), n.id]))
  const inside = new Set<string>()
  for (const [hw, sw] of opts.merged ?? []) { const a = idOfPid.get(sw), b = idOfPid.get(hw); if (a && b) inside.add(`${a}|${b}`) }
  const rank = sequenceRanks(units.map((n) => n.id), rawEdges.map((e) => ({ source: e.source, target: e.target,
    kind: inside.has(`${e.source}|${e.target}`) ? 'OTF' : e.flow_type === 'M2M' ? 'M2M' : e.flow_type === 'control' ? 'control' : 'OTF' })))
  const visible = units.filter((n) => opts.showSw || n.type !== 'sw')
  const lane = new Map(visible.map((n) => [n.id, laneOf(n, ch)]))
  const usedRanks = [...new Set(visible.map((n) => rank.get(n.id)!))].sort((a, b) => a - b)
  const col = new Map(usedRanks.map((r, i) => [r, i]))
  const lanes = LANE_ORDER.filter((l) => visible.some((n) => lane.get(n.id) === l))

  // stack per (lane, col) — keep pipeline order (OTF chain order)
  const cells = new Map<string, string[]>()
  for (const n of [...visible].sort((a, b) => order.get(a.id)! - order.get(b.id)!)) {
    const k = `${lane.get(n.id)}|${col.get(rank.get(n.id)!)}`
    cells.set(k, [...(cells.get(k) ?? []), n.id])
  }
  const laneRows = new Map<Lane, number>(lanes.map((l) => [l, Math.max(1, ...[...cells.entries()].filter(([k]) => k.startsWith(`${l}|`)).map(([, v]) => v.length))]))
  const x0 = SEQ.laneLabelW + 18
  const fullColW = SEQ.nodeW + SEQ.colGap
  const fitColW = opts.fitWidth ? (opts.fitWidth - x0 - 24 + MIN_GAP) / Math.max(1, usedRanks.length) : fullColW
  const colW = Math.max(MIN_NODE_W + MIN_GAP, Math.min(fullColW, fitColW))
  const nodeW = Math.round(Math.max(MIN_NODE_W, Math.min(SEQ.nodeW, colW - Math.max(MIN_GAP, colW * 0.24))))
  let y = SEQ.headerH
  const laneY = new Map<Lane, { y: number; h: number }>()
  for (const l of lanes) {
    const h = laneRows.get(l)! * (SEQ.nodeH + SEQ.gapY) - SEQ.gapY + SEQ.lanePad * 2
    laneY.set(l, { y, h })
    y += h
  }
  const height = y + 10
  const width = x0 + usedRanks.length * colW - (colW - nodeW) + 24

  const nodes: Placed[] = []
  for (const [k, ids] of cells) {
    const [l, c] = k.split('|')
    const ly = laneY.get(l as Lane)!
    const stackH = ids.length * (SEQ.nodeH + SEQ.gapY) - SEQ.gapY
    ids.forEach((id, i) => {
      const n = units[order.get(id)!]
      const pid = pipelineIdOf(n.id)
      const ip = opts.model?.byPid.get(pid)
      const t = opts.timing?.get(pid)
      const kind: GNode['kind'] = n.type === 'sw' ? 'sw' : isExternal(n) ? 'external' : 'ip'
      let sub = ''
      if (t) sub = `+${fmt(t.offset)} · ${fmt(t.dur)}ms`
      else if (ip?.sw?.mean !== undefined) sub = `${fmt(ip.sw.mean)}ms (${ip.sw.min ?? '?'}–${ip.sw.max ?? '?'})`
      const sub2 = ip && kind !== 'sw' ? (ip.inSize ? ip.inSize : '') : ip?.sw?.source ? `sw ${ip.sw.source}` : ''
      nodes.push({
        id: n.id, label: n.label, kind, group: null, width: nodeW, height: SEQ.nodeH, pipelineId: pid, data: n,
        sub: sub || sub2, sub2: sub ? sub2 : undefined,
        x: x0 + Number(c) * colW, y: ly.y + (ly.h - stackH) / 2 + i * (SEQ.nodeH + SEQ.gapY),
      })
    })
  }
  const pos = new Map(nodes.map((n) => [n.id, n]))

  // edges: collapse parallel (same src/dst/type) with count + buffer list
  const agg = new Map<string, GEdge & { bufs: string[] }>()
  for (const e of rawEdges) {
    if (!pos.has(e.source) || !pos.has(e.target)) continue
    const kind = e.flow_type === 'M2M' ? 'M2M' : e.flow_type === 'control' ? 'control' : 'OTF'
    const k = `${e.source}|${e.target}|${kind}`
    const cur = agg.get(k) ?? { id: k, source: e.source, target: e.target, kind, count: 0, bufs: [] as string[] }
    cur.count = (cur.count ?? 0) + 1
    if (e.buffer_ref) cur.bufs.push(e.buffer_ref)
    agg.set(k, cur)
  }
  const outIdx = new Map<string, number>()
  const edges: PlacedEdge[] = [...agg.values()].map((e) => {
    const a = pos.get(e.source)!, b = pos.get(e.target)!
    const ports = e.bufs.length ? e.bufs.join(', ') : e.kind
    let points: { x: number; y: number }[]
    if (Math.abs(a.x - b.x) < 1) {
      // same step: vertical (OTF streaming inside the column)
      const down = b.y > a.y
      const off = e.kind === 'OTF' ? 0 : 10
      points = [{ x: a.x + a.width / 2 + off, y: down ? a.y + a.height : a.y }, { x: b.x + b.width / 2 + off, y: down ? b.y : b.y + b.height }]
    } else {
      const k = outIdx.get(e.source) ?? 0
      outIdx.set(e.source, k + 1)
      const sx = a.x + a.width, sy = a.y + a.height / 2 + (e.kind === 'control' ? 5 : e.kind === 'M2M' ? -5 : 0)
      const tx = b.x, ty = b.y + b.height / 2 + (e.kind === 'control' ? 5 : e.kind === 'M2M' ? -5 : 0)
      const gap = colW - nodeW
      const mx = b.x > a.x ? Math.min(tx - 8, sx + Math.min(14, gap / 2) + (k % 4) * Math.min(6, gap / 8)) : sx + 10
      points = b.x > a.x ? [{ x: sx, y: sy }, { x: mx, y: sy }, { x: mx, y: ty }, { x: tx, y: ty }]
        : [{ x: sx, y: sy }, { x: sx + 14, y: sy }, { x: sx + 14, y: Math.max(a.y, b.y) + SEQ.nodeH + 6 }, { x: tx - 14, y: Math.max(a.y, b.y) + SEQ.nodeH + 6 }, { x: tx - 14, y: ty }, { x: tx, y: ty }]
    }
    return { id: e.id, source: e.source, target: e.target, kind: e.kind, ports, count: e.count, faint: e.kind === 'M2M', label: e.count && e.count > 1 ? `×${e.count}` : undefined, points }
  })

  // phase bands over columns
  const colLanes = usedRanks.map(() => new Set<Lane>())
  for (const n of nodes) colLanes[Math.round((n.x - x0) / colW)].add(lane.get(n.id)!)
  const nrtCols = colLanes.map((s, i) => (s.has('nrt') ? i : -1)).filter((i) => i >= 0)
  const firstNrt = nrtCols.length ? nrtCols[0] : -1, lastNrt = nrtCols.length ? nrtCols[nrtCols.length - 1] : -1
  const bands: Layout['bands'] = []
  let seenOutput = false
  colLanes.forEach((s, i) => {
    let p = phaseLabel(s, i, firstNrt, lastNrt)
    if (p.tone === 4) seenOutput = true
    else if (seenOutput && p.tone === 3) p = { label: 'Output 이후 · SW', tone: 5 }
    const t = [...nodes].filter((n) => Math.round((n.x - x0) / colW) === i).map((n) => opts.timing?.get(n.pipelineId ?? ''))
      .filter((v): v is StageTiming => !!v)
    const sub = t.length ? `+${fmt(Math.min(...t.map((v) => v.offset)))}–${fmt(Math.max(...t.map((v) => v.offset + v.dur)))}ms` : undefined
    const last = bands[bands.length - 1]
    if (last && last.label === p.label && p.label) { last.width += colW; if (sub && last.sub) last.sub = `${last.sub.split('–')[0]}–${sub.split('–')[1]}`; else if (sub) last.sub = sub }
    else bands.push({ x: x0 + i * colW - (colW - nodeW) / 2 + 4, width: colW, label: p.label, tone: p.tone, sub })
  })
  return {
    nodes, edges, groups: [], width, height, bands, headerH: SEQ.headerH, laneLabelW: SEQ.laneLabelW,
    lanes: lanes.map((l) => ({ id: l, label: LANE_LABEL[l], ...laneY.get(l)! })).map((l) => ({ id: l.id, label: l.label, y: l.y, height: l.h })),
  }
}
