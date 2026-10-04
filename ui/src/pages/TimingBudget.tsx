import { useEffect, useMemo, useState } from 'react'
import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { SW_MARGINS, fmt, stageDomainsOf, marginOf, marginOpts, pct0, timingApi, verdictChip, type EisMode, type Statistic, type TimingReport } from '../lib/timingBudget'
import { Card, ClockChart, Gantt, Intervals, PowerBw, SlotBudget, WhatIf } from '../components/TimingCharts'
import { ProvBadge } from '../components/Provenance'
import { powerScope, type Prov } from '../lib/provenance'
import { ProfileSelect } from '../components/ProfileSelect'
import { useSimProfiles } from '../lib/simProfile'

const SCALES = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5]

export function TimingBudgetPage({ ctx }: { ctx: Ctx }) {
  const { scenario, variant } = ctx
  const statistic = (ctx.params.stat === 'mean' || ctx.params.stat === 'min' ? ctx.params.stat : 'max') as Statistic
  const eis = (ctx.params.eis === 'on' || ctx.params.eis === 'off' ? ctx.params.eis : 'auto') as EisMode
  const scale = SCALES.includes(Number(ctx.params.scale)) ? Number(ctx.params.scale) : 1.0
  const margin = marginOf(ctx.params.margin)
  const [marginDraft, setMarginDraft] = useState(String(Math.round(margin * 100)))
  useEffect(() => setMarginDraft(String(Math.round(margin * 100))), [margin])
  const frames = [6, 12, 20].includes(Number(ctx.params.frames)) ? Number(ctx.params.frames) : 20
  const set = (k: string, v: string | undefined) => ctx.navigate(undefined, { [k]: v }, true)
  const sp = useSimProfiles(ctx.project, ctx.params.cfg)
  const cfg = sp.ref

  const q = useAsync(() => (!sp.ready ? new Promise<never>(() => {}) : variant ? timingApi.variant(scenario, variant, { statistic, eis, runtime_scale: scale, timeline_frames: frames, ...marginOpts(margin) }, cfg) : Promise.reject(new Error('variant를 선택하세요 (Ctrl K)'))), [scenario, variant, statistic, eis, scale, cfg, sp.ready, margin, frames])
  // what-if (24 sims) starts after the main report so the page never holds two simulation slots at once
  const mainKey = JSON.stringify([ctx.project, scenario, variant, cfg, margin])
  const [mainReadyKey, setMainReadyKey] = useState<string | null>(null)
  useEffect(() => { if (q.data && sp.ready) setMainReadyKey(mainKey) }, [q.data, sp.ready, mainKey])
  const mainReady = mainReadyKey === mainKey && sp.ready
  const wq = useAsync(() => (variant && mainReady ? timingApi.variant(scenario, variant, { statistic: 'max', eis: 'auto', runtime_scale: 1, include_whatif: true, ...marginOpts(margin) }, cfg) : Promise.resolve(null)), [scenario, variant, mainReady, cfg, margin])
  const r = q.data?.report
  const whatif = wq.data?.report.whatif ?? []

  return (
    <div className="page tb-page">
      <div className="toolbar" style={{ flexWrap: 'wrap', gap: 14 }}>
        <Seg label="SW 통계" value={statistic} options={[['max', 'max'], ['mean', 'mean']]} onPick={(v) => set('stat', v === 'max' ? undefined : v)} />
        <Seg label="EIS" value={eis} options={[['auto', `auto${r ? (r.eis.auto ? ' (ON)' : ' (OFF)') : ''}`], ['on', 'ON'], ['off', 'OFF']]} onPick={(v) => set('eis', v === 'auto' ? undefined : v)} />
        <Seg label="차기 SW 증가" value={String(scale)} options={SCALES.map((s) => [String(s), `×${s.toFixed(1)}`])} onPick={(v) => set('scale', v === '1' ? undefined : v)} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }} title="RT · Output HW는 frame period의 (1 − margin) 안에 끝나야 함. NRT · Post 필요 clock의 rule 기준선도 같은 margin을 사용. 기본 25%">
          <span className="muted" style={{ fontSize: 13 }}>SW margin</span>
          <div className="seg" role="group" aria-label="SW margin">
            {SW_MARGINS.map((m) => <button key={m} className={Math.abs(margin - m) < 1e-9 ? 'on' : ''} onClick={() => set('margin', Math.abs(m - 0.25) < 1e-9 ? undefined : String(Math.round(m * 100)))}>{pct0(m)}{Math.abs(m - 0.25) < 1e-9 ? ' (기본)' : ''}</button>)}
          </div>
          <input className="input" type="number" min={5} max={60} step={1} value={marginDraft} aria-label="SW margin %" style={{ width: 64, padding: '5px 6px' }}
            onChange={(e) => setMarginDraft(e.target.value)}
            onBlur={() => { const v = Math.round(Number(marginDraft)); set('margin', Number.isFinite(v) && v >= 5 && v <= 60 && v !== 25 ? String(v) : undefined) }}
            onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} /><span className="faint" style={{ fontSize: 12 }}>%</span>
        </div>
        <ProfileSelect profiles={sp.profiles} value={cfg} onChange={(v) => set('cfg', v)} />
        <span className="grow" />
        {r && <span className={`badge ${verdictChip(r.verdict.status).cls}`} title={r.verdict.reasons.join('\n')}>{verdictChip(r.verdict.status).label}</span>}
        {r && r.warnings.length > 0 && <button className="badge v-warn" style={{ border: 0, cursor: 'pointer' }} title={r.warnings.slice(0, 8).join('\n')}
          onClick={() => { const d = document.getElementById('tb-warnings') as HTMLDetailsElement | null; if (d) { d.open = true; d.scrollIntoView({ behavior: 'smooth', block: 'center' }) } }}>경고 {r.warnings.length}</button>}
        {r && <span className="chip">{fmt(r.fps, 0)} fps · P {fmt(r.period_ms, 3)} ms</span>}
        {r && <span className="chip" title={r.dvfs.tables.join(', ')}>DVFS {r.dvfs.applied ? r.dvfs.table_ref ?? 'custom' : '미연결'}</span>}
        <button className="btn" onClick={() => ctx.navigate('timing-fleet', { cfg: ctx.params.cfg, margin: ctx.params.margin })}>전체 scenario →</button>
      </div>
      {(sp.error || q.error) && <div className="err">{sp.error || q.error}</div>}
      {q.loading && !r && !sp.error && <div className="empty">계산 중…</div>}
      {r && <Body r={r} cfg={q.data?.config_profile_ref ?? null} ctx={ctx} whatif={whatif} whatLoading={wq.loading} current={{ statistic, eis: r.eis.on, scale }} margin={r.sw_margin?.rt ?? margin}
        frames={frames} setFrames={(n) => set('frames', n === 20 ? undefined : String(n))} />}
    </div>
  )
}

function Body({ r, cfg, whatif, whatLoading, current, margin, frames, setFrames }: { r: TimingReport; cfg: string | null; ctx: Ctx; whatif: NonNullable<TimingReport['whatif']>; whatLoading: boolean; current: { statistic: string; eis: boolean; scale: number }
  margin: number; frames: number; setFrames: (n: number) => void }) {
  const st = useMemo(() => Object.fromEntries(r.stages.map((s) => [s.id, s])), [r])
  // one clock per DVFS domain: a stage can span several (NRT = CAM + INTCAM); never mix them in one number
  const nrtDomains = useMemo(() => stageDomainsOf(r, 'nrt'), [r])
  const rtReadout = useMemo(() => r.ips.find((i) => i.stage === 'rt' && i.sensor_readout_ms)?.sensor_readout_ms ?? null, [r])
  const iv = r.intervals
  const prov: Prov = {
    kind: 'recalc', engine: 'Timing Budget (analytic)', scope: powerScope({ cpu: r.power.cpu_mw, hw: r.power.hw_mw, bw: r.power.bw_mw }),
    dvfs: r.dvfs.applied ? r.dvfs.table_ref : null,
    rev: cfg ? `profile ${cfg}` : 'profile 없음 (코드 기본값)',
    notes: [
      `CPU 가정: CL${r.power.cpu_model.cluster} ${fmt(r.power.cpu_model.freq_mhz, 0)} MHz ${fmt(r.power.cpu_model.volt_v, 2)} V (${r.power.cpu_model.source})`,
      ...(r.power.zero_power_ips.length ? [`unit_power=0: ${r.power.zero_power_ips.join(', ')}`] : []),
      '현재 조건으로 즉석 계산한 값 — 등록 예측(예측 현황)·Simulation evidence와 다를 수 있음',
    ],
  }
  const kpis: { label: string; value: string; unit: string; note: string; bad: boolean; prov?: Prov; small?: boolean }[] = [
    { label: `RT HW / ${pct0(1 - margin)} 예산`, value: `${fmt(st.rt.hw_ms, 2)}`, unit: `/ ${fmt(st.rt.budget_ms, 2)} ms`,
      note: rtReadout ? `sensor readout ${fmt(rtReadout, 2)} ms에 종속 · clock = readout 만족 최소 (margin 무관)` : `SW margin ${pct0(margin)} rule${Math.abs(margin - 0.25) > 1e-9 ? ' (기본 25%에서 변경)' : ''}`,
      bad: st.rt.hw_ms > st.rt.budget_ms },
    { label: 'NRT SW (runtime+latency)', value: fmt(st.nrt.sw_ms, 2), unit: 'ms', note: `HW 예산 ${fmt(st.nrt.budget_ms, 2)} ms`, bad: !st.nrt.feasible },
    { label: 'Post SW (EIS 등)', value: fmt(st.post.sw_ms, 2), unit: 'ms', note: r.eis.on ? 'EIS ON' : 'EIS OFF', bad: !st.post.feasible },
    { label: 'NRT clock · DVFS domain별', value: nrtDomains.map((d) => `${d.domain} ${fmt(d.set_mhz, 0)}`).join(' · ') || '—', unit: 'MHz',
      note: nrtDomains.map((d) => `${d.domain} 필요 ${fmt(d.required_mhz, 0)}${d.level !== null ? `→L${d.level}` : ''}${d.headroom_pct !== null ? ` 여유 ${fmt(d.headroom_pct, 0)}%` : ''}${d.set_reason === 'domain' && d.domain_leader ? ` (${d.domain_leader.toUpperCase()}가 결정)` : ''}`).join(' · ') || '—',
      bad: nrtDomains.some((d) => d.rule_mhz !== null && d.set_mhz > d.rule_mhz * 1.05), small: nrtDomains.length > 1 },
    { label: 'Preview / Video 간격', value: `${fmt(iv.preview.max_ms, 2)} / ${fmt(iv.video.max_ms, 2)}`, unit: 'ms', note: iv.ok ? `목표 ${fmt(iv.target_ms, 2)} ±${fmt(iv.tolerance * 100, 1)}% ✓` : '목표 이탈', bad: !iv.ok },
    { label: 'Power · BW', value: fmt(r.power.total_mw, 0), unit: 'mW', note: `CPU ${fmt(r.power.cpu_mw, 0)} · HW ${fmt(r.power.hw_mw, 0)} · BW ${fmt(r.power.bw_mw, 0)} · ${fmt(r.bw.total_mbs / 1000, 2)} GB/s`, bad: false, prov },
  ]
  return <>
    <section className="tb-kpis" aria-label="요약">
      {kpis.map((k) => (
        <div key={k.label} className="panel tb-kpi">
          <div className="faint" style={{ fontSize: 12 }}>{k.label}{k.prov && <> <ProvBadge prov={k.prov} compact /></>}</div>
          <div><span className="mono" style={{ fontSize: k.small ? 16 : 20, fontWeight: 600, color: k.bad ? 'var(--del-text)' : 'var(--text)' }}>{k.value}</span> <span className="faint" style={{ fontSize: 12 }}>{k.unit}</span></div>
          <div className="faint" style={{ fontSize: 11 }}>{k.note}</div>
        </div>
      ))}
    </section>
    {r.verdict.reasons.length > 0 && <div className="err" style={{ fontSize: 13 }}>{r.verdict.reasons.slice(0, 4).map((x) => <div key={x}>{x}</div>)}</div>}
    {(r.verdict.notes?.length ?? 0) > 0 && <div className="panel tb-notes" role="note" style={{ fontSize: 13, padding: '6px 12px', borderLeft: '3px solid var(--warn-text, #B7791F)' }}>
      <b>Clock ↑</b> {r.verdict.notes!.map((x) => <div key={x} className="mono" style={{ fontSize: 12 }}>{x}</div>)}</div>}
    <div className="tb-grid">
      <Card id="slot" title="① 1 frame 예산 — stage별 slot" note="stage는 memory로 pipeline · 각 stage가 1 frame 안에 끝나야 함" defaultWide><SlotBudget report={r} margin={margin} /></Card>
      <Card id="clock" title="⑤ IP별 필요 clock · DVFS level" note={`DVFS domain별 묶음 · domain level = 최고 요구 IP · RT = sensor readout 기준 · Output ${pct0(margin)} rule · NRT·Post = SW 반영 예산`}><ClockChart ips={r.ips} dvfsApplied={r.dvfs.applied} margin={margin} /></Card>
      <Card id="power" title="⑥ 예상 Power · BW" note="CPU(SW) / HW(IP별) / BW(HW·SW) 비중"><PowerBw report={r} /></Card>
      <Card id="gantt" title="② Pipeline timeline" note={`${r.timeline.length ? Math.max(...r.timeline.map((t) => t.frame)) + 1 : 0} frames · 점선 = ${fmt(r.fps, 0)} fps frame 경계 (${fmt(r.period_ms, 2)} ms)`} defaultWide
        actions={<div className="seg sm" role="group" aria-label="timeline frame 수">{[6, 12, 20].map((n) => <button key={n} className={frames === n ? 'on' : ''} onClick={() => setFrames(n)}>{n} frame</button>)}</div>}><Gantt report={r} /></Card>
      <Card id="interval" title="③ 출력 frame 간격 · pipeline latency" note="합격 기준 = 간격 · latency는 참고"><Intervals report={r} /></Card>
      <Card id="whatif" title="④ 차기 SW 증가 → NRT 필요 clock" note="NRT 예산 = period − SW(runtime+latency) · DVFS domain별 (CAM / INTCAM …)">
        {whatLoading && !whatif.length ? <div className="empty">what-if 계산 중…</div> : <WhatIf rows={whatif} current={current} margin={margin} />}
      </Card>
    </div>
    {r.warnings.length > 0 && <details id="tb-warnings" className="panel" style={{ padding: '8px 12px', fontSize: 12 }}><summary>경고 {r.warnings.length}</summary>{r.warnings.map((w) => <div key={w} className="faint">{w}</div>)}</details>}
  </>
}

function Seg({ label, value, options, onPick }: { label: string; value: string; options: string[][]; onPick: (v: string) => void }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span className="muted" style={{ fontSize: 13 }}>{label}</span>
      <div className="seg" role="group" aria-label={label}>
        {options.map(([v, l]) => <button key={v} className={value === v ? 'on' : ''} onClick={() => onPick(v)}>{l}</button>)}
      </div>
    </div>
  )
}
