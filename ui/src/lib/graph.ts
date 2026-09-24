// View (Level 1 projection) → hierarchical graph with explicit buffer nodes,
// laid out by ELK layered with orthogonal edge routing.
import type { Dict, ViewResponse, ViewNodeData, ViewEdgeData } from './api'
import type { PipelineModel } from './model'

export type NodeKind = 'ip' | 'sw' | 'buffer' | 'external' | 'group'
export type EdgeKind = 'OTF' | 'M2M' | 'control'

export interface GNode {
  id: string
  label: string
  kind: NodeKind
  group: string | null
  width: number
  height: number
  sub?: string            // secondary line (buffer size/format …)
  sub2?: string           // tertiary line (timing …)
  tone?: 'stat' | 'history' | 'optional' | 'warn'
  pipelineId?: string     // canonical pipeline node id (mcsc, gdc_o …) for timing linkage
  data?: ViewNodeData
  memory?: Dict | null
  bufferRef?: string
}

export interface GEdge {
  id: string
  source: string
  target: string
  kind: EdgeKind
  label?: string
  ports?: string
  count?: number
  faint?: boolean
}

export interface GGroup { id: string; label: string; count: number }

export interface Graph { nodes: GNode[]; edges: GEdge[]; groups: GGroup[] }

const RT = ['csis', 'pdp', 'byrp', 'rgbp', 'yuvsc', 'mlsc']
const NRT = ['mtnr', 'msnr', 'yuvp', 'mcsc']
const GROUP_LABEL: Record<string, string> = {
  'g:isp-front': 'ISP Front · RT OTF',
  'g:isp-nr': 'ISP NR · M2M',
  'g:lme': 'LME',
  'g:vps': 'VPS',
  'g:gdc': 'GDC',
  'g:codec': 'Codec',
  'g:display': 'Display',
  'g:sw': 'CPU · SW',
}

/** Canonical pipeline id from a view node id: ip-gdc-o → gdc_o, ip-sensor-rear → sensor_rear. */
export function pipelineIdOf(viewId: string): string {
  return viewId.replace(/^ip-/, '').replace(/-/g, '_')
}

export function isExternal(n: ViewNodeData): boolean {
  const ref = String(n.ip_ref ?? '')
  return /sensor|display-panel|panel/.test(ref) || /^(SENSOR|PANEL)\b/i.test(n.label)
}

function topGroupOf(n: ViewNodeData, byId: Map<string, ViewNodeData>): string | null {
  let cur: ViewNodeData | undefined = n
  let top: string | null = null
  while (cur?.parent) { top = cur.parent; cur = byId.get(cur.parent) }
  return top
}

export function groupOf(n: ViewNodeData, byId: Map<string, ViewNodeData>): string | null {
  if (n.type === 'sw') return 'g:sw'
  if (isExternal(n)) return null
  const pid = pipelineIdOf(n.id)
  if (RT.includes(pid)) return 'g:isp-front'
  if (NRT.includes(pid)) return 'g:isp-nr'
  if (pid === 'lme') return 'g:lme'
  const top = topGroupOf(n, byId) ?? ''
  const key = top.replace(/^grp-/, '')
  if (key.startsWith('vps')) return 'g:vps'
  if (key.startsWith('gdc')) return 'g:gdc'
  if (key.startsWith('codec')) return 'g:codec'
  if (key.startsWith('display')) return 'g:display'
  if (key.startsWith('isp')) return 'g:isp-nr'
  return key ? `g:${key}` : null
}

export function memoryText(mem: Dict | null | undefined): string {
  if (!mem) return ''
  const size = mem.width && mem.height ? `${mem.width}×${mem.height}` : ''
  const fmt = mem.format ? String(mem.format).replace('YUV', '') : ''
  const bit = mem.bitdepth ? `${mem.bitdepth}b` : ''
  const comp = mem.compression && mem.compression !== 'COMP_OFF' ? String(mem.compression).replace('COMP_', '') : ''
  return [size, fmt, bit, comp].filter(Boolean).join(' ')
}

const shortBuffer = (ref: string) => ref.replace(/^PYRAMID_/, 'PYR ').replace(/_INPUT$/, '_IN').replace(/_PREVIEW$/, '_PRV').replace(/_VIDEO$/, '_VID')

export function buildGraph(view: ViewResponse, collapsed: ReadonlySet<string> = new Set(), hiddenKinds: ReadonlySet<string> = new Set(), model?: PipelineModel | null): Graph {
  const all = view.nodes.map((n) => n.data)
  const byId = new Map(all.map((n) => [n.id, n]))
  const units = all.filter((n) => n.type === 'ip' || n.type === 'sw')
  const nodes = new Map<string, GNode>()
  const groupCount = new Map<string, number>()
  const alias = new Map<string, string>() // view id → rendered node id (collapsed groups)

  for (const n of units) {
    const group = groupOf(n, byId)
    if (group) groupCount.set(group, (groupCount.get(group) ?? 0) + 1)
    if (group && collapsed.has(group)) { alias.set(n.id, group); continue }
    const kind: NodeKind = n.type === 'sw' ? 'sw' : isExternal(n) ? 'external' : 'ip'
    if (kind === 'sw' && hiddenKinds.has('sw')) continue
    alias.set(n.id, n.id)
    const ipm = model?.byPid.get(pipelineIdOf(n.id))
    const io = ipm && kind === 'ip' && !hiddenKinds.has('buffer') ? [ipm.inSize, ipm.outSizes.filter((o) => o !== ipm.inSize).join(' / ')].filter(Boolean).join(' → ') : ''
    nodes.set(n.id, {
      sub: io || undefined,
      id: n.id, label: n.label.replace(/ /g, '_').replace(/_(ENC|REAR)$/, (m) => ' ' + m.slice(1)).replace(/_/g, ' '),
      kind, group, width: kind === 'sw' ? 108 : kind === 'external' ? 128 : io ? 150 : 108, height: kind === 'sw' ? 24 : kind === 'external' ? 32 : io ? 34 : 28,
      pipelineId: pipelineIdOf(n.id), data: n,
    })
  }
  for (const g of collapsed) {
    if (!groupCount.has(g)) continue
    nodes.set(g, { id: g, label: `${GROUP_LABEL[g] ?? g} (${groupCount.get(g)})`, kind: 'group', group: null, width: 170, height: 30 })
  }

  const edges: GEdge[] = []
  const seen = new Set<string>()
  const push = (e: GEdge) => {
    if (e.source === e.target || !nodes.has(e.source) || !nodes.has(e.target)) return
    const key = `${e.source}|${e.target}|${e.kind}`
    if (seen.has(key)) return
    seen.add(key)
    edges.push(e)
  }
  for (const { data: e } of view.edges as { data: ViewEdgeData }[]) {
    const src = alias.get(e.source)
    const dst = alias.get(e.target)
    if (!src || !dst) continue
    const kind: EdgeKind = e.flow_type === 'M2M' ? 'M2M' : e.flow_type === 'control' ? 'control' : 'OTF'
    if (kind === 'control' && hiddenKinds.has('control')) continue
    const ports = (e.port_pairs ?? []).map((p) => `${p.src}→${p.dst}`).join(', ')
    if (kind === 'M2M' && e.buffer_ref && !hiddenKinds.has('buffer')) {
      const bid = `buf:${e.buffer_ref}`
      if (!nodes.has(bid)) {
        const b = model?.buffers.find((x) => x.name === e.buffer_ref)
        const rate = b && b.mbFrame !== null ? `${b.mbFrame} MB/f${b.wMBs !== null ? ` · ${((b.wMBs ?? 0) + (b.rMBs ?? 0)).toFixed(0)} MB/s` : ''}` : b?.kind === 'stat' ? 'stat · size 미정' : ''
        nodes.set(bid, { id: bid, label: shortBuffer(e.buffer_ref), kind: 'buffer', group: null, width: 140, height: rate ? 40 : 30,
          sub: memoryText(e.memory) || (b?.kind === 'stat' ? 'stat' : ''), sub2: rate || undefined, tone: b?.kind === 'stat' ? 'stat' : undefined, memory: e.memory, bufferRef: e.buffer_ref })
      }
      push({ id: `${e.id}:w`, source: src, target: bid, kind, ports })
      push({ id: `${e.id}:r`, source: bid, target: dst, kind, ports })
    } else {
      push({ id: e.id, source: src, target: dst, kind, label: kind === 'M2M' ? e.buffer_ref ?? undefined : undefined, ports })
    }
  }
  // history (prev-frame) and catalogued stat / optional DMA buffers from the definition
  if (model && !hiddenKinds.has('buffer')) {
    const byPidId = new Map([...nodes.values()].filter((n) => n.pipelineId).map((n) => [n.pipelineId!, n.id]))
    for (const b of model.buffers) {
      if (b.kind === 'data' || nodes.has(`buf:${b.name}`)) continue
      if (view.edges.some((e) => e.data.buffer_ref === b.name)) continue
      const owner = byPidId.get(b.producerPid)
      if (!owner) continue
      const bid = `buf:${b.name}`
      const mem = { width: b.width, height: b.height, format: b.format, bitdepth: b.bit, compression: b.comp }
      nodes.set(bid, { id: bid, label: shortBuffer(b.name), kind: 'buffer', group: null, width: 140, height: 40, bufferRef: b.name, memory: mem,
        sub: memoryText(mem) || (b.kind === 'stat' ? 'stat · size 미정' : ''),
        sub2: b.kind === 'history' ? `history f-1${b.mbFrame !== null ? ` · ${b.mbFrame} MB/f` : ''}` : b.kind === 'optional' ? 'optional · off' : b.mbFrame !== null ? `${b.mbFrame} MB/f` : 'stat',
        tone: b.kind })
      if (b.kind === 'history') {
        if (b.wPorts.length) push({ id: `${bid}:hw`, source: owner, target: bid, kind: 'M2M', ports: b.wPorts.join(', ') })
        push({ id: `${bid}:hr`, source: bid, target: owner, kind: 'M2M', ports: b.rPorts.join(', ') })
      } else push({ id: `${bid}:w`, source: owner, target: bid, kind: 'M2M', ports: b.wPorts.join(', ') })
    }
  }
  const groups = [...groupCount.entries()].map(([id, count]) => ({ id, label: GROUP_LABEL[id] ?? id.replace(/^g:/, ''), count }))
  return { nodes: [...nodes.values()], edges, groups }
}

// ---------------------------------------------------------------------------
// ELK layout
// ---------------------------------------------------------------------------

export interface Placed extends GNode { x: number; y: number }
export interface PlacedGroup extends GGroup { x: number; y: number; width: number; height: number }
export interface PlacedEdge extends GEdge { points: { x: number; y: number }[] }
export interface LaneBand { id: string; label: string; y: number; height: number }
export interface PhaseBand { x: number; width: number; label: string; tone: number; sub?: string }
export interface Layout { nodes: Placed[]; groups: PlacedGroup[]; edges: PlacedEdge[]; width: number; height: number; lanes?: LaneBand[]; bands?: PhaseBand[]; headerH?: number; laneLabelW?: number }

interface ElkNode { id: string; x?: number; y?: number; width?: number; height?: number; children?: ElkNode[]; edges?: ElkEdge[]; layoutOptions?: Record<string, string>; labels?: { text: string }[] }
interface ElkEdge { id: string; sources: string[]; targets: string[]; sections?: { startPoint: { x: number; y: number }; endPoint: { x: number; y: number }; bendPoints?: { x: number; y: number }[] }[]; container?: string }

export interface ElkOptions { stackColumns?: number }

/**
 * Buffers written by the same producer all land in one ELK layer, which makes the
 * graph very wide (MLSC → 9 buffers). Stack them into `stackColumns` columns with
 * invisible ordering edges so the pipeline stays tall and narrow (split view).
 */
function stackingEdges(graph: Graph, cols: number): ElkEdge[] {
  if (cols <= 0) return []
  const byProducer = new Map<string, string[]>()
  for (const e of graph.edges) {
    if (!e.target.startsWith('buf:')) continue
    const list = byProducer.get(e.source) ?? []
    if (!list.includes(e.target)) list.push(e.target)
    byProducer.set(e.source, list)
  }
  const out: ElkEdge[] = []
  for (const [p, bufs] of byProducer) {
    if (bufs.length <= cols) continue
    bufs.forEach((b, i) => {
      if (i + cols < bufs.length) out.push({ id: `inv:${p}:${i}`, sources: [b], targets: [bufs[i + cols]] })
    })
  }
  return out
}

export function toElk(graph: Graph, opts: ElkOptions = {}): ElkNode {
  const byGroup = new Map<string, GNode[]>()
  const root: ElkNode[] = []
  for (const n of graph.nodes) {
    const el: ElkNode = { id: n.id, width: n.width, height: n.height }
    if (n.group && n.kind !== 'group') {
      if (!byGroup.has(n.group)) byGroup.set(n.group, [])
      byGroup.get(n.group)!.push(n)
    } else root.push(el)
  }
  for (const [g, members] of byGroup) {
    root.push({
      id: g,
      layoutOptions: { 'elk.padding': '[top=26,left=12,bottom=12,right=12]' },
      children: members.map((m) => ({ id: m.id, width: m.width, height: m.height })),
    })
  }
  return {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'DOWN',
      'elk.edgeRouting': 'ORTHOGONAL',
      'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
      'elk.layered.spacing.nodeNodeBetweenLayers': '34',
      'elk.spacing.nodeNode': '18',
      'elk.layered.spacing.edgeNodeBetweenLayers': '14',
      'elk.spacing.edgeEdge': '10',
      'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
      'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
      'elk.padding': '[top=16,left=16,bottom=16,right=16]',
    },
    children: root,
    edges: [...graph.edges.map((e) => ({ id: e.id, sources: [e.source], targets: [e.target] })), ...stackingEdges(graph, opts.stackColumns ?? 0)],
  }
}

type ElkApi = { layout: (g: ElkNode) => Promise<ElkNode> }
let elkPromise: Promise<ElkApi> | null = null
async function elk(): Promise<ElkApi> {
  if (!elkPromise) {
    elkPromise = import('elkjs/lib/elk.bundled.js').then((m) => {
      const Ctor = (m as unknown as { default: new () => ElkApi }).default
      return new Ctor()
    })
  }
  return elkPromise
}

export function fromElk(graph: Graph, laid: ElkNode): Layout {
  const abs = new Map<string, { x: number; y: number }>()
  const nodes: Placed[] = []
  const groups: PlacedGroup[] = []
  const gById = new Map(graph.nodes.map((n) => [n.id, n]))
  const gGroups = new Map(graph.groups.map((g) => [g.id, g]))
  const walk = (n: ElkNode, ox: number, oy: number) => {
    const x = ox + (n.x ?? 0)
    const y = oy + (n.y ?? 0)
    abs.set(n.id, { x, y })
    if (n.id !== 'root') {
      const gn = gById.get(n.id)
      if (gn) nodes.push({ ...gn, x, y })
      else if (gGroups.has(n.id)) groups.push({ ...gGroups.get(n.id)!, x, y, width: n.width ?? 0, height: n.height ?? 0 })
    }
    for (const c of n.children ?? []) walk(c, x, y)
  }
  walk(laid, -(laid.x ?? 0), -(laid.y ?? 0))
  const edgeMeta = new Map(graph.edges.map((e) => [e.id, e]))
  const edges: PlacedEdge[] = []
  const collect = (n: ElkNode) => {
    for (const e of n.edges ?? []) {
      const meta = edgeMeta.get(e.id)
      const s = e.sections?.[0]
      if (!meta || !s) continue
      const off = abs.get(e.container ?? n.id) ?? { x: 0, y: 0 }
      const pts = [s.startPoint, ...(s.bendPoints ?? []), s.endPoint].map((p) => ({ x: p.x + off.x, y: p.y + off.y }))
      edges.push({ ...meta, points: pts })
    }
    for (const c of n.children ?? []) collect(c)
  }
  collect(laid)
  return { nodes, groups, edges, width: laid.width ?? 800, height: laid.height ?? 600 }
}

export async function layoutGraph(graph: Graph, opts: ElkOptions = {}): Promise<Layout> {
  const engine = await elk()
  const laid = await engine.layout(toElk(graph, opts))
  return fromElk(graph, laid)
}

export function edgePath(points: { x: number; y: number }[]): string {
  return points.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')
}

// ---------------------------------------------------------------------------
// DMA table rows (buffer centric)
// ---------------------------------------------------------------------------

export interface DmaRow { buffer: string; producer: string; consumer: string; ports: string; size: string; format: string; bit: string; compression: string; mb: number | null }

const PLANE: Record<string, number> = { Y: 1, BAYER: 1, RAW_BAYER: 1, YUV420: 1.5, YUV422: 2, YUV444: 3, RGB: 3, RGBA8888: 4, RGBA1010102: 4 }

export function frameMb(mem: Dict | null | undefined): number | null {
  if (!mem) return null
  if (typeof mem.size_bytes === 'number') return +(mem.size_bytes / 1048576).toFixed(2)
  const w = Number(mem.width), h = Number(mem.height)
  const fmt = String(mem.format ?? '').toUpperCase()
  const f = PLANE[fmt]
  if (!w || !h || !f) return null
  const bytes = fmt.startsWith('RGBA') ? 4 * w * h : w * h * f * (Number(mem.bitdepth ?? 8) > 8 ? 2 : 1)
  return +(bytes / 1048576).toFixed(2)
}

export function dmaRows(view: ViewResponse): DmaRow[] {
  const label = new Map(view.nodes.map((n) => [n.data.id, n.data.label]))
  return view.edges.map((e) => e.data).filter((e) => e.flow_type === 'M2M').map((e) => {
    const mem = e.memory ?? {}
    return {
      buffer: e.buffer_ref ?? '—',
      producer: label.get(e.source) ?? e.source,
      consumer: label.get(e.target) ?? e.target,
      ports: (e.port_pairs ?? []).map((p) => `${p.src} → ${p.dst}`).join(', '),
      size: mem.width && mem.height ? `${mem.width}×${mem.height}` : '',
      format: String(mem.format ?? ''),
      bit: mem.bitdepth ? String(mem.bitdepth) : '',
      compression: String(mem.compression ?? ''),
      mb: frameMb(mem),
    }
  }).sort((a, b) => a.producer.localeCompare(b.producer) || a.buffer.localeCompare(b.buffer))
}
