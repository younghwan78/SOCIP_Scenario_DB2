import { useState, type CSSProperties } from 'react'
import { fmt, type EventJob, type JobStage, type KpiResult } from '../lib/timingBudget'

// R-3 job-v1 event job (X-02): stage Gantt on the job clock (t = 0 = trigger) with phase bands and milestone lines,
// P(t) · BW(t) on the same axis with the steady background and the peak window, and the stage table with its value source.

const KIND_COLOR: Record<string, string> = { hw: 'var(--ip-line)', sw: 'var(--primary)', transfer: 'var(--buf-line)', fixed: 'var(--ext-line)' }
const KIND_LABEL: Record<string, string> = { hw: 'HW', sw: 'SW', transfer: '전송', fixed: '고정' }
const kindColor = (k: string) => KIND_COLOR[k] ?? 'var(--ext-line)'
const SOURCE_BADGE: Record<string, string> = { measured: 'v-ok', assumed: 'v-na' }

const pct = (v: number, span: number) => `${Math.max(0, Math.min(100, (v / span) * 100))}%`

/** Time span of the Gantt and the series: the makespan, or the series length when it runs longer. */
export function jobSpan(j: EventJob): number {
  const series = j.series ? j.series.power_mw.length * j.series.dt_ms : 0
  return Math.max(j.makespan_ms, ...j.stages.map((s) => s.end_ms), series, 1e-6)
}

/** Peak window position: the window_ms slice with the highest mean power in the series (null without a series). */
export function peakWindow(j: EventJob): { start_ms: number; end_ms: number } | null {
  const s = j.series, w = j.peak?.window_ms
  if (!s || !w || !s.power_mw.length) return null
  const n = Math.max(1, Math.round(w / s.dt_ms))
  let best = -Infinity, at = 0, sum = 0
  for (let i = 0; i < s.power_mw.length; i++) {
    sum += s.power_mw[i]
    if (i >= n) sum -= s.power_mw[i - n]
    if (i >= n - 1 && sum > best) { best = sum; at = i - n + 1 }
  }
  if (best === -Infinity) return null
  return { start_ms: at * s.dt_ms, end_ms: (at + n) * s.dt_ms }
}

const waitMs = (s: JobStage) => Math.max(0, s.elapsed_ms - s.service_ms)

function Milestones({ j, span }: { j: EventJob; span: number }) {
  return <>{Object.entries(j.milestones ?? {}).map(([k, v]) => (
    <span key={k} aria-hidden style={{ position: 'absolute', left: pct(v, span), top: 0, bottom: 0, borderLeft: '2px dashed var(--del-text)', opacity: 0.6 }} />
  ))}</>
}

function Series({ j, span, field, color, label, unit, base }: { j: EventJob; span: number; field: 'power_mw' | 'bw_mbs'; color: string; label: string; unit: string; base: number | null }) {
  const s = j.series
  const v = s?.[field]
  if (!s || !v?.length) return null
  const max = Math.max(...v, base ?? 0, 1e-6)
  const pts = v.map((y, i) => `${((i * s.dt_ms) / span) * 1000},${60 - (y / max) * 56}`)
  // step line: hold each sample for dt
  const step = v.flatMap((y, i) => [`${((i * s.dt_ms) / span) * 1000},${60 - (y / max) * 56}`, `${(((i + 1) * s.dt_ms) / span) * 1000},${60 - (y / max) * 56}`])
  const pk = peakWindow(j)
  return (
    <>
      <span className="faint" style={{ fontSize: 11 }}>{label}<br /><span className="mono">max {fmt(max, 0)} {unit}</span></span>
      <div style={{ position: 'relative' }}>
        <svg viewBox="0 0 1000 60" preserveAspectRatio="none" width="100%" height={60} role="img" aria-label={`${label} 시계열`} style={{ display: 'block', background: 'var(--surface-soft)', borderRadius: 4 }}>
          {pk && field === 'power_mw' && <rect x={(pk.start_ms / span) * 1000} y={0} width={((pk.end_ms - pk.start_ms) / span) * 1000} height={60} fill="var(--warn-soft)" />}
          {base != null && <line x1={0} x2={1000} y1={60 - (base / max) * 56} y2={60 - (base / max) * 56} stroke="var(--faint)" strokeDasharray="6 4" vectorEffect="non-scaling-stroke" />}
          <polyline points={(step.length ? step : pts).join(' ')} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
        </svg>
        <Milestones j={j} span={span} />
      </div>
      <span />
    </>
  )
}

function JobView({ j, kpis }: { j: EventJob; kpis: KpiResult[] }) {
  const span = jobSpan(j)
  const mine = kpis.filter((k) => k.job === j.id)
  const ms = Object.entries(j.milestones ?? {}).sort((a, b) => a[1] - b[1])
  const grid: CSSProperties = { display: 'grid', gridTemplateColumns: 'minmax(90px, 160px) 1fr minmax(64px, 110px)', gap: '4px 8px', alignItems: 'center', fontSize: 12 }
  const measured = j.stages.filter((s) => s.value_source === 'measured').length
  return (
    <div data-testid={`job-${j.id}`}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginBottom: 8, fontSize: 13 }}>
        <b>{j.label ?? j.id}</b>
        <span className="chip mono">makespan {fmt(j.makespan_ms, 2)} ms</span>
        {ms.map(([k, v]) => {
          const kp = mine.find((x) => x.milestone === k && x.target != null)
          return <span key={k} className={`badge ${kp ? (kp.status === 'fail' ? 'v-fail' : 'v-ok') : 'v-info'}`} title={kp ? `${kp.id ?? kp.kpi}: 목표 ${kp.bound === 'min' ? '≥' : '≤'} ${fmt(kp.target, 0)} ${kp.unit}${kp.value_source === 'assumed' ? ' (가정 목표)' : ''}` : '목표 없음'}>
            {k} {fmt(v, 2)} ms{kp ? ` ${kp.bound === 'min' ? '≥' : '≤'} ${fmt(kp.target, 0)}` : ''}</span>
        })}
        <span className="faint">stage 출처: 실측 {measured} / {j.stages.length}</span>
      </div>
      <div style={grid} role="group" aria-label="stage timeline">
        <span className="faint" style={{ fontSize: 11 }}>phase</span>
        <div style={{ position: 'relative', height: 18 }}>
          {j.phases.map((p, i) => (
            <span key={p.id} title={`${p.id} ${fmt(p.start_ms, 2)} – ${fmt(p.end_ms, 2)} ms`} style={{ position: 'absolute', left: pct(p.start_ms, span), width: pct(p.end_ms - p.start_ms, span), top: 0, bottom: 0,
              background: i % 2 ? 'var(--line-soft)' : 'var(--primary-soft)', fontSize: 10, overflow: 'hidden', whiteSpace: 'nowrap', paddingLeft: 3, borderRadius: 3 }}>{p.id}</span>
          ))}
          <Milestones j={j} span={span} />
        </div>
        <span className="faint mono" style={{ fontSize: 11 }}>0 – {fmt(span, 1)} ms</span>
        {j.stages.map((s) => {
          const w = waitMs(s)
          return [
            <span key={`${s.id}-l`} className="mono" title={s.nodes.join(', ')} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.id} <span className="faint">{KIND_LABEL[s.kind] ?? s.kind}</span></span>,
            <div key={`${s.id}-t`} style={{ position: 'relative', height: 16, background: 'var(--surface-soft)', borderRadius: 3 }}>
              <span data-testid={`job-bar-${s.id}`} title={`${s.id}: ${fmt(s.start_ms, 2)} – ${fmt(s.end_ms, 2)} ms · service ${fmt(s.service_ms, 2)} · 대기 ${fmt(w, 2)} ms`}
                style={{ position: 'absolute', left: pct(s.start_ms, span), width: pct(s.end_ms - s.start_ms, span), minWidth: 2, top: 2, bottom: 2, borderRadius: 2,
                  background: w > 0 && s.elapsed_ms > 0
                    ? `linear-gradient(90deg, ${kindColor(s.kind)} ${(s.service_ms / s.elapsed_ms) * 100}%, transparent ${(s.service_ms / s.elapsed_ms) * 100}%), repeating-linear-gradient(45deg, ${kindColor(s.kind)} 0 2px, transparent 2px 5px)`
                    : kindColor(s.kind) }} />
              <Milestones j={j} span={span} />
            </div>,
            <span key={`${s.id}-n`} className="mono faint" style={{ fontSize: 11 }}>{fmt(s.elapsed_ms, 2)} ms{w > 0.005 ? ` (대기 ${fmt(w, 1)})` : ''}</span>,
          ]
        })}
        <Series j={j} span={span} field="power_mw" color="var(--del-text)" label="P(t)" unit="mW" base={j.background?.power_mw ?? null} />
        <Series j={j} span={span} field="bw_mbs" color="var(--add-text)" label="BW(t)" unit="MB/s" base={j.background?.bw_mbs ?? null} />
      </div>
      <div className="faint" style={{ fontSize: 11, margin: '4px 0 10px' }}>
        점선 가로선 = steady background · 노란 음영 = peak {fmt(j.peak?.window_ms ?? null, 0)} ms 창 · 붉은 세로 점선 = milestone ({ms.map(([k]) => k).join(', ') || '—'})
      </div>
      <div style={{ overflowX: 'auto', maxWidth: '100%' }}>
      <table className="tb-mini-table" style={{ width: '100%' }}>
        <thead><tr><th>stage</th><th>phase</th><th>node</th><th style={{ textAlign: 'right' }}>start</th><th style={{ textAlign: 'right' }}>service</th><th style={{ textAlign: 'right' }}>elapsed</th><th style={{ textAlign: 'right' }}>대기</th><th>clock MHz</th><th style={{ textAlign: 'right' }}>MB</th><th style={{ textAlign: 'right' }}>mJ</th><th>출처</th></tr></thead>
        <tbody>
          {j.stages.map((s) => (
            <tr key={s.id} data-testid={`job-row-${s.id}`}>
              <td className="mono"><span aria-hidden style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: kindColor(s.kind), marginRight: 4 }} />{s.id}{s.chunks > 1 ? <span className="faint"> ×{s.chunks}</span> : null}</td>
              <td className="faint">{s.phase}</td>
              <td className="faint">{s.nodes.join(', ')}</td>
              <td className="mono" style={{ textAlign: 'right' }}>{fmt(s.start_ms, 2)}</td>
              <td className="mono" style={{ textAlign: 'right' }}>{fmt(s.service_ms, 2)}</td>
              <td className="mono" style={{ textAlign: 'right' }}>{fmt(s.elapsed_ms, 2)}</td>
              <td className="mono" style={{ textAlign: 'right' }}>{waitMs(s) > 0.005 ? fmt(waitMs(s), 2) : '—'}</td>
              <td className="mono faint">{Object.entries(s.clock_mhz ?? {}).map(([n, f]) => `${n} ${fmt(f, 0)}`).join(' · ') || '—'}</td>
              <td className="mono" style={{ textAlign: 'right' }}>{fmt(s.mb, 1)}</td>
              <td className="mono" style={{ textAlign: 'right' }}>{s.energy_attributed === false ? '—' : fmt(s.energy_mj, 2)}</td>
              <td><span className={`badge ${SOURCE_BADGE[s.value_source] ?? 'v-info'}`} title={s.value_source === 'measured' ? 'jobs.measured.yaml 실측 slot' : s.value_source === 'assumed' ? 'E2600 가정값 — 사내 실측 slot으로 교체' : s.value_source}>{s.value_source === 'measured' ? '실측' : s.value_source === 'assumed' ? '가정' : s.value_source}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 8, marginTop: 10 }}>
        {j.energy_mj && <div className="tb-tile" data-testid="job-energy">
          <div className="faint" style={{ fontSize: 11 }}>event energy</div>
          <div className="mono" style={{ fontSize: 17, fontWeight: 600 }}>{fmt(j.energy_mj.event, 2)} mJ</div>
          <div className="faint" style={{ fontSize: 11 }}>{Object.entries(j.energy_mj.by_kind).map(([k, v]) => `${KIND_LABEL[k] ?? k} ${fmt(v, 2)}`).join(' · ')}{j.energy_mj.unattributed.length ? ` · 미귀속 ${j.energy_mj.unattributed.join(', ')}` : ''}</div>
        </div>}
        {j.peak && <div className="tb-tile" data-testid="job-peak">
          <div className="faint" style={{ fontSize: 11 }}>peak ({fmt(j.peak.window_ms, 0)} ms 창 / 순간)</div>
          <div className="mono" style={{ fontSize: 17, fontWeight: 600 }}>{fmt(j.peak.power_mw, 0)} / {fmt(j.peak.power_instant_mw, 0)} mW</div>
          <div className="faint" style={{ fontSize: 11 }}>BW {fmt(j.peak.bw_mbs / 1000, 2)} / {fmt(j.peak.bw_instant_mbs / 1000, 2)} GB/s · memory {fmt(j.peak.footprint_mb, 1)} MB</div>
        </div>}
        {j.background && <div className="tb-tile" data-testid="job-background">
          <div className="faint" style={{ fontSize: 11 }}>steady background ({j.background.priority})</div>
          <div className="mono" style={{ fontSize: 17, fontWeight: 600 }}>{fmt(j.background.power_mw, 0)} mW</div>
          <div className="faint" style={{ fontSize: 11 }}>BW {fmt(j.background.bw_mbs / 1000, 2)} GB/s · RT 대기 max {fmt(j.background.rt_wait_max_ms, 2)} ms · drop {j.background.dropped_frames} frame</div>
        </div>}
      </div>
      {(j.basis || (j.notes?.length ?? 0) > 0) && <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>{j.model}{j.basis ? ` · ${j.basis}` : ''}{(j.notes ?? []).map((n) => <div key={n}>⚠ {n}</div>)}</div>}
    </div>
  )
}

/** Event jobs of the report; a picker when there is more than one. */
export function JobCard({ jobs, kpis }: { jobs: EventJob[]; kpis: KpiResult[] }) {
  const [pick, setPick] = useState(0)
  const at = Math.min(pick, jobs.length - 1)
  if (!jobs.length) return null
  return (
    <div>
      {jobs.length > 1 && <div className="seg sm" role="group" aria-label="event job" style={{ marginBottom: 8 }}>
        {jobs.map((j, i) => <button key={j.id} className={i === at ? 'on' : ''} onClick={() => setPick(i)}>{j.id}</button>)}
      </div>}
      <JobView j={jobs[at]} kpis={kpis} />
    </div>
  )
}
