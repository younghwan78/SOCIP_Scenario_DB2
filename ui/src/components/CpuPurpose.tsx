// CPU what-if, top of page (UX 2026-10-09): the three questions the page is for, each with where to answer it
// and — once something ran — the current answer. A run log keeps every rebalance run's knobs and result so
// "traffic shaping 0.8" or "차기 SW ×1.2" can be read against the baseline without re-running.
import { fmt } from '../lib/timingBudget'
import { strategyVerdict, type CpuRebalance } from '../lib/rebalance'

export interface CpuRun {
  n: number; profile: string; target: string; cmp: string | null; context: string
  growth: number; bwScale: number; pgEff: number
  ref_mw: number; best_mw: number | null; cmp_ref_mw: number | null; cmp_best_mw: number | null; winner: string | null
  /** CPU → DRAM MB/s of the run (BW-only effect of the BW scale) */
  bw_mbs?: number | null
}

const sg = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${fmt(v, d)}`)

export function CpuPurpose({ rb, cmp, runs, growth, bwScale, onRebalance, onPreset }: {
  rb: CpuRebalance | null; cmp: CpuRebalance | null; runs: CpuRun[]; growth: number; bwScale: number
  onRebalance: () => void; onPreset: (p: { growth?: number; bwScale?: number }) => void
}) {
  const last = runs[runs.length - 1]
  const base = [...runs].reverse().find((r) => r.context === last?.context && r.growth === 1 && r.bwScale === 1)
  const tuneGain = rb?.best ? rb.best.total_mw - rb.reference.total_mw : null
  const sv = rb?.strategies ? strategyVerdict(rb.strategies) : null
  const shaping = runs.filter((r) => r.bwScale !== 1 && base && r.context === base.context && r.growth === base.growth)
  const growthRuns = runs.filter((r) => r.growth !== 1 && base && r.context === base.context && r.bwScale === base.bwScale)
  return <section className="cpu-purpose" aria-label="CPU what-if 목적">
    <div className="cpu-q">
      <b>① 현재 SW · EMS tuning / workload 분산</b>
      <div className="faint">측정 배치 → MID 집중 vs 분산 · BIG 사용 여부 · task 재배치 (cpuset)</div>
      {rb ? <div><span className={`mono ${(tuneGain ?? 0) < 0 ? 'pm-down' : ''}`} style={{ fontSize: 18, fontWeight: 600 }}>{sg(tuneGain)} mW</span> <span className="faint">최적 재배치 vs 현재 {fmt(rb.reference.total_mw, 0)} mW</span>
        {sv && <div style={{ fontSize: 12 }}>{sv.text}</div>}</div>
        : <button className="btn tb-mini" onClick={onRebalance}>MID 재분배 실행 →</button>}
    </div>
    <div className="cpu-q">
      <b>② Traffic shaping (CPU BW · DSU)</b>
      <div className="faint">CPU BW 배율(L3/SLC hit ↑, burst 완화) · DSU 동기화 가정 — 같은 profile로 다시 실행해 비교.
        <b> 현재 모델: BW 배율은 CPU→DRAM traffic(MB/s)만 바꾸고 CPU+DSU power는 그대로</b> (stall·OPP 연계 미모델) — 아래 Δ는 traffic 변화로 읽으세요.</div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {[0.9, 0.8, 0.7].map((s) => <button key={s} className={`btn tb-mini ${bwScale === s ? 'primary' : ''}`} onClick={() => onPreset({ bwScale: s })}>BW ×{s}</button>)}
        {bwScale !== 1 && <button className="btn tb-mini" onClick={() => onPreset({ bwScale: 1 })}>×1 (기준)</button>}
      </div>
      {shaping.length > 0 && base && <div style={{ fontSize: 12 }}>{shaping.map((r) => <div key={r.n} className="mono">BW ×{r.bwScale}: CPU BW {r.bw_mbs != null && base.bw_mbs != null ? `${fmt(base.bw_mbs, 0)}→${fmt(r.bw_mbs, 0)} MB/s (${sg(r.bw_mbs - base.bw_mbs, 0)})` : '—'} · CPU+DSU {sg(r.ref_mw - base.ref_mw)} mW{Math.abs(r.ref_mw - base.ref_mw) < 0.05 ? ' (BW-only)' : ''}</div>)}</div>}
    </div>
    <div className="cpu-q">
      <b>③ 차기 과제 — cluster 구조 · SW 증가</b>
      <div className="faint">① 기준의 “과제 비교”로 다른 SoC CPU 구성에 같은 SW 재배치 · ② 조건의 SW 증가 배율</div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {[1.1, 1.2, 1.3].map((g) => <button key={g} className={`btn tb-mini ${growth === g ? 'primary' : ''}`} onClick={() => onPreset({ growth: g })}>SW ×{g}</button>)}
        {growth !== 1 && <button className="btn tb-mini" onClick={() => onPreset({ growth: 1 })}>×1 (기준)</button>}
      </div>
      {cmp && rb && <div style={{ fontSize: 12 }} className="mono">구조 변경: 최적 {fmt(cmp.best?.total_mw ?? cmp.reference.total_mw, 0)} vs {fmt(rb.best?.total_mw ?? rb.reference.total_mw, 0)} mW ({sg((cmp.best?.total_mw ?? cmp.reference.total_mw) - (rb.best?.total_mw ?? rb.reference.total_mw))})</div>}
      {growthRuns.length > 0 && base && <div style={{ fontSize: 12 }}>{growthRuns.map((r) => <div key={r.n} className="mono">SW ×{r.growth}: {sg(r.ref_mw - base.ref_mw)} mW · 최적 배치 {sg((r.best_mw ?? r.ref_mw) - (base.best_mw ?? base.ref_mw))}</div>)}</div>}
    </div>
    {runs.length > 1 && <details className="cpu-runs"><summary className="faint">실행 기록 {runs.length}건 (같은 profile · 조건별 CPU power)</summary>
      <table className="tb-mini-table"><thead><tr><th>#</th><th>SoC</th><th>SW ×</th><th>BW ×</th><th>gating</th><th style={{ textAlign: 'right' }}>현재 배치 mW</th><th style={{ textAlign: 'right' }}>최적 mW</th><th>집중/분산</th><th style={{ textAlign: 'right' }}>비교 SoC 최적</th></tr></thead>
        <tbody>{runs.map((r) => <tr key={r.n} className={r === last ? 'selected' : ''}><td>{r.n}</td><td className="mono" style={{ fontSize: 11 }}>{r.target}</td><td>{r.growth}</td><td>{r.bwScale}</td><td>{r.pgEff}</td>
          <td className="mono" style={{ textAlign: 'right' }}>{fmt(r.ref_mw, 1)}</td><td className="mono" style={{ textAlign: 'right' }}>{r.best_mw === null ? '—' : fmt(r.best_mw, 1)}</td><td>{r.winner ?? '—'}</td>
          <td className="mono" style={{ textAlign: 'right' }}>{r.cmp_best_mw === null ? '—' : `${fmt(r.cmp_best_mw, 1)} (${r.cmp})`}</td></tr>)}</tbody></table></details>}
  </section>
}
