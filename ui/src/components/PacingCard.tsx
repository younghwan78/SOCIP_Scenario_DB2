import type { FramePacing } from '../lib/timingBudget'

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
