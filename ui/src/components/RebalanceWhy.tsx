// CPU what-if · MID 재분배: 왜 이 분배가 최상인가 + Timing Budget 영향 (2026-10-11)
//   CPU power ~ active time × C·V²·f per cluster. Moving util off the busiest cluster lets schedutil drop its OPP
//   (V²f falls faster than linearly) while receivers stay on their floor OPP — the price is task time
//   (same cycles at a lower clock). Stretching an NRT/Post SW task eats the stage's SW slack; in the pipelined
//   model fps holds and latency grows by buffered frames.
import { fmt } from '../lib/timingBudget'
import type { CpuRebalance, TimingImpact } from '../lib/rebalance'
import { Card } from './TimingCharts'

const s1 = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${fmt(v, d)}`)

export function RebalanceWhy({ r, mode, onMode }: { r: CpuRebalance; mode: 'off' | 'stage_slack'; onMode?: (m: 'off' | 'stage_slack') => void }) {
  const w = r.why, tc = r.timing_coupling
  const best = r.best
  const impact = tc?.impact.best ?? []
  const refImpact = new Map((tc?.impact.reference ?? []).map((x) => [x.stage, x]))
  const broken = impact.filter((x) => !x.ok)
  const frames = Math.max(0, ...impact.map((x) => x.extra_latency_frames))
  const same = !best || !best.moved.length
  return (
    <Card id="cpu-why" title="왜 이 분배인가 · SW timing 영향" defaultWide minHeight={140}
      note={tc ? `${tc.enforced ? 'Timing Budget 연동: stage SW 여유만큼만 task가 느려질 수 있음' : 'Timing Budget 미연동: frame 주기만 제약 (영향은 아래에 표시)'} · ${tc.statistic} ×${tc.runtime_scale}` : '측정 profile에 scenario variant가 없어 Timing Budget과 연결하지 않음'}
      actions={onMode && tc ? <div className="seg" role="group" aria-label="SW timing 제약">
        <button className={mode === 'stage_slack' ? 'on' : ''} onClick={() => onMode('stage_slack')} title="NRT/Post stage SW 여유 안에서만 task가 느려짐 — stage SW 시간 증가 제한">SW 여유 제약</button>
        <button className={mode === 'off' ? 'on' : ''} onClick={() => onMode('off')} title="각 task가 frame 주기 안에만 들어오면 허용 — stage 판정과 전체 fps는 별도 확인 필요">CPU 주기만</button>
      </div> : undefined}>
      <div style={{ display: 'grid', gap: 8 }}>
        <div className={`cpu-why-head ${same ? '' : broken.length ? 'warn' : 'ok'}`}>
          {same
            ? <>현재 탐색 범위와 제약에서 추가 절감안을 찾지 못했습니다{tc?.enforced && tc.stages.some((s) => s.slack_ms <= 0) ? ` — ${tc.stages.filter((s) => s.slack_ms <= 0).map((s) => `${s.stage.toUpperCase()} SW 여유 ${fmt(s.slack_ms, 2)} ms`).join(', ')}: 이미 budget을 넘어 SW task를 더 느리게 할 수 없습니다. 이 scenario의 CPU 절감은 SW 경로 단축이 먼저입니다.` : '.'}</>
            : <>최적 분배 <b className="mono">{s1(best!.delta_mw)} mW</b> ({fmt(r.reference.total_mw, 1)} → {fmt(best!.total_mw, 1)} mW)
              {w?.driver && w.driver.mhz[1] < w.driver.mhz[0] && <> — 핵심은 <b>{w.driver.cluster}</b> OPP {fmt(w.driver.mhz[0], 0)}→{fmt(w.driver.mhz[1], 0)} MHz ({fmt(w.driver.mv[0], 0)}→{fmt(w.driver.mv[1], 0)} mV, {s1(w.driver.delta_mw)} mW)</>}
              {tc?.enforced && w?.driver && w.driver.mhz[1] >= w.driver.mhz[0] && w.driver.next_lower_mhz && <>. {w.driver.cluster}를 {fmt(w.driver.next_lower_mhz, 0)} MHz로 내리면
                그 cluster에 남는 SW stage task({r.units.filter((u) => u.home === w.driver!.cluster && u.budget_source === 'stretch').map((u) => u.unit).join(', ') || '—'})도 함께 느려져 stage 여유를 넘으므로 OPP는 유지하고 작은 이동만 남습니다</>}
              {broken.length > 0 && <>. <b>단, {broken.map((x) => `${x.stage.toUpperCase()} SW ${s1(x.delta_sw_ms, 1)} ms (여유 ${fmt(x.slack_ms, 1)} ms)`).join(', ')}{frames ? ` → latency +${frames} frame` : ''}</b> — stage 시간 여유를 넘었습니다. 전체 fps와 지연을 다시 확인하세요{mode === 'off' && onMode ? ' (SW 여유 제약으로 다시 실행해 비교)' : ''}.</>}</>}
        </div>
        {w && !same && <div className="cpu-why-grid">
          <table className="tb-mini-table"><thead><tr><th>cluster</th><th>OPP MHz</th><th>mV</th><th style={{ textAlign: 'right' }}>mW</th><th style={{ textAlign: 'right' }}>Δ</th></tr></thead>
            <tbody>{w.clusters.map((c) => <tr key={c.cluster}><td>{c.cluster}</td>
              <td className="mono">{fmt(c.mhz[0], 0)}{c.mhz[0] !== c.mhz[1] ? ` → ${fmt(c.mhz[1], 0)}` : ''}{c.opp_change === 'down' ? ' ↓' : c.opp_change === 'up' ? ' ↑' : ''}</td>
              <td className="mono">{fmt(c.mv[0], 0)}{c.mv[0] !== c.mv[1] ? ` → ${fmt(c.mv[1], 0)}` : ''}</td>
              <td className="mono" style={{ textAlign: 'right' }}>{fmt(c.mw[0], 1)} → {fmt(c.mw[1], 1)}</td>
              <td className="mono" style={{ textAlign: 'right', color: c.delta_mw < 0 ? 'var(--primary-strong)' : 'var(--del-text)' }}>{s1(c.delta_mw)}</td></tr>)}
              <tr><td>DSU</td><td className="mono">{fmt(w.dsu.mhz[0], 0)}{w.dsu.mhz[0] !== w.dsu.mhz[1] ? ` → ${fmt(w.dsu.mhz[1], 0)}` : ''}</td><td />
                <td className="mono" style={{ textAlign: 'right' }}>{fmt(w.dsu.mw[0], 1)} → {fmt(w.dsu.mw[1], 1)}</td><td className="mono" style={{ textAlign: 'right' }}>{s1(w.dsu.delta_mw)}</td></tr>
            </tbody></table>
          <table className="tb-mini-table"><thead><tr><th>이동</th><th>→</th><th style={{ textAlign: 'right' }} title="측정 배치 → 최적 배치의 task 시간">task ms</th><th style={{ textAlign: 'right' }}>budget</th></tr></thead>
            <tbody>{w.moves.map((m) => <tr key={m.unit}><td>{m.unit}</td><td className="mono">{m.from} → {m.to}</td>
              <td className="mono" style={{ textAlign: 'right' }}>{fmt(m.ms[0], 2)} → {fmt(m.ms[1], 2)}{m.stretch && m.stretch > 1.2 ? ` (×${fmt(m.stretch, 1)})` : ''}</td>
              <td className="mono faint" style={{ textAlign: 'right' }}>{m.budget_ms ? fmt(m.budget_ms, 2) : '—'}</td></tr>)}
              {w.stretched.filter((s) => !w.moves.some((m) => m.unit === s.task)).slice(0, 4).map((s) => <tr key={s.task} className="faint"><td>{s.task} (그대로)</td><td>OPP↓</td>
                <td className="mono" style={{ textAlign: 'right' }}>{fmt(s.ms[0], 2)} → {fmt(s.ms[1], 2)} (×{fmt(s.stretch, 1)})</td><td className="mono" style={{ textAlign: 'right' }}>{s.budget_ms ? fmt(s.budget_ms, 2) : '—'}</td></tr>)}
            </tbody></table>
        </div>}
        {w?.driver && !same && w.driver.delta_util_needed !== null && <div className="faint" style={{ fontSize: 12 }}>
          측정 배치에서 {w.driver.cluster} 최대 CPU util {fmt(w.driver.peak_util, 1)} — {fmt(w.driver.next_lower_mhz, 0)} MHz로 내려가려면 util {fmt(w.driver.delta_util_needed, 1)} 이상을 덜어내야 합니다.
          받는 cluster는 최저 OPP를 유지하고 active 시간만 늘어 V²f 절감이 더 큽니다. 대신 같은 cycle을 낮은 clock에서 돌리므로 task 시간이 늘어납니다.</div>}
        {tc && <table className="tb-mini-table" style={{ width: '100%' }}>
          <thead><tr><th>Timing Budget stage</th><th style={{ textAlign: 'right' }}>SW ms (측정 배치)</th><th style={{ textAlign: 'right' }}>여유 ms</th><th style={{ textAlign: 'right' }} title="SW task가 느려질 수 있는 배수 = (P − HW − overhead) / SW">허용 ×</th>
            <th style={{ textAlign: 'right' }}>최적 배치 SW Δ</th><th style={{ textAlign: 'right' }}>여유 ms</th><th style={{ textAlign: 'right' }}>latency</th><th>task</th></tr></thead>
          <tbody>{tc.stages.map((s) => { const b: TimingImpact | undefined = impact.find((x) => x.stage === s.stage); const r0 = refImpact.get(s.stage)
            return <tr key={s.stage}><td>{s.stage.toUpperCase()}</td><td className="mono" style={{ textAlign: 'right' }}>{fmt(r0?.sw_ms ?? s.sw_ms, 2)}</td>
              <td className="mono" style={{ textAlign: 'right', color: s.slack_ms < 0 ? 'var(--del-text)' : undefined }}>{fmt(s.slack_ms, 2)}</td>
              <td className="mono" style={{ textAlign: 'right' }}>×{fmt(s.stretch, 2)}</td>
              <td className="mono" style={{ textAlign: 'right' }}>{b ? s1(b.delta_sw_ms, 2) : '—'}</td>
              <td className="mono" style={{ textAlign: 'right', color: b && b.slack_ms < 0 ? 'var(--del-text)' : undefined }}>{b ? fmt(b.slack_ms, 2) : '—'}</td>
              <td className="mono" style={{ textAlign: 'right' }}>{b?.extra_latency_frames ? `+${b.extra_latency_frames} frame` : '—'}</td>
              <td className="faint" style={{ fontSize: 11 }}>{s.tasks.map((t) => t.task).join(', ')}</td></tr> })}</tbody></table>}
        {tc && tc.unmatched_tasks.length > 0 && <div className="faint" style={{ fontSize: 11 }}>Timing Budget SW 중 CPU profile에 없는 task: {tc.unmatched_tasks.join(', ')} (제약 미적용)</div>}
        {r.dsu_model?.mode === 'measured' && <div className="faint" style={{ fontSize: 11 }}>DSU = 측정 residency 고정 (배치와 무관) — cluster OPP를 따라가는 효과는 DSU 동기화(가정) 카드에서 vote로 실험하세요.</div>}
      </div>
    </Card>
  )
}
