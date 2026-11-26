import type { FramePacing, GpuMif } from '../lib/timingBudget'

const n = (v: number | null | undefined, d = 2) => (v == null ? '—' : v.toFixed(d))

/** R-5 / M-6 frame-pacing-v1: the game frame chain over the panel latch (only when the GPU declares sim.workload). */
export function PacingSummary({ pacing }: { pacing: FramePacing }) {
  if (pacing.status === 'no_gpu_time') return <div className="faint">{pacing.reason}</div>
  const tiles: [string, string, string][] = [
    ['달성 fps', `${n(pacing.achieved_fps, 1)} / ${n(pacing.target_fps, 0)}`, `fail 기준 < ${n(pacing.fail_below_fps, 1)} fps`],
    ['jank', `${n(pacing.jank_pct, 2)} %`, `기대 간격 ${n(pacing.expected_interval_ms)} ms 초과 · drop ${pacing.drops ?? 0}`],
    ['GPU frame time', `${n(pacing.gpu_ms?.p50)} / ${n(pacing.gpu_ms?.p95)} / ${n(pacing.gpu_ms?.p99)} ms`, `P50 / P95 / P99 · ${pacing.gpu_clock_mhz ?? '—'} MHz`],
    ['render → photon', `${n(pacing.latency_ms?.p50, 1)} / ${n(pacing.latency_ms?.p99, 1)} ms`, 'P50 / P99'],
  ]
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
        {tiles.map(([k, v, tip]) => (
          <div key={k} className="tb-tile" data-testid={`pacing-${k}`}>
            <div className="faint" style={{ fontSize: 11 }}>{k}</div>
            <div className="mono" style={{ fontSize: 17, fontWeight: 600 }}>{v}</div>
            <div className="faint" style={{ fontSize: 11 }}>{tip}</div>
          </div>
        ))}
      </div>
      <div className="faint" style={{ fontSize: 12, marginTop: 6 }}>
        {pacing.model} · {pacing.refresh_hz} Hz latch · BufferQueue {pacing.depth} · {pacing.present_mode} · {pacing.frames} frame (seed {pacing.seed}) · GPU 분포 {pacing.gpu_basis?.distribution}
        {pacing.gpu_basis?.p95_x_gap != null && ` · P95 배수 차이 ${n(pacing.gpu_basis.p95_x_gap, 3)}`} · {pacing.value_source}
      </div>
    </div>
  )
}

/** M-7 gpu-mif-floor-v1: GPU workload DRAM traffic, the catalog MIF min-lock floor at the GPU clock, and the MIF level
 * (mif-linear BW model only; otherwise the floor is reported, not applied). */
export function MifSummary({ mif }: { mif: GpuMif }) {
  if (mif.status === 'no_gpu_clock' || mif.status === 'no_table') return <div className="faint">{mif.reason}</div>
  const wl = mif.gpu_workload_mbs ?? {}
  const rd = wl.GPU_WORKLOAD_RD, wr = wl.GPU_WORKLOAD_WR
  const tiles: [string, string, string][] = [
    ['GPU workload BW', rd == null && wr == null ? '—' : `${n((rd ?? 0) / 1000)} / ${n((wr ?? 0) / 1000)} GB/s`, 'read / write · framebuffer 제외'],
    ['MIF floor', mif.floor_mhz == null ? (mif.status === 'off' ? 'off' : '—') : `${n(mif.floor_mhz, 0)} MHz`,
      `GPU ${mif.gpu_mhz ?? '—'} MHz → mif_min_lock[${mif.floor_key_khz ?? '—'}]`],
    ['MIF level', mif.level_mhz == null ? '—' : `${n(mif.level_mhz, 0)} MHz`,
      mif.applied ? `${mif.level_reason ?? ''} · floor 없을 때 ${n(mif.level_without_floor_mhz, 0)} MHz` : `${mif.bw_model}: 보고만 (mif-linear에서 적용)`],
    ['floor 추가 전력', mif.floor_extra_mw == null ? '—' : `${n(mif.floor_extra_mw, 1)} mW`, `MIF base ${n(mif.base_mw, 0)} mW · DRAM ${n((mif.dram_mbs ?? 0) / 1000)} GB/s`],
  ]
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
        {tiles.map(([k, v, tip]) => (
          <div key={k} className="tb-tile" data-testid={`mif-${k}`}>
            <div className="faint" style={{ fontSize: 11 }}>{k}</div>
            <div className="mono" style={{ fontSize: 17, fontWeight: 600 }}>{v}</div>
            <div className="faint" style={{ fontSize: 11 }}>{tip}</div>
          </div>
        ))}
      </div>
      {mif.warning && <div className="faint" style={{ fontSize: 12, marginTop: 6 }}>⚠ {mif.warning}</div>}
    </div>
  )
}
