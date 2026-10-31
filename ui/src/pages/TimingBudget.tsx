import { useEffect, useMemo, useState } from 'react'
import type { Ctx } from '../App'
import { updateExperimentContext } from '../lib/experimentContext'
import { useAsync } from '../lib/route'
import { SW_MARGINS, runtimeScaleOf, fmt, stageDomainsOf, stageSlack, marginOf, marginOpts, pct0, timingApi, verdictChip, DEFAULT_STATISTIC, STAT_TIP, appliedCpuModel, statisticOf, type CpuModel, type EisMode, type ThroughputModel, type TimingReport, type DvfsWhatIf, type TimingConfig, type IntervalDistribution, DEFAULT_COMBOS, formatOverrides, parseOverrides, parseMeasured, formatMeasuredFlags, type MeasuredInputs } from '../lib/timingBudget'
import { Card, ClockChart, Gantt, Intervals, PowerBw, SlotBudget, WhatIf } from '../components/TimingCharts'
import { ProvBadge } from '../components/Provenance'
import { powerScope, type Prov } from '../lib/provenance'
import { ProfileSelect } from '../components/ProfileSelect'
import { DEFAULT_POWER_MODEL, defaultPowerParams, effectiveProfile, useSimProfiles } from '../lib/simProfile'
import { TimingInputsHelp } from '../components/TimingInputsHelp'
import { maText, useBattery, batteryNote, type Battery } from '../lib/battery'
import { DvfsWhatIfTable } from '../components/DvfsWhatIf'
import { useReferences } from '../lib/review'
import { usePref } from '../components/Layout'
import { invalidateCache } from '../lib/api'
import { ConditionBar, DvfsOverrideTable, IntervalBoxes, MeasuredCompareCard, MeasuredPicker, type Condition } from '../components/TimingWorkbench'
import { calibrationApi } from '../lib/calibration'
import { useRegistrationGuard } from '../lib/registration'
import { RegistrationBasis } from '../components/RegistrationBasis'

const SCALES = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5]

export function TimingBudgetPage({ ctx }: { ctx: Ctx }) {
  const { scenario, variant } = ctx
  const statistic = statisticOf(ctx.params.stat)
  const eis = (ctx.params.eis === 'on' || ctx.params.eis === 'off' ? ctx.params.eis : 'auto') as EisMode
  const scale = runtimeScaleOf(ctx.params.scale)
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
  const prof = effectiveProfile(sp.profiles, cfg, sp.basis)
  // power params must target the profile's power model (the server rejects a mismatch)
  const runModel = String(prof?.run_config?.power_model ?? DEFAULT_POWER_MODEL)
  const defaultPp = defaultPowerParams(sp.basis, prof)
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
  const [extrasOn, setExtrasOn] = useState(false)
  const wq = useAsync(() => (variant && extrasOn && mainReady ? timingApi.variant(scenario, variant, { statistic: 'max', eis: 'auto', runtime_scale: 1, include_whatif: true, cpu_model: cpuModel, ...tpOpt, ...marginOpts(margin), ...(warmup ? { warmup_frames: warmup } : {}) }, cfg, config) : Promise.resolve(null)), [scenario, variant, extrasOn, mainReady, cfg, margin, cpuModel, tpParam, warmup, condKey])
  // ⑦ DVFS level ±1/±2 per domain — runs after ⑥ so at most one simulation slot is held
  const dq = useAsync(() => (variant && extrasOn && mainReady && !wq.loading && !q.loading ? timingApi.dvfsWhatif(scenario, variant, baseOpts, cfg, undefined, DEFAULT_COMBOS, config) : Promise.resolve(null)),
    [scenario, variant, extrasOn, mainReady, wq.loading, q.loading, cfg, margin, statistic, eis, scale, cpuModel, tpParam, warmup, condKey])
  // ⑤ SW-variance box plot: last, after ⑦ (one simulation slot at a time)
  const [distOn, setDistOn] = usePref<boolean>('tb.dist', false)
  const distQ = useAsync<IntervalDistribution | null>(() => (variant && distOn && mainReady && !dq.loading && !wq.loading && !q.loading ? timingApi.distribution(scenario, variant, baseOpts, cfg, config) : Promise.resolve(null)),
    [scenario, variant, distOn, mainReady, dq.loading, wq.loading, q.loading, cfg, margin, statistic, eis, scale, cpuModel, tpParam, warmup, condKey])
  const r = q.data?.report
  const guard = useRegistrationGuard([{ scenario_id: scenario, variant_id: variant }], ctx.project, r?.condition_hash ?? '')
  const whatif = wq.data?.report.whatif ?? []
  const effTp = tpParam ?? (r?.stages?.find((x) => x.id === 'nrt')?.throughput === 'pipelined' ? 'pipelined' : r ? 'stage' : policyTp)
  const cond: Condition = { statistic, scale, eis, cpuModel: measured?.cpu ? 'profile' : cpuModel, throughput: effTp, margin, profile: q.data?.config_profile_ref ?? cfg ?? null, overrides, measured, powerParams: pp || null,
    basis: q.data?.basis_code ? { code: q.data.basis_code, overrides: q.data.basis_overrides ?? [] } : null }
  // B2 vs B2*: the server's resolution once calculated; before that, what the URL already says
  const basisOv = q.data ? (q.data.basis_overrides ?? []) : sp.basis ? [...(sp.followsBasis ? [] : ['config_profile']), ...(pp && pp !== sp.basis.power_params_ref ? ['power_params'] : [])] : undefined
  const experimentBlocked = cpuModel === 'profile' || !!measured ? '측정 replay는 변경 조건으로 외삽할 수 없습니다. 가정 CPU·정의 SW 조건을 선택하세요.'
    : !sp.followsBasis ? '기준 외 profile은 What-if의 모델 설정에서 명시적으로 지정하세요.' : null
  const startExperiment = () => {
    updateExperimentContext({ project_ref: ctx.project, scenario_id: scenario, variant_id: variant }, {
      changes: [], baseline_hash: undefined, analysis_hash: undefined, active_candidate_id: undefined,
      basis_ref: q.data?.basis_ref ?? sp.basis?.id, basis_label: q.data?.basis_code ?? sp.basis?.code,
      config: { ...(Object.keys(overrides).length ? { dvfs_overrides: overrides } : {}), ...(pp ? { power_params_ref: pp } : {}) },
      options: { ...baseOpts, throughput_model: effTp, timeline_frames: frames }, comparison: 'retune',
    })
    ctx.navigate('whatif', { experiment: undefined })
  }

  return (
    <div className="page tb-page">
      <div className="toolbar" style={{ flexWrap: 'wrap', gap: 14 }}>
        <button className="btn" disabled={!r || !!experimentBlocked} title={experimentBlocked ?? '현재 SW·DVFS·power 설정을 조건 실험의 기준으로 전달'} onClick={startExperiment}>이 계산 조건으로 실험 →</button>
        <span title={STAT_TIP}><Seg label="SW 통계" value={statistic} options={[['mean', 'mean (기본)'], ['max', 'max']]} onPick={(v) => set('stat', v === DEFAULT_STATISTIC ? undefined : v)} /></span>
        <Seg label="EIS" value={eis} options={[['auto', `auto${r ? (r.eis.auto ? ' (ON)' : ' (OFF)') : ''}`], ['on', 'ON'], ['off', 'OFF']]} onPick={(v) => set('eis', v === 'auto' ? undefined : v)} />
        <Seg label="차기 SW 증가" value={String(scale)} options={[...new Set([...SCALES, scale])].sort((a, b) => a - b).map((s) => [String(s), `×${Number.isInteger(s) ? s.toFixed(1) : s}`])} onPick={(v) => set('scale', v === '1' ? undefined : v)} />
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
        <ProfileSelect profiles={sp.profiles} value={cfg} onChange={(v) => set('cfg', v)} basis={sp.basis} followsBasis={sp.followsBasis} overrides={basisOv} />
        <MeasuredPicker options={measQ.data ?? []} value={measured} onChange={setMeasured} />
        <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 13 }} className="muted"
          title={sp.basis ? `power model 계수 버전 — 기본은 예측 기준 ${sp.basis.code}가 고정한 ${sp.basis.power_params_ref ?? 'profile 계수'}. 다른 것을 고르면 ${sp.basis.code}*(기준 외)` : 'power model 계수 버전 — 기본은 설정 profile의 것. 보정(S5)으로 만든 draft를 골라 비교 · 등록'}>power params
          <select value={pp} onChange={(e) => set('pp', e.target.value || undefined)} aria-label="power params" style={{ maxWidth: 270 }}
            className={sp.basis && pp && pp !== sp.basis.power_params_ref ? 'sel-off-basis' : undefined}>
            <option value="">{sp.basis ? `기준 ${sp.basis.code} · ${sp.basis.power_params_ref ?? 'profile 계수'}` : `profile 기본 · ${defaultPp ?? '내장 계수'}`}</option>
            {(ppQ.data ?? []).map((p) => { const off = !!p.ip_model && p.ip_model !== runModel && p.ref !== pp
              return <option key={p.ref} value={p.ref} disabled={off} title={off ? `${p.ip_model}용 계수 — 이 profile의 power model은 ${runModel}` : p.description ?? undefined}>
                {p.ref}{p.calibrated ? ' · 보정' : ''}{p.status === 'draft' ? ' · draft' : ''}{off ? ` · ${p.ip_model} (power model 불일치)` : ''}</option> })}
          </select></label>
        <TimingInputsHelp inputs={{ statistic, throughput: effTp, margin, profile: prof, basisCode: sp.basis?.code ?? null, measured,
          measuredOption: (measQ.data ?? []).find((o) => o.id === measured?.measurement_ref) ?? null, powerParams: pp, defaultPowerParams: defaultPp,
          pinnedDomains: Object.keys(overrides).sort(), cpuModel: appliedCpuModel(r, measured?.cpu ? 'profile' : cpuModel) }} />
        <span className="grow" />
        {r && <span className={`badge ${verdictChip(r.verdict.status).cls}`} title={r.verdict.reasons.join('\n')}>{verdictChip(r.verdict.status).label}</span>}
        {r && r.warnings.length > 0 && <button className="badge v-warn" style={{ border: 0, cursor: 'pointer' }} title={r.warnings.slice(0, 8).join('\n')}
          onClick={() => { const d = document.getElementById('tb-warnings') as HTMLDetailsElement | null; if (d) { d.open = true; d.scrollIntoView({ behavior: 'smooth', block: 'center' }) } }}>경고 {r.warnings.length}</button>}
        {r && <span className="chip">{fmt(r.fps, 0)} fps · P {fmt(r.period_ms, 3)} ms</span>}
        {r && <span className="chip" title={r.dvfs.tables.join(', ')}>DVFS {r.dvfs.applied ? r.dvfs.table_ref ?? 'custom' : '미연결'}</span>}
        <button className="btn" title="현재 scenario의 모든 variant를 같은 모델(CPU · 처리량 · margin · 통계)로" onClick={() => ctx.navigate('timing-fleet', { cfg: ctx.params.cfg, margin: ctx.params.margin, cpu: ctx.params.cpu, tp: ctx.params.tp, stat: ctx.params.stat })}>전체 variant →</button>
      </div>
      {r && variant && <RegistrationBasis guard={guard} />}
      {r && variant && <ConditionBar key={JSON.stringify([scenario, variant, cond, r.condition_hash])} cond={cond} verdict={r.verdict.status} registrationReady={guard.ready}
        onSaveEvidence={async () => { const x = await timingApi.saveEvidence(scenario, variant, baseOpts, cfg, config, r.condition_hash); invalidateCache('/evidence'); invalidateCache('/calibration'); invalidateCache(`/scenarios/${encodeURIComponent(scenario)}`)
          return x.existed ? `이미 저장된 같은 조건 (${x.evidence_id})` : `저장됨 ${x.evidence_id}` }}
        onRegister={async (reason) => { if (!guard.ready || !guard.expected) throw new Error('등록 기준을 먼저 확인하세요.')
          try { const x = await timingApi.register(scenario, variant, baseOpts, reason, cfg, config, ctx.project, r.condition_hash, guard.expected[0].prediction_id)
            guard.refresh(); const p = x.promoted[0]; return p ? `등록됨 ${p.id}${x.total_mw ? ` · ${fmt(x.total_mw, 0)} mW` : ''}` : `등록 안 됨: ${x.skipped.map((k) => k.reason).join(', ')}`
          } catch (e) { throw new Error(guard.fail(e)) } }}
        onOpenPredictions={() => ctx.navigate('predictions', { sf: scenario })} />}
      {(sp.error || q.error) && <div className="err">{sp.error || q.error}</div>}
      {q.loading && !r && !sp.error && <div className="empty">계산 중…</div>}
      <div className="workflow-note"><label><input type="checkbox" checked={extrasOn} onChange={(e) => setExtrasOn(e.target.checked)} /> 보조 탐색 계산 (SW 증가 · DVFS 조합)</label><span>기준 결과를 먼저 표시합니다. 보조 탐색을 켜면 조건 변경 시 순서대로 다시 계산합니다.</span></div>
      {r && <Body r={r} cfg={q.data?.config_profile_ref ?? null} ctx={ctx} extrasOn={extrasOn} whatif={whatif} battery={battery} dvfs={dq.data ?? null} dvfsLoading={dq.loading || wq.loading} dvfsError={dq.error ?? null} whatLoading={wq.loading} current={{ statistic, eis: r.eis.on, scale }} margin={r.sw_margin?.rt ?? margin}
        frames={frames} setFrames={(n) => set('frames', n === 20 ? undefined : String(n))} warmup={warmup} setWarmup={(n) => set('warmup', n ? String(n) : undefined)}
        overrides={overrides} setOverrides={(o) => set('dvo', formatOverrides(o))}
        dist={distQ.data ?? null} distLoading={distQ.loading} distError={distQ.error ?? null} distOn={distOn} setDistOn={setDistOn} />}
    </div>
  )
}

function Body({ r, cfg, extrasOn, whatif, whatLoading, current, margin, frames, setFrames, warmup, setWarmup, battery, dvfs, dvfsLoading, dvfsError, overrides, setOverrides, dist, distLoading, distError, distOn, setDistOn }: { r: TimingReport; cfg: string | null; ctx: Ctx; extrasOn: boolean; whatif: NonNullable<TimingReport['whatif']>; whatLoading: boolean; current: { statistic: string; eis: boolean; scale: number }
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
      <Card id="clock" title="② IP별 필요 clock · DVFS level (계산 / override)" note={`DVFS domain별 묶음 · domain level = 최고 요구 IP · RT = sensor readout 기준 · Output ${pct0(margin)} rule · NRT·Post = SW 반영 예산`}>
        <ClockChart ips={r.ips} dvfsApplied={r.dvfs.applied} margin={margin} />
        <DvfsOverrideTable report={r} overrides={overrides} onChange={setOverrides} /></Card>
      <Card id="power" title="③ 예상 Power · BW" note="CPU(SW) / HW(IP별) / BW(HW·SW) 비중"><PowerBw report={r} /></Card>
      <Card id="gantt" title="④ Pipeline timeline" note={`${r.timeline.length ? Math.max(...r.timeline.map((t) => t.frame)) + 1 : 0} frames · 점선 = ${fmt(r.fps, 0)} fps frame 경계 (${fmt(r.period_ms, 2)} ms)`} defaultWide
        actions={<span style={{ display: 'inline-flex', gap: 6 }}>
          <div className="seg sm" role="group" aria-label="timeline 상세도"><button className={ganttDetail ? 'on' : ''} onClick={() => setGanttDetail(true)} title="IP · SW task별 행">상세</button><button className={!ganttDetail ? 'on' : ''} onClick={() => setGanttDetail(false)} title="stage별 묶음">요약</button></div>
          <div className="seg sm" role="group" aria-label="timeline frame 수">{[6, 12, 20].map((n) => <button key={n} className={frames === n ? 'on' : ''} onClick={() => setFrames(n)}>{n} frame</button>)}</div></span>}><Gantt report={r} detail={ganttDetail} /></Card>
      <Card id="interval" title="⑤ 출력 frame 간격 · pipeline latency" defaultWide note="합격 기준 = 간격 · latency는 참고 · jitter · drop · SW 편차 분포는 참고 지표"
        actions={<div className="seg sm" role="group" aria-label="warm-up 제외" title="앞쪽 출력 간격 N개를 판정에서 제외 (pipeline fill · AE/AWB 안정화). 0 = 모두 판정">{[0, 1, 2, 4].map((n) => <button key={n} className={warmup === n ? 'on' : ''} onClick={() => setWarmup(n)}>{n ? `warm-up ${n}` : 'warm-up 없음'}</button>)}</div>}><Intervals report={r} />
        <label className="faint" style={{ fontSize: 12, display: 'inline-flex', gap: 4, marginTop: 6 }}><input type="checkbox" checked={distOn} onChange={(e) => setDistOn(e.target.checked)} />SW 편차 box plot</label>
        {distOn && (distError ? <div className="err">{distError}</div> : dist ? <IntervalBoxes data={dist} /> : distLoading ? <div className="faint" style={{ fontSize: 12 }}>SW 편차 분포 계산 중…</div> : null)}</Card>
      <Card id="whatif" title="⑥ 차기 SW 증가 → NRT 필요 clock" note="NRT 예산 = period − SW(runtime+latency) · DVFS domain별 (CAM / INTCAM …)">
        {!extrasOn ? <div className="empty">위의 보조 탐색 계산을 켜면 SW 증가 조건을 비교합니다.</div> : whatLoading && !whatif.length ? <div className="empty">what-if 계산 중…</div> : <WhatIf rows={whatif} current={current} margin={margin} />}
      </Card>
      <Card id="dvfs" title="⑦ IP clock level ±1 / ±2 → SW 여유 · Power · BW" note={`DVFS domain (RT / NRT / M2M) 하나를 L±1·L±2로 고정, 나머지는 현재 그대로 · ${batteryNote(battery)}`} defaultWide>
        {!extrasOn ? <div className="empty">위의 보조 탐색 계산을 켜면 DVFS 조합을 비교합니다.</div> : dvfsError ? <div className="err">{dvfsError}</div> : !dvfs ? <div className="empty">{dvfsLoading ? 'level what-if 계산 중…' : '—'}</div> : <DvfsWhatIfTable data={dvfs} battery={battery} />}
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
