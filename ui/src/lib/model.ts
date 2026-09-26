// Pipeline model = Level-1 view + scenario definition (buffers, history/stat DMA)
// + resolved variant (node_configs, size_overrides). Feeds the Sequence,
// DMA·Memory and IP-internal lenses. Never invents sizes: unknown stays null.
import type { BufferDef, Dict, IpCatalog, ScenarioDef, VariantDetail, ViewEdgeData, ViewNodeData, ViewResponse } from './api'
import { frameMb, isExternal, pipelineIdOf } from './graph'

export type Lane = 'sensor' | 'rt' | 'sw' | 'nrt' | 'm2m' | 'codec' | 'display' | 'other'
export const LANE_ORDER: Lane[] = ['sensor', 'rt', 'sw', 'nrt', 'm2m', 'codec', 'display', 'other']
export const LANE_LABEL: Record<Lane, string> = {
  sensor: 'Sensor', rt: 'ISP RT', sw: 'CPU · SW', nrt: 'ISP NRT', m2m: 'M2M accel', codec: 'Codec', display: 'Display', other: 'Other',
}

const RT_DEFAULT = ['csis', 'pdp', 'byrp', 'rgbp', 'yuvsc', 'mlsc']
const NRT_DEFAULT = ['mtnr', 'msnr', 'yuvp', 'mcsc']

export function chains(scn?: ScenarioDef | null): { rt: string[]; nrt: string[] } {
  const ag = (scn?.pipeline?.architecture_graph ?? {}) as Dict
  const rt = Array.isArray(ag.rt_chain) ? (ag.rt_chain as string[]) : RT_DEFAULT
  const nrt = Array.isArray(ag.nrt_chain) ? (ag.nrt_chain as string[]) : NRT_DEFAULT
  const strip = (p: string) => p.replace(/^front_/, '')
  return { rt: [...rt, ...rt.map((p) => `front_${strip(p)}`)], nrt: [...nrt, ...nrt.map((p) => `front_${strip(p)}`)] }
}

export function laneOf(n: ViewNodeData, ch: { rt: string[]; nrt: string[] }): Lane {
  const pid = pipelineIdOf(n.id)
  const ref = String(n.ip_ref ?? '')
  if (n.type === 'sw') return 'sw'
  if (/sensor/.test(ref) || pid.startsWith('sensor')) return 'sensor'
  if (ch.rt.includes(pid)) return 'rt'
  if (ch.nrt.includes(pid)) return 'nrt'
  if (/^(mfc|apv|codec|jpeg|hevc)/.test(pid) || /mfc|apv|codec/.test(ref)) return 'codec'
  if (/^(dpu|panel|decon|display)/.test(pid) || /dpu|panel|display/.test(ref) || isExternal(n)) return 'display'
  if (/^(lme|vps|gdc|g2d|npu|gpu|dsp|abox|m2msc|m2m_?sc|msc|m2m_?scaler)/.test(pid) || /m2m-scaler/.test(ref)) return 'm2m'
  return 'other'
}

export function parseSize(s: unknown): { w: number; h: number } | null {
  const m = String(s ?? '').match(/(\d+)\s*[x×]\s*(\d+)/i)
  return m ? { w: Number(m[1]), h: Number(m[2]) } : null
}
export const sizeText = (w?: unknown, h?: unknown) => (w && h ? `${w}×${h}` : '')

export type Via = 'OTF' | 'DMA' | 'history' | 'stat' | 'optional' | 'ctrl'
export interface Port {
  port: string
  dir: 'in' | 'out'
  via: Via
  buffer?: string
  peer?: string
  size?: string
  format?: string
  bit?: string
  comp?: string
  mb?: number | null
  enabled: boolean
  note?: string
  /** catalog channel not used in this variant */
  unused?: boolean
}

export interface SwTiming { min?: number; mean?: number; max?: number; source?: string }

/** One DMA/FIFO channel from the IP catalog (or used but not catalogued). */
export interface DmaChannel {
  name: string
  dir: 'in' | 'out'
  kind: 'DMA' | 'FIFO'
  status: 'used' | 'off' | 'unused'
  purpose?: string
  buffer?: string
  peer?: string
  catalogued: boolean
}

export interface IpModel {
  viewId: string
  pid: string
  label: string
  lane: Lane
  type: string
  ipRef: string
  inSize: string
  outSizes: string[]
  ops: string[]
  mode?: string
  flags: [string, string][]
  sw?: SwTiming
  ports: Port[]
  /** every DMA/FIFO channel of the IP (catalog ∪ used) with use status */
  channels: DmaChannel[]
  rdma: { used: number; total: number | null }
  wdma: { used: number; total: number | null }
  modes?: string[]
  /** BLK from catalog properties.blk/block; falls back to hierarchy_group (blkSource says which) */
  blk?: string
  blkSource?: 'blk' | 'hierarchy_group'
  /** voltage rail / DVFS group from catalog sim (selected mode first) */
  vdd?: string
  dvfsGroup?: string
}

export interface IpLink { from: string; to: string; kind: 'OTF' | 'M2M' | 'ctrl'; buffer?: string; mbs?: number | null }

export type BufferKind = 'data' | 'stat' | 'history' | 'optional'
export interface BufferRow {
  name: string
  kind: BufferKind
  producer: string
  producerPid: string
  consumers: string[]
  consumerPids: string[]
  wPorts: string[]
  rPorts: string[]
  width: number | null
  height: number | null
  format: string
  bit: string
  comp: string
  mbFrame: number | null
  fps: number | null
  wMBs: number | null
  rMBs: number | null
  enabled: boolean
  note: string
}

export interface PipelineModel {
  ips: IpModel[]
  byPid: Map<string, IpModel>
  /** IP-to-IP connections (pid level, one per edge) for the topology overview */
  links: IpLink[]
  buffers: BufferRow[]
  fps: number | null
  /** total DMA traffic (W+R, MB/s) over characterised buffers */
  totalMBs: number
  unknownBuffers: number
}

function opsOf(ops: Dict | null | undefined, cfg: Dict | undefined): string[] {
  const o = { ...((cfg?.operations as Dict | undefined) ?? {}), ...(ops ?? {}) } as Dict
  const out: string[] = []
  if (o.crop) out.push(o.crop_region ? `crop ${String(o.crop_region)}` : o.crop_ratio ? `crop ×${o.crop_ratio}` : 'crop')
  if (o.scale) out.push(typeof o.scale_ratio === 'number' ? `scale ×${(o.scale_ratio as number).toFixed(2)}` : o.scale_from && o.scale_to ? `scale ${o.scale_from}→${o.scale_to}` : 'scale')
  if (o.rotate) out.push(`rotate ${o.rotate}°`)
  if (o.colorspace_convert) out.push(`CSC ${o.colorspace_convert === true ? '' : String(o.colorspace_convert)}`.trim())
  if (o.compose) out.push('compose')
  if (cfg?.bypass_downscale) out.push('downscale bypass')
  return out
}

const FLAG_SKIP = new Set(['sim', 'operations', 'sw_timing', 'memory_io', 'source_note', 'stat_dma_note', 'active_output_ports', 'selected_mode', 'sw_bitrate_scaling'])

function flagsOf(cfg: Dict | undefined): [string, string][] {
  if (!cfg) return []
  return Object.entries(cfg).filter(([k, v]) => !FLAG_SKIP.has(k) && (typeof v !== 'object' || v === null)).map(([k, v]) => [k, String(v)])
}

function swTimingOf(cfg: Dict | undefined): SwTiming | undefined {
  const t = cfg?.sw_timing as Dict | undefined
  if (!t) return undefined
  const n = (x: unknown) => (typeof x === 'number' ? x : undefined)
  return { min: n(t.min_ms), mean: n(t.mean_ms), max: n(t.max_ms), source: t.value_source ? String(t.value_source) : undefined }
}

function bufSize(def: BufferDef | undefined, scn?: ScenarioDef | null, variant?: VariantDetail | null): { w: number; h: number } | null {
  if (!def?.size_ref) return null
  return parseSize(variant?.size_overrides?.[def.size_ref] ?? scn?.size_profile?.anchors?.[def.size_ref])
}

const isStatName = (n: string) => /HIST|SAT|DRC|STAT|_MV\b|RESULT/i.test(n)

export function buildModel(view: ViewResponse, scn?: ScenarioDef | null, variant?: VariantDetail | null, catalogs?: Map<string, IpCatalog>): PipelineModel {
  const ch = chains(scn)
  const units = view.nodes.map((n) => n.data).filter((n) => n.type === 'ip' || n.type === 'sw')
  const label = new Map(units.map((n) => [n.id, n.label]))
  const pidLabel = new Map(units.map((n) => [pipelineIdOf(n.id), n.label]))
  const active = new Set(units.map((n) => pipelineIdOf(n.id)))
  const cfgs = variant?.node_configs ?? {}
  const fps = Number(view.summary.fps ?? variant?.design_conditions?.fps ?? NaN)
  const vfps = Number.isFinite(fps) && fps > 0 ? fps : null
  const edges = view.edges.map((e) => e.data)
  const defs = scn?.pipeline?.buffers ?? {}

  // ---- buffers from view M2M edges (grouped by buffer_ref)
  const bufMap = new Map<string, BufferRow>()
  for (const e of edges) {
    if (e.flow_type !== 'M2M') continue
    const name = e.buffer_ref ?? `${e.source}→${e.target}`
    const mem = (e.memory ?? {}) as Dict
    let b = bufMap.get(name)
    if (!b) {
      const def = defs[name]
      const w = Number(mem.width) || null, h = Number(mem.height) || null
      const mb = frameMb(mem)
      const f = Number(mem.fps) || vfps
      const unknown = !w || !h || !mem.format
      b = { name, kind: unknown && (isStatName(name) || def?.size_status === 'unknown') ? 'stat' : unknown ? 'stat' : 'data',
        producer: label.get(e.source) ?? e.source, producerPid: pipelineIdOf(e.source), consumers: [], consumerPids: [], wPorts: [], rPorts: [],
        width: w, height: h, format: String(mem.format ?? def?.format ?? ''), bit: mem.bitdepth ? String(mem.bitdepth) : def?.bitdepth ? String(def.bitdepth) : '',
        comp: String(mem.compression ?? def?.compression ?? ''), mbFrame: mb, fps: f ?? null, wMBs: null, rMBs: null, enabled: true, note: def?.source_note ?? '' }
      bufMap.set(name, b)
    }
    const cons = label.get(e.target) ?? e.target
    if (!b.consumers.includes(cons)) { b.consumers.push(cons); b.consumerPids.push(pipelineIdOf(e.target)) }
    for (const p of e.port_pairs ?? []) {
      if (!b.wPorts.includes(p.src)) b.wPorts.push(p.src)
      if (!b.rPorts.includes(p.dst)) b.rPorts.push(p.dst)
    }
  }
  // ---- history + catalogued stat/optional DMA from the scenario definition
  for (const [name, def] of Object.entries(defs)) {
    if (bufMap.has(name)) continue
    const node = def.history?.node_id ?? def.dma?.node_id
    if (!node || !active.has(node)) continue
    const sz = bufSize(def, scn, variant)
    const mem = sz ? { width: sz.w, height: sz.h, format: def.format, bitdepth: def.bitdepth, compression: def.compression } : null
    const mb = frameMb(mem)
    const cfg = cfgs[node] as Dict | undefined
    let enabled = true
    if (def.dma?.enabled === false) enabled = false
    if (def.dma?.activation_flag) enabled = cfg?.[def.dma.activation_flag] === true
    const kind: BufferKind = def.history ? 'history' : !enabled ? 'optional' : (!sz || isStatName(name) || def.size_status === 'unknown') ? 'stat' : 'data'
    const nodeLabel = pidLabel.get(node) ?? node
    bufMap.set(name, {
      name, kind, producer: def.history ? `${nodeLabel} (f-1)` : nodeLabel, producerPid: node,
      consumers: def.history ? [nodeLabel] : [], consumerPids: def.history ? [node] : [],
      wPorts: def.history?.write_ports ?? def.dma?.write_ports ?? [], rPorts: def.history?.read_ports ?? def.dma?.read_ports ?? [],
      width: sz?.w ?? null, height: sz?.h ?? null, format: def.format ?? '', bit: def.bitdepth ? String(def.bitdepth) : '', comp: def.compression ?? '',
      mbFrame: mb, fps: vfps, wMBs: null, rMBs: null, enabled, note: def.source_note ?? (def.history ? `history · frame_offset ${def.history.frame_offset ?? -1}${def.history.producer ? ` · ${def.history.producer}` : ''}` : ''),
    })
  }
  let total = 0, unknown = 0
  for (const b of bufMap.values()) {
    if (b.mbFrame === null || !b.fps || !b.enabled) { if (b.enabled) unknown++; continue }
    const perFrame = b.mbFrame * b.fps
    b.wMBs = b.kind === 'history' && !b.wPorts.length ? 0 : perFrame
    b.rMBs = perFrame * Math.max(1, b.kind === 'history' ? 1 : b.consumers.length || (b.rPorts.length ? 1 : 0))
    if (b.kind !== 'history' && !b.consumers.length && !b.rPorts.length) b.rMBs = 0
    b.wMBs = +b.wMBs.toFixed(1); b.rMBs = +b.rMBs.toFixed(1)
    total += b.wMBs + b.rMBs
  }
  const buffers = [...bufMap.values()]

  // ---- per-IP model with ports
  const ips: IpModel[] = units.map((n) => {
    const pid = pipelineIdOf(n.id)
    const cfg = cfgs[pid] as Dict | undefined
    const sim = (cfg?.sim ?? {}) as Dict
    const ports: Port[] = []
    for (const e of edges) {
      const out = e.source === n.id, inn = e.target === n.id
      if (!out && !inn) continue
      const peer = label.get(out ? e.target : e.source) ?? (out ? e.target : e.source)
      if (e.flow_type === 'control') { ports.push({ port: out ? 'trigger →' : '← trigger', dir: out ? 'out' : 'in', via: 'ctrl', peer, enabled: true }); continue }
      if (e.flow_type === 'M2M') {
        const b = bufMap.get(e.buffer_ref ?? '')
        const pairs = e.port_pairs?.length ? e.port_pairs : [{ src: 'WDMA', dst: 'RDMA' }]
        for (const p of pairs) ports.push({ port: out ? p.src : p.dst, dir: out ? 'out' : 'in', via: b?.kind === 'stat' ? 'stat' : 'DMA', buffer: e.buffer_ref ?? undefined, peer,
          size: b ? sizeText(b.width, b.height) : '', format: b?.format, bit: b?.bit, comp: b?.comp, mb: b?.mbFrame ?? null, enabled: true })
        continue
      }
      const pairs = e.port_pairs?.length ? e.port_pairs : [{ src: 'OTF out', dst: 'OTF in' }]
      for (const p of pairs) ports.push({ port: out ? p.src : p.dst, dir: out ? 'out' : 'in', via: 'OTF', peer, enabled: true })
    }
    for (const b of buffers) {
      if (b.producerPid !== pid || (b.kind !== 'history' && b.kind !== 'stat' && b.kind !== 'optional') || edges.some((e) => e.buffer_ref === b.name)) continue
      const common = { buffer: b.name, size: sizeText(b.width, b.height), format: b.format, bit: b.bit, comp: b.comp, mb: b.mbFrame, enabled: b.enabled, note: b.note }
      if (b.kind === 'history') {
        b.rPorts.forEach((p) => ports.push({ ...common, port: p, dir: 'in', via: 'history', peer: 'prev frame' }))
        b.wPorts.forEach((p) => ports.push({ ...common, port: p, dir: 'out', via: 'history', peer: 'next frame' }))
      } else {
        (b.wPorts.length ? b.wPorts : ['WDMA']).forEach((p) => ports.push({ ...common, port: p, dir: 'out', via: b.kind === 'optional' ? 'optional' : 'stat', peer: b.kind === 'optional' ? 'disabled' : 'stat' }))
      }
    }
    for (const io of (cfg?.memory_io as Dict[] | undefined) ?? []) {
      ports.push({ port: String(io.port), dir: io.direction === 'read' ? 'in' : 'out', via: 'DMA', peer: io.bitrate_condition ? `bitrate: ${io.bitrate_condition}` : undefined, enabled: true })
    }
    const inEdge = edges.find((e) => e.target === n.id && e.flow_type === 'M2M' && e.memory?.width)
    const inSize = sim.width && sim.height ? sizeText(sim.width, sim.height) : inEdge ? sizeText(inEdge.memory!.width, inEdge.memory!.height) : ''
    const outSizes = [...new Set(edges.filter((e) => e.source === n.id && e.flow_type === 'M2M' && e.memory?.width).map((e) => sizeText(e.memory!.width, e.memory!.height)))]
    const cat = n.type === 'ip' ? catalogs?.get(String(n.ip_ref ?? '')) : undefined
    const channels = channelsOf(ports, cat)
    const count = (dir: 'in' | 'out') => ({
      used: channels.filter((c) => c.kind === 'DMA' && c.dir === dir && c.status === 'used').length,
      total: cat ? channels.filter((c) => c.kind === 'DMA' && c.dir === dir).length : null,
    })
    return {
      viewId: n.id, pid, label: n.label, lane: laneOf(n, ch), type: n.type, ipRef: String(n.ip_ref ?? ''), inSize, outSizes,
      ops: opsOf(n.active_operations, cfg), mode: cfg?.selected_mode ? String(cfg.selected_mode) : undefined, flags: flagsOf(cfg), sw: swTimingOf(cfg), ports,
      channels, rdma: count('in'), wdma: count('out'), modes: cat?.capabilities?.operating_modes?.map((m) => m.id),
      ...domainOf(cat, cfg),
    }
  })
  const links: IpLink[] = edges.filter((e) => e.flow_type !== 'risk' && active.has(pipelineIdOf(e.source)) && active.has(pipelineIdOf(e.target)))
    .map((e) => {
      const kind: IpLink['kind'] = e.flow_type === 'control' ? 'ctrl' : e.flow_type === 'M2M' ? 'M2M' : 'OTF'
      const b = e.buffer_ref ? bufMap.get(e.buffer_ref) : undefined
      return { from: pipelineIdOf(e.source), to: pipelineIdOf(e.target), kind, buffer: e.buffer_ref ?? undefined, mbs: b && b.consumers.length ? (b.rMBs ?? 0) / b.consumers.length : null }
    })
  return { ips, byPid: new Map(ips.map((i) => [i.pid, i])), links, buffers, fps: vfps, totalMBs: +total.toFixed(1), unknownBuffers: unknown }
}

/** BLK / voltage rail / DVFS group from the IP catalog. The selected mode's sim entry wins. */
export function domainOf(cat?: IpCatalog, cfg?: Dict): Pick<IpModel, 'blk' | 'blkSource' | 'vdd' | 'dvfsGroup'> {
  const caps = cat?.capabilities
  if (!caps) return {}
  const props = caps.properties ?? {}
  const sim = (caps.sim ?? {}) as Dict
  const modes = (sim.modes ?? {}) as Record<string, Dict>
  const sel = cfg?.selected_mode ? modes[String(cfg.selected_mode)] : undefined
  const first = Object.values(modes).find((m) => m && typeof m === 'object')
  const pick = (k: string) => {
    for (const src of [sel, sim, first]) if (src && typeof src[k] === 'string' && src[k]) return String(src[k])
    return undefined
  }
  const blk = props.blk ?? props.block
  return { blk: blk ?? props.hierarchy_group, blkSource: blk ? 'blk' : props.hierarchy_group ? 'hierarchy_group' : undefined, vdd: pick('vdd'), dvfsGroup: pick('dvfs_group') }
}

/** Catalog modules ∪ used ports → channel list with used / off (optional disabled) / unused. */
export function channelsOf(ports: Port[], cat?: IpCatalog): DmaChannel[] {
  const out = new Map<string, DmaChannel>()
  for (const m of cat?.capabilities?.properties?.modules ?? []) {
    const kind = m.type === 'FIFO' || /FIFO$/.test(m.name) ? 'FIFO' : 'DMA'
    out.set(m.name, { name: m.name, dir: m.direction === 'read' ? 'in' : 'out', kind, status: 'unused', purpose: m.purpose, catalogued: true })
  }
  for (const p of ports) {
    if (p.via === 'ctrl') continue
    const kind: DmaChannel['kind'] = p.via === 'OTF' ? 'FIFO' : 'DMA'
    if (kind === 'FIFO' && !out.has(p.port) && /^OTF /.test(p.port)) continue
    const cur = out.get(p.port) ?? { name: p.port, dir: p.dir, kind, status: 'unused' as const, catalogued: false }
    const status: DmaChannel['status'] = p.enabled ? 'used' : cur.status === 'used' ? 'used' : 'off'
    out.set(p.port, { ...cur, status, buffer: cur.buffer ?? p.buffer, peer: cur.peer ? `${cur.peer}, ${p.peer ?? ''}` : p.peer })
  }
  const rank = { used: 0, off: 1, unused: 2 }
  return [...out.values()].sort((a, b) => (a.dir === b.dir ? 0 : a.dir === 'in' ? -1 : 1) || rank[a.status] - rank[b.status] || a.name.localeCompare(b.name))
}

/** DMA traffic per IP (WDMA + RDMA engines, MB/s) — for stacked comparisons. */
export function trafficByIp(m: PipelineModel): Map<string, number> {
  const out = new Map<string, number>()
  const add = (k: string, v: number | null) => { if (v) out.set(k, +((out.get(k) ?? 0) + v).toFixed(1)) }
  for (const b of m.buffers) {
    if (!b.enabled || b.mbFrame === null) continue
    add(m.byPid.get(b.producerPid)?.label ?? b.producer, b.wMBs)
    if (b.kind === 'history') { add(m.byPid.get(b.producerPid)?.label ?? b.producer, b.rMBs); continue }
    const per = b.consumers.length ? (b.rMBs ?? 0) / b.consumers.length : 0
    b.consumers.forEach((c) => add(c, per))
  }
  return out
}

export type { ViewEdgeData }
