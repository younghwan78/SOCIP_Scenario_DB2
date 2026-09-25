// Library: reference inputs behind predictions (IP, DVFS, compression, sensor, SW timing)
import { getJson, type Dict } from './api'

export interface Paged<T> { items: T[]; total: number }
export interface IpRow { id: string; category: string; capabilities: Dict; hierarchy?: Dict }
export interface DvfsLevel { level: number; speed_mhz: number; voltages: Record<string, number> }
export interface DvfsTable { id: string; soc_ref: string; dvfs_version: number; evt_hint: string | null; source: Dict | null; domains: Record<string, { domain: string; levels: DvfsLevel[] }> }
export interface SocRow { id: string; process_node?: string; memory_type?: string; compression_modes: Record<string, { comp_ratio?: number; compressor?: string }> | null }
export interface SensorCatalogRow { id: string; board: string; sensor_name: string; mode_count: number }
export interface SensorTimingRow { id: string; sensor_name: string; revision?: string; modes: string[] }
export interface SwTaskRow {
  scenario_id: string; task: string; variants: number; min_ms: number[] | null; mean_ms: number[] | null; max_ms: number[] | null
  latency_ms: number[] | null; source: string[]; bitrate_scaled: boolean
}
export interface SwMeasured { evidence_id: string; scenario_id: string; variant_id: string; task: string; mean_ms?: number; p95_ms?: number; max_ms?: number; count?: number }

export const libraryApi = {
  ips: () => getJson<Paged<IpRow>>('/ip-catalogs', { limit: 500 }),
  dvfs: () => getJson<Paged<DvfsTable>>('/soc-dvfs-tables', { limit: 100 }),
  socs: () => getJson<Paged<SocRow>>('/soc-platforms', { limit: 100 }),
  sensors: () => getJson<{ items: SensorCatalogRow[]; total: number }>('/sensors/catalogs'),
  sensorTiming: () => getJson<{ items: SensorTimingRow[] }>('/sensors/timing-profiles'),
  swTiming: (scenarioId?: string) => getJson<{ tasks: SwTaskRow[]; measured: SwMeasured[] }>('/library/sw-timing', { scenario_id: scenarioId }),
}

/** Flatten the IP catalog fields the table shows. */
export function ipSummary(ip: IpRow) {
  const caps = (ip.capabilities ?? {}) as Dict
  const sim = (caps.sim ?? {}) as Dict
  const feats = (caps.supported_features ?? {}) as Dict
  const modes = (caps.operating_modes ?? sim.modes ?? []) as unknown
  const comp = (feats.compression ?? []) as unknown
  return {
    hw: String(sim.hw_name ?? '—'), vdd: String(sim.vdd ?? '—'), dvfs: String(sim.dvfs_group ?? '—'),
    source: String(sim.source ?? '—'), note: String(sim.source_note ?? ''),
    modes: Array.isArray(modes) ? modes.length : modes && typeof modes === 'object' ? Object.keys(modes).length : 0,
    compression: Array.isArray(comp) ? (comp as string[]).filter((c) => !/OFF/i.test(c)) : [],
  }
}

export const range = (r: number[] | null | undefined, d = 1) => (!r ? '—' : r[0] === r[1] ? r[0].toFixed(d) : `${r[0].toFixed(d)}–${r[1].toFixed(d)}`)
