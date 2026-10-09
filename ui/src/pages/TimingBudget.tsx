import { useEffect, useMemo, useState } from 'react'
import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { SW_MARGINS, fmt, stageDomainsOf, stageSlack, marginOf, marginOpts, pct0, timingApi, verdictChip, type CpuModel, type EisMode, type Statistic, type ThroughputModel, type TimingReport, type DvfsWhatIf, type TimingConfig, type IntervalDistribution, DEFAULT_COMBOS, formatOverrides, parseOverrides, parseMeasured, formatMeasuredFlags, type MeasuredInputs } from '../lib/timingBudget'
import { Card, ClockChart, Gantt, Intervals, PowerBw, SlotBudget, WhatIf } from '../components/TimingCharts'
import { ProvBadge } from '../components/Provenance'
import { powerScope, type Prov } from '../lib/provenance'
import { ProfileSelect } from '../components/ProfileSelect'
import { useSimProfiles } from '../lib/simProfile'
import { maText, useBattery, batteryNote, type Battery } from '../lib/battery'
import { DvfsWhatIfTable } from '../components/DvfsWhatIf'
import { useReferences } from '../lib/review'
import { usePref } from '../components/Layout'
import { invalidateCache } from '../lib/api'
import { ConditionBar, DvfsOverrideTable, IntervalBoxes, MeasuredCompareCard, MeasuredPicker, type Condition } from '../components/TimingWorkbench'
import { calibrationApi } from '../lib/calibration'

const SCALES = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5]

export function TimingBudgetPage({ ctx }: { ctx: Ctx }) {
  const { scenario, variant } = ctx
  const statistic = (ctx.params.stat === 'mean' || ctx.params.stat === 'min' ? ctx.params.stat : 'max') as Statistic
  const eis = (ctx.params.eis === 'on' || ctx.params.eis === 'off' ? ctx.params.eis : 'auto') as EisMode
  const scale = SCALES.includes(Number(ctx.params.scale)) ? Number(ctx.params.scale) : 1.0
  const cpuModel: CpuModel = ctx.params.cpu === 'profile' ? 'profile' : 'flat'
  // URL override only; otherwise the server applies the project review policy (and the toggle shows the effective one)
  const tpParam: ThroughputModel | undefined = ctx.params.tp === 'stage' || ctx.params.tp === 'pipelined' ? ctx.params.tp : undefined
  const refs = useReferences(ctx.project)
  const policyTp: ThroughputModel = refs?.policy.throughput_model ?? 'stage'
  const tpOpt = tpParam ? { throughput_model: tpParam } : {}
  const margin = marginOf(ctx.params.margin)
  const [marginDraft, setMarginDraft] = useState(String(Math.round(margin * 100)))
  useEffect(() => setMarginDraft(String(Math.round(margin * 100))), [margin])
  const frames = [6, 12, 20].includes(Number(ctx.params.frames)) ? Number(ctx.params.frames) : 20
  const warmup = [0, 1, 2, 4].includes(Number(ctx.params.warmup)) ? Number(ctx.params.warmup) : 0
  const set = (k: string, v: string | undefined) => ctx.navigate(undefined, { [k]: v }, true)
  const sp = useSimProfiles(ctx.project, ctx.params.cfg)
  const cfg = sp.ref
  const battery = useBattery(ctx.project, ctx.params.cfg)
  // DVFS level override per domain (URL dvo = "CAM:3,INTCAM:2"); part of the condition
  const dvo = ctx.params.dvo ?? ''
  const overrides = useMemo(() => parseOverrides(dvo), [dvo])
  // S4: measurement as input (URL mref = measurement id, min = "sw,clock,cpu") and as the comparison reference
  const mref = ctx.params.mref ?? ''
  const mflags = ctx.params.min ?? ''
  const measured = useMemo(() => parseMeasured(mref, mflags), [mref, mflags])
  const pp = ctx.params.pp ?? ''
  const config: TimingConfig | null = useMemo(() => (Object.keys(overrides).length || measured || pp ? { dvfs_overrides: overrides, measured, power_params_ref: pp || null } : null), [overrides, measured, pp])
  const ppQ = useAsync(() => calibrationApi.powerParams().catch(() => []), [])
  const measQ = useAsync(() => (variant ? timingApi.measuredInputs(scenario, variant).catch(() => []) : Promise.resolve([])), [scenario, variant])
  const setMeasured = (m: MeasuredInputs | null) => ctx.navigate(undefined, { mref: m?.measurement_ref || undefined, min: formatMeasuredFlags(m) }, true)
  const condKey = `${dvo}|${mref}|${mflags}|${pp}`
  const baseOpts = { statistic, eis, runtime_scale: scale, cpu_model: cpuModel, ...tpOpt, ...marginOpts(margin), ...(warmup ? { warmup_frames: warmup } : {}) }

  const q = useAsync(() => (!sp.ready ? new Promise<never>(() => {}) : variant ? timingApi.variant(scenario, variant, { ...baseOpts, timeline_frames: frames }, cfg, config) : Promise.reject(new Error('variant를 선택하세요 (Ctrl K)'))), [scenario, variant, statistic, eis, scale, cfg, sp.ready, margin, frames, cpuModel, tpParam, warmup, condKey])
  // what-if (24 sims) starts after the main report so the page never holds two simulation slots at once
  const mainKey = JSON.stringify([ctx.project, scenario, variant, cfg, margin, cpuModel, tpParam, warmup, condKey])
  const [mainReadyKey, setMainReadyKey] = useState<string | null>(null)
  useEffect(() => { if (q.data && sp.ready) setMainReadyKey(mainKey) }, [q.data, sp.ready, mainKey])
  const mainReady = mainReadyKey === mainKey && sp.ready
  const wq = useAsync(() => (variant && mainReady ? timingApi.variant(scenario, variant, { statistic: 'max', eis: 'auto', runtime_scale: 1, include_whatif: true, cpu_model: cpuModel, ...tpOpt, ...marginOpts(margin), ...(warmup ? { warmup_frames: warmup } : {}) }, cfg, config) : Promise.resolve(null)), [scenario, variant, mainReady, cfg, margin, cpuModel, tpParam, warmup, condKey])
  // ⑦ DVFS level ±1/±2 per domain — runs after ④ so at most one simulation slot is held
  const dq = useAsync(() => (variant && mainReady && !wq.loading && !q.loading ? timingApi.dvfsWhatif(scenario, variant, baseOpts, cfg, undefined, DEFAULT_COMBOS, config) : Promise.resolve(null)),
    [scenario, variant, mainReady, wq.loading, q.loading, cfg, margin, statistic, eis, scale, cpuModel, tpParam, warmup, condKey])
  // ③ SW-variance box plot: last, after ⑦ (one simulation slot at a time)
  const [distOn, setDistOn] = usePref<boolean>('tb.dist', true)
  const distQ = useAsync<IntervalDistribution | null>(() => (variant && distOn && mainReady && !dq.loading && !wq.loading && !q.loading ? timingApi.distribution(scenario, variant, baseOpts, cfg, config) : Promise.resolve(null)),
    [scenario, variant, distOn, mainReady, dq.loading, wq.loading, q.loading, cfg, margin, statistic, eis, scale, cpuModel, tpParam, warmup, condKey])
  const r = q.data?.report
  const whatif = wq.data?.report.whatif ?? []
  const effTp = tpParam ?? (r?.stages?.find((x) => x.id === 'nrt')?.throughput === 'pipelined' ? 'pipelined' : r ? 'stage' : policyTp)
  const cond: Condition = { statistic, scale, eis, cpuModel: measured?.cpu ? 'profile' : cpuModel, throughput: effTp, margin, profile: q.data?.config_profile_ref ?? cfg ?? null, overrides, measured, powerParams: pp || null }

  return (
    <div className="page tb-page">
      <div className="toolbar" style={{ flexWrap: 'wrap', gap: 14 }}>
        <Seg label="SW 통계" value={statistic} options={[['max', 'max'], ['mean', 'mean']]} onPick={(v) => set('stat', v === 'max' ? undefined : v)} />
        <Seg label="EIS" value={eis} options={[['auto', `auto${r ? (r.eis.auto ? ' (ON)' : ' (OFF)') : ''}`], ['on', 'ON'], ['off', 'OFF']]} onPick={(v) => set('eis', v === 'auto' ? undefined : v)} />
        <Seg label="차기 SW 증가" value={String(scale)} options={SCALES.map((s) => [String(s), `×${s.toFixed(1)}`])} onPick={(v) => set('scale', v === '1' ? undefined : v)} />
        <span title="가정 = 한 cluster·고정 OPP의 coeff·f·V²·util (기존) · 측정 profile = 이 variant의 측정 CPU profile을 EAS + schedutil로 재현, SW 증가에 따라 OPP·DSU·leakage가 함께 변함 (CPU BW도 측정 bus bytes)">
          <Seg label="CPU 모델" value={cpuModel} options={[['flat', '가정'], ['profile', '측정 profile']]} onPick={(v) => set('cpu', v === 'flat' ? undefined : v)} /></span>
        <span title={'pipeline (buffer) = stage 사이 M2M buffer로 분리: 각 SW task가 1 frame 안에, NRT/Post HW는 IP rule clock. SW+HW 합이 period를 넘으면 latency만 증가하고 fps는 출력 간격으로 판정 (기본)\nstage 1 frame = NRT · Post SW + HW 합이 1 frame 안에 (보수적, 이전 기준)'}>
          <Seg label="처리량 기준" value={tpParam ?? (q.data?.report?.stages?.find((x) => x.id === 'nrt')?.throughput === 'pipelined' ? 'pipelined' : q.data?.report ? 'stage' : policyTp)}
            options={[['pipelined', `pipeline (buffer)${policyTp === 'pipelined' ? ' · 과제 기준' : ''}`], ['stage', `stage 1 frame${policyTp === 'stage' ? ' · 과제 기준' : ''}`]]}
            onPick={(v) => set('tp', v === policyTp ? undefined : v)} /></span>
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
        <MeasuredPicker options={measQ.data ?? []} value={measured} onChange={setMeasured} />
        <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 13 }} className="muted" title="power model 계수 버전 — 기본은 설정 profile의 것. 보정(S5)으로 만든 draft를 골라 비교 · 등록">power params
          <select value={pp} onChange={(e) => set('pp', e.target.value || undefined)} aria-label="power params">
            <option value="">profile 기본</option>
            {(ppQ.data ?? []).map((p) => <option key={p.ref} value={p.ref}>{p.ref}{p.calibrated ? ' · 보정' : ''}{p.status === 'draft' ? ' · draft' : ''}</option>)}
          </select></label>
        <span className="grow" />
        {r && <span className={`badge ${verdictChip(r.verdict.status).cls}`} title={r.verdict.reasons.join('\n')}>{verdictChip(r.verdict.status).label}</span>}
        {r && r.warnings.length > 0 && <button className="badge v-warn" style={{ border: 0, cursor: 'pointer' }} title={r.warnings.slice(0, 8).join('\n')}
          onClick={() => { const d = document.getElementById('tb-warnings') as HTMLDetailsElement | null; if (d) { d.open = true; d.scrollIntoView({ behavior: 'smooth', block: 'center' }) } }}>경고 {r.warnings.length}</button>}
        {r && <span className="chip">{fmt(r.fps, 0)} fps · P {fmt(r.period_ms, 3)} ms</span>}
        {r && <span className="chip" title={r.dvfs.tables.join(', ')}>DVFS {r.dvfs.applied ? r.dvfs.table_ref ?? 'custom' : '미연결'}</span>}
        <button className="btn" title="현재 scenario의 모든 variant를 같은 모델(CPU · 처리량 · margin · 통계)로" onClick={() => ctx.navigate('timing-fleet', { cfg: ctx.params.cfg, margin: ctx.params.margin, cpu: ctx.params.cpu, tp: ctx.params.tp, stat: ctx.params.stat })}>전체 variant →</button>
      </div>
      {r && variant && <ConditionBar cond={cond} verdict={r.verdict.status}
        onSaveEvidence={async () => { const x = await timingApi.saveEvidence(scenario, variant, baseOpts, cfg, config); invalidateCache('/evidence'); invalidateCache('/calibration')
          return x.existed ? `이미 저장된 같은 조건 (${x.evidence_id})` : `저장됨 ${x.evidence_id}` }}
        onRegister={async (reason) => { const x = await timingApi.register(scenario, variant, baseOpts, reason, cfg, config, ctx.project)
          const p = x.promoted[0]; return p ? `등록됨 ${p.id}${x.total_mw ? ` · ${fmt(x.total_mw, 0)} mW` : ''}` : `등록 안 됨: ${x.skipped.map((k) => k.reason).join(', ')}` }}
        onOpenPredictions={() => ctx.navigate('predictions', { sf: scenario })} />}
      {(sp.error || q.error) && <div className="err">{sp.error || q.error}</div>}
      {q.loading && !r && !sp.error && <div className="empty">계산 중…</div>}
      {r && <Body r={r} cfg={q.data?.config_profile_ref ?? null} ctx={ctx} whatif={whatif} battery={battery} dvfs={dq.data ?? null} dvfsLoading={dq.loading || wq.loading} dvfsError={dq.error ?? null} whatLoading={wq.loading} current={{ statistic, eis: r.eis.on, scale }} margin={r.sw_margin?.rt ?? margin}
        frames={frames} setFrames={(n) => set('frames', n === 20 ? undefined : String(n))} warmup={warmup} setWarmup={(n) => set('warmup', n ? String(n) : undefined)}
        overrides={overrides} setOverrides={(o) => set('dvo', formatOverrides(o))}
        dist={distQ.data ?? null} distLoading={distQ.loading} distError={distQ.error ?? null} distOn={distOn} setDistOn={setDistOn} />}
    </div>
  )
}

function Body({ r, cfg, whatif, whatLoading, current, margin, frames, setFrames, warmup, setWarmup, battery, dvfs, dvfsLoading, dvfsError, overrides, setOverrides, dist, distLoading, distError, distOn, setDistOn }: { r: TimingReport; cfg: string | null; ctx: Ctx; whatif: NonNullable<TimingReport['whatif']>; whatLoading: boolean; current: { statistic: string; eis: boolean; scale: number }
  margin: number; frames: number; setFrames: (n: number) => void; warmup: number; setWarmup: (n: number) => void; battery: Battery; dvfs: DvfsWhatIf | null; dvfsLoading: boolean; dvfsError: string | null
  overrides: Record<string, number>; setOverrides: (o: Record<string, number>) => void
  dist: IntervalDistribution | null; distLoading: boolean; distError: string | null; distOn: boolean; setDistOn: (v: boolean) => void }) {
  const [ganttDetail, setGanttDetail] = usePref<boolean>('tb.gantt.detail', true)
  const st = useMemo(() => Object.fromEntries(r.stages.map((s) => [s.id, s])), [r])
  // one clock per DVFS domain: a stage can span several (NRT = CAM + INTCAM); never mix them in one number
  const nrtDomains = useMemo(() => stageDomainsOf(r, 'nrt'), [r])
  const rtReadout = useMemo(() => r.ips.find((i) => i.stage === 'rt' && i.sensor_readout_ms)?.sensor_readout_ms ?? null, [r])
  const iv = r.intervals
  const slack = useMemo(() => stageSlack(r), [r])
  const pipelined = r.stages.some((s) => s.throughput === 'pipelined')
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
    { label: 'SW 여유 · 현재 clock', value: (['rt', 'nrt', 'post'] as const).map((s) => fmt(slack[s], 1)).join(' / '), unit: 'ms',
      note: `RT / NRT / Post — SW가 더 쓸 수 있는 시간${pipelined ? ' (NRT·Post = period − 최장 SW task)' : ' (NRT·Post = period − SW − HW)'}`,
      bad: (['rt', 'nrt', 'post'] as const).some((s) => slack[s] < 0), small: true },
    { label: 'Preview / Video 간격', value: `${fmt(iv.preview.max_ms, 2)} / ${fmt(iv.video.max_ms, 2)}`, unit: 'ms', note: iv.ok ? `목표 ${fmt(iv.target_ms, 2)} ±${fmt(iv.tolerance * 100, 1)}% ✓` : '목표 이탈', bad: !iv.ok },
    { label: 'Power · BW', value: fmt(r.power.total_mw, 0), unit: `mW · ${maText(r.power.total_mw, battery)}@Vbat`, note: `CPU ${fmt(r.power.cpu_mw, 0)} · HW ${fmt(r.power.hw_mw, 0)} · BW ${fmt(r.power.bw_mw, 0)} · ${fmt(r.bw.total_mbs / 1000, 2)} GB/s`, bad: false, prov },
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
      <b>참고 (clock ↑ · pipeline latency)</b> {r.verdict.notes!.map((x) => <div key={x} className="mono" style={{ fontSize: 12 }}>{x}</div>)}</div>}
    {r.measured_compare && <MeasuredCompareCard data={r.measured_compare} battery={battery} />}
    <div className="tb-grid">
      <Card id="slot" title="① 1 frame 예산 — stage별 slot" note={pipelined ? 'stage는 M2M buffer로 pipeline · 각 SW task / HW stage가 1 frame 안에 · 합이 넘으면 latency만 증가 (fps = 출력 간격)' : 'stage 1 frame 기준 · 각 stage SW+HW가 1 frame 안에 끝나야 함 (보수적)'} defaultWide><SlotBudget report={r} margin={margin} /></Card>
      <Card id="clock" title="⑤ IP별 필요 clock · DVFS level (계산 / override)" note={`DVFS domain별 묶음 · domain level = 최고 요구 IP · RT = sensor readout 기준 · Output ${pct0(margin)} rule · NRT·Post = SW 반영 예산`}>
        <ClockChart ips={r.ips} dvfsApplied={r.dvfs.applied} margin={margin} />
        <DvfsOverrideTable report={r} overrides={overrides} onChange={setOverrides} /></Card>
      <Card id="power" title="⑥ 예상 Power · BW" note="CPU(SW) / HW(IP별) / BW(HW·SW) 비중"><PowerBw report={r} /></Card>
      <Card id="gantt" title="② Pipeline timeline" note={`${r.timeline.length ? Math.max(...r.timeline.map((t) => t.frame)) + 1 : 0} frames · 점선 = ${fmt(r.fps, 0)} fps frame 경계 (${fmt(r.period_ms, 2)} ms)`} defaultWide
        actions={<span style={{ display: 'inline-flex', gap: 6 }}>
          <div className="seg sm" role="group" aria-label="timeline 상세도"><button className={ganttDetail ? 'on' : ''} onClick={() => setGanttDetail(true)} title="IP · SW task별 행">상세</button><button className={!ganttDetail ? 'on' : ''} onClick={() => setGanttDetail(false)} title="stage별 묶음">요약</button></div>
          <div className="seg sm" role="group" aria-label="timeline frame 수">{[6, 12, 20].map((n) => <button key={n} className={frames === n ? 'on' : ''} onClick={() => setFrames(n)}>{n} frame</button>)}</div></span>}><Gantt report={r} detail={ganttDetail} /></Card>
      <Card id="interval" title="③ 출력 frame 간격 · pipeline latency" defaultWide note="합격 기준 = 간격 · latency는 참고 · jitter · drop · SW 편차 분포는 참고 지표"
        actions={<div className="seg sm" role="group" aria-label="warm-up 제외" title="앞쪽 출력 간격 N개를 판정에서 제외 (pipeline fill · AE/AWB 안정화). 0 = 모두 판정">{[0, 1, 2, 4].map((n) => <button key={n} className={warmup === n ? 'on' : ''} onClick={() => setWarmup(n)}>{n ? `warm-up ${n}` : 'warm-up 없음'}</button>)}</div>}><Intervals report={r} />
        <label className="faint" style={{ fontSize: 12, display: 'inline-flex', gap: 4, marginTop: 6 }}><input type="checkbox" checked={distOn} onChange={(e) => setDistOn(e.target.checked)} />SW 편차 box plot</label>
        {distOn && (distError ? <div className="err">{distError}</div> : dist ? <IntervalBoxes data={dist} /> : distLoading ? <div className="faint" style={{ fontSize: 12 }}>SW 편차 분포 계산 중…</div> : null)}</Card>
      <Card id="whatif" title="④ 차기 SW 증가 → NRT 필요 clock" note="NRT 예산 = period − SW(runtime+latency) · DVFS domain별 (CAM / INTCAM …)">
        {whatLoading && !whatif.length ? <div className="empty">what-if 계산 중…</div> : <WhatIf rows={whatif} current={current} margin={margin} />}
      </Card>
      <Card id="dvfs" title="⑦ IP clock level ±1 / ±2 → SW 여유 · Power · BW" note={`DVFS domain (RT / NRT / M2M) 하나를 L±1·L±2로 고정, 나머지는 현재 그대로 · ${batteryNote(battery)}`} defaultWide>
        {dvfsError ? <div className="err">{dvfsError}</div> : !dvfs ? <div className="empty">{dvfsLoading ? 'level what-if 계산 중…' : '—'}</div> : <DvfsWhatIfTable data={dvfs} battery={battery} />}
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
