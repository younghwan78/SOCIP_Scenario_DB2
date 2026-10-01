// Power-model decomposition shared by Compare and CPU what-if views.
// Families keep the same hue everywhere (CPU = blue, IP = green, memory = orange),
// so a part can be recognised across rows / pages without reading the legend.
import type { Dict } from './api'

export type Family = 'cpu' | 'ip' | 'mem'
export interface PowerPart { key: string; label: string; family: Family; mw: number; note?: string }

export const FAMILY_COLOR: Record<Family, string> = { cpu: '#1F6FB2', ip: '#009E73', mem: '#E69F00' }
const FIXED: Record<string, string> = {
  'ip.work': '#009E73', 'ip.leak': '#00664B', 'ip.clock': '#7FD1B9',
  'mem.traffic': '#E69F00', 'mem.base': '#B87A00', 'mem.other': '#F4C766',
}

// CPU: DSU / MID / BIG are separate colour sets (grey / blue / violet — never IP green or memory orange).
// Order = how often a cluster is used in multimedia scenarios: DSU < MID_LF < MID_HF < BIG_LF < BIG.
export type CpuTier = 'dsu' | 'mid' | 'big'
const CPU_SETS: Record<CpuTier, string[][]> = {
  dsu: [['#6B7A8F', '#8E9BAD']],
  //     LF (light)                        HF (deep)                          other
  mid: [['#8EC1E8', '#B5D7F2', '#6AAEDF'], ['#1F6FB2', '#0B4F8A', '#3B86C6'], ['#4A90C8', '#2C7BBE']],
  big: [['#C3A2DD', '#D8C2EA', '#A97FCC'], ['#8E5BB8', '#A574C9'], ['#5E2F8C', '#4A2370', '#7444A3']],
}

/** Sort key for a CPU part key (`cpu.<cluster>` or `cpu.dsu`): [tier, LF/HF/plain, numeric suffix]. */
export function cpuRank(key: string): [number, number, number] {
  const n = key.replace(/^cpu\./, '').toUpperCase()
  if (key === 'cpu.dsu' || n.includes('DSU')) return [0, 0, 0]
  const tier = /BIG|PRIME|ULTRA/.test(n) ? 2 : 1
  const sub = /(^|_)LF/.test(n) ? 0 : /(^|_)HF/.test(n) ? 1 : 2
  return [tier, sub, Number(n.match(/(\d+)$/)?.[1] ?? 0)]
}

export function cpuTier(key: string): CpuTier {
  return (['dsu', 'mid', 'big'] as const)[cpuRank(key)[0]]
}

export function compareCpu(a: string, b: string): number {
  const ra = cpuRank(a), rb = cpuRank(b)
  return ra[0] - rb[0] || ra[1] - rb[1] || ra[2] - rb[2] || a.localeCompare(b)
}

/** Cluster names (no `cpu.` prefix) in DSU < MID_LF < MID_HF < BIG_LF < BIG order. */
export function sortClusters(names: string[]): string[] {
  return [...names].sort((a, b) => compareCpu(`cpu.${a}`, `cpu.${b}`))
}

export function partColor(key: string, cpuOrder: string[] = []): string {
  if (FIXED[key]) return FIXED[key]
  if (!key.startsWith('cpu.')) return '#8A8274'
  const [tier, sub] = cpuRank(key)
  const set = CPU_SETS[(['dsu', 'mid', 'big'] as const)[tier]][tier === 0 ? 0 : sub]
  const same = cpuOrder.filter((k) => { const r = cpuRank(k); return r[0] === tier && r[1] === sub })
  const i = Math.max(0, same.indexOf(key))
  return set[i % set.length]
}

const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
const obj = (v: unknown): Dict => (v && typeof v === 'object' ? (v as Dict) : {})

/** power_breakdown (simulation evidence) -> ordered parts: CPU clusters, IP work/leak/clock, memory traffic/base/other. */
export function powerModelParts(pb: Dict | null | undefined): PowerPart[] {
  if (!pb) return []
  const parts: PowerPart[] = []
  const cpu = obj(pb.cpu)
  const clusters = obj(cpu.by_cluster)
  const dsuName = String(obj(cpu.dsu).name ?? 'DSU')
  for (const [name, mw] of Object.entries(clusters)) {
    const isDsu = name.toUpperCase() === dsuName.toUpperCase()
    parts.push({ key: isDsu ? 'cpu.dsu' : `cpu.${name}`, label: isDsu ? 'DSU' : name, family: 'cpu', mw: num(mw) })
  }
  parts.sort((a, b) => compareCpu(a.key, b.key))
  const ip = obj(pb.ip)
  const clock = num(ip.clock_overhead_mw), leak = num(ip.leakage_mw)
  parts.push({ key: 'ip.work', label: 'IP 동작', family: 'ip', mw: Math.max(0, num(ip.total_mw) - clock - leak) })
  if (leak) parts.push({ key: 'ip.leak', label: 'IP leakage', family: 'ip', mw: leak })
  if (clock) parts.push({ key: 'ip.clock', label: 'IP clock 초과분', family: 'ip', mw: clock, note: '필요 clock 초과로 늘어난 전력' })
  const mem = obj(pb.memory)
  const mif = obj(mem.mif)
  const base = num(mif.base_mw), other = num(mif.other_masters_mw)
  parts.push({ key: 'mem.traffic', label: 'BW traffic', family: 'mem', mw: Math.max(0, num(mem.total_mw) - base - other) })
  if (base) parts.push({ key: 'mem.base', label: `MIF base${mif.mif_mhz ? ` @${mif.mif_mhz}` : ''}`, family: 'mem', mw: base })
  if (other) parts.push({ key: 'mem.other', label: '기타 master BW', family: 'mem', mw: other })
  return parts.filter((p) => p.mw > 0 || p.key === 'ip.work')
}

export function mifSummary(pb: Dict | null | undefined): string | null {
  const mif = obj(obj(pb?.memory).mif)
  if (!mif.mif_mhz) return null
  const reason = mif.reason === 'qos_lock' ? 'QoS lock' : mif.reason === 'saturated' ? '포화' : 'governor'
  const util = typeof mif.utilization === 'number' ? ` · ${(mif.utilization * 100).toFixed(0)}%` : ''
  return `MIF ${mif.mif_mhz} MHz (${reason}${util})`
}

export function cpuSource(pb: Dict | null | undefined): string | null {
  const cpu = obj(pb?.cpu)
  if (cpu.source === 'pmu_profile') return 'CPU: 실측 profile'
  if (cpu.source === 'sw_timing') return 'CPU: SW timing 추정'
  return num(cpu.total_mw) ? 'CPU' : null
}
