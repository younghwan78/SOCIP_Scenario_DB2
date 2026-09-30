// Power-model decomposition shared by Compare and CPU what-if views.
// Families keep the same hue everywhere (CPU = blue, IP = green, memory = orange),
// so a part can be recognised across rows / pages without reading the legend.
import type { Dict } from './api'

export type Family = 'cpu' | 'ip' | 'mem'
export interface PowerPart { key: string; label: string; family: Family; mw: number; note?: string }

const CPU_SHADES = ['#0B4F8A', '#0072B2', '#3B8FCB', '#6AA9D8', '#98C4E6', '#1F3F66']
export const FAMILY_COLOR: Record<Family, string> = { cpu: '#0072B2', ip: '#009E73', mem: '#E69F00' }
const FIXED: Record<string, string> = {
  'ip.work': '#009E73', 'ip.leak': '#00664B', 'ip.clock': '#7FD1B9',
  'mem.traffic': '#E69F00', 'mem.base': '#B87A00', 'mem.other': '#F4C766', 'cpu.dsu': '#8FA3B8',
}

export function partColor(key: string, cpuOrder: string[]): string {
  if (FIXED[key]) return FIXED[key]
  const i = cpuOrder.indexOf(key)
  return CPU_SHADES[(i < 0 ? 0 : i) % CPU_SHADES.length]
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
    parts.push({ key: isDsu ? 'cpu.dsu' : `cpu.${name}`, label: isDsu ? 'DSU' : `CPU ${name}`, family: 'cpu', mw: num(mw) })
  }
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
