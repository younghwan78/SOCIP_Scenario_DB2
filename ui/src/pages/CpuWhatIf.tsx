import { useEffect, useMemo, useRef, useState } from 'react'
import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { fmt } from '../lib/timingBudget'
import {
  caseParts, clusterCover, cpuApi, freqChanges, knobHow, knobLabel, movedLabel, parseLevels, rankTopologies,
  type CpuInputs, type CpuSweep, type CpuSweepRequest, type Knob, type SweepCase, type SweepRangeCluster,
} from '../lib/cpu'
import { Card } from '../components/TimingCharts'
import { DataTable, type Column } from '../components/DataTable'
import { PowerDeltaTable, PowerStack, type PowerRow } from '../components/PowerModelCharts'
import { partColor, sortClusters } from '../lib/powerModel'
import { CPU_HELP, threadLabel } from '../components/CpuHelp'
import { usePref } from '../components/Layout'
import { DsuPanel, sweepEvaluator } from '../components/DsuPanel'
import { applyDsu, type DsuPolicy } from '../lib/dsu'
import { applyDsuRebalance, defaultPool, rebalanceApi, type CpuRebalance, type CpuRebalanceRequest } from '../lib/rebalance'
import { AssumptionSensitivity, CrossSocCompare, RebalanceResults, RebalanceSetup, type Knob as RbKnob, type SetupRow, type TaskState } from '../components/RebalanceView'
import { ModelCheckDist } from '../components/ClockResidency'
import { CpuPurpose, type CpuRun } from '../components/CpuPurpose'

type TaskEdit = { sweep: string[] | null; threads: string; budget: string; growth: string }
type Adv = { freqMargin: string; fitsMargin: string; utilModel: '' | 'util_est' | 'pelt_avg'; halflife: string; boost: '' | 'on' | 'off'; emStatic: '' | 'on' | 'off' }

const NO_ADV: Adv = { freqMargin: '', fitsMargin: '', utilModel: '', halflife: '', boost: '', emStatic: '' }
const num = (v: string): number | undefined => (v.trim() !== '' && Number.isFinite(Number(v)) ? Number(v) : undefined)
const tri = (v: '' | 'on' | 'off'): boolean | undefined => (v === '' ? undefined : v === 'on')
const signed = (v: number, d = 1) => `${v >= 0 ? '+' : ''}${fmt(v, d)}`

// CPU what-if = Android EAS + schedutil reproduction of a measured per-frame profile,
// then an automatic sweep of the knobs a device actually has (cpuset / affinity, uclamp),
// ranked against "현재" (measured placement) by power.
export function CpuWhatIfPage({ ctx }: { ctx: Ctx }) {
  const inputs = useAsync(() => cpuApi.inputs(), [])
  const [profile, setProfile] = useState('')
  const [target, setTarget] = useState('')
  const [base, setBase] = useState('')
  const [reference, setReference] = useState<'measured' | 'eas'>('measured')
  const [fps, setFps] = useState(30)
  const [growth, setGrowth] = useState(1.0)
  const [pgEff, setPgEff] = useState(0.9)
  const [bwScale, setBwScale] = useState(1.0)
  const [knobs, setKnobs] = useState<Knob[]>(['pin', 'upto'])
  const [uMax, setUMax] = useState('')
  const [uMin, setUMin] = useState('')
  const [adv, setAdv] = useState<Adv>(NO_ADV)
  const [edits, setEdits] = useState<Record<string, TaskEdit>>({})
  const [rawResult, setResult] = useState<CpuSweep | null>(null)
  // DSU assumption: exp = client-side experiment on the returned cases, dsuReq = rule sent to the server
  const [dsuExp, setDsuExp] = useState<DsuPolicy | null>(null)
  const [dsuReq, setDsuReq] = useState<DsuPolicy | null>(null)
  const result = useMemo(() => (rawResult ? applyDsu(rawResult, dsuExp) : null), [rawResult, dsuExp])
  const sweepEval = useMemo(() => (rawResult ? sweepEvaluator(rawResult) : () => ({ refMw: 0, bestMw: null, deltaMw: null, refDsuMhz: null, bestDsuMhz: null, bestKey: '' })), [rawResult])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const requestId = useRef(0)
  const inputSelection = useRef('')
  const [sel, setSel] = useState<string>('')
  const [showAllBetter, setShowAllBetter] = useState(false)
  const [top, setTop] = usePref<number>('cpu.top', 60)
  // mode: MID 재분배 (split tasks over the MID clusters) or the automatic knob sweep
  const [mode, setMode] = usePref<'rebalance' | 'sweep'>('cpu.mode', 'rebalance')
  const [rbRaw, setRbRaw] = useState<CpuRebalance | null>(null)
  const [rbTop, setRbTop] = usePref<number>('cpu.rb.top', 20)
  const [poolSel, setPoolSel] = useState<string[] | null>(null)
  const [taskStates, setTaskStates] = useState<Record<string, TaskState>>({})
  // cgroup per task name (assumption, kept across profiles — same logical task names)
  const [groups, setGroups] = usePref<Record<string, string>>('cpu.rb.cgroup', {})
  const [rbSel, setRbSel] = useState('')
  // C6: the same profile rebalanced on another project's topology (sequential run, one admission slot at a time)
  const [cmpTarget, setCmpTarget] = useState('')
  const [rbKnob, setRbKnob] = usePref<RbKnob>('cpu.rb.knob', 'cpuset')
  const [cmpRb, setCmpRb] = useState<CpuRebalance | null>(null)
  const [cmpErr, setCmpErr] = useState<string | null>(null)
  const [runs, setRuns] = useState<CpuRun[]>([])
  const [pendingRun, setPendingRun] = useState(false)
  const rb = useMemo(() => (rbRaw ? applyDsuRebalance(rbRaw, dsuExp) : null), [rbRaw, dsuExp])

  const prof = inputs.data?.profiles.find((p) => p.id === profile)
  const topo = inputs.data?.topologies.find((t) => t.id === target)
  const clusterNames = useMemo(() => sortClusters(result?.range.clusters.map((c) => c.name) ?? topo?.clusters ?? []), [result, topo])
  const cpuKeys = clusterNames.map((c) => `cpu.${c}`)
  const colorOf = (c: string) => partColor(`cpu.${c}`, cpuKeys)
  const rangeCluster = (c: string): SweepRangeCluster | undefined => result?.range.clusters.find((x) => x.name === c)
  const tasks = result?.range.tasks.map((t) => t.task) ?? (prof?.tasks ?? []).map((t) => t.task)
  const edit = (t: string): TaskEdit => edits[t] ?? { sweep: null, threads: '', budget: '', growth: '' }
  const setEdit = (t: string, patch: Partial<TaskEdit>) => setEdits((m) => ({ ...m, [t]: { ...edit(t), ...patch } }))

  useEffect(() => {
    if (!inputs.data) return
    // U10: open on a usable profile — task cycles present, current variant/scenario/project first
    if (!profile && inputs.data.profiles[0]) setProfile(rankProfiles(inputs.data.profiles, ctx)[0].id)
  }, [inputs.data]) // eslint-disable-line react-hooks/exhaustive-deps
  // default topology = the one whose clusters cover the profile's measured clusters (then newest version);
  // re-picked on profile change until the user chooses a topology explicitly
  const targetPicked = useRef(false)
  useEffect(() => {
    if (!inputs.data?.topologies.length || targetPicked.current) return
    setTarget(rankTopologies(inputs.data.topologies, prof)[0].id)
  }, [inputs.data, prof]) // eslint-disable-line react-hooks/exhaustive-deps

  const request = (taskEdits = edits, dsu = dsuReq): CpuSweepRequest => {
    const pick = (k: 'budget' | 'growth' | 'threads') => Object.fromEntries(Object.entries(taskEdits)
      .map(([t, e]) => [t, num(e[k])] as const).filter(([, v]) => v !== undefined)) as Record<string, number>
    return {
      cpu_profile_ref: profile, power_params_ref: target, base_power_params_ref: base || undefined, fps,
      default_growth: growth, growth: pick('growth'), budgets_ms: pick('budget'), threads: pick('threads'),
      sweep_clusters: Object.fromEntries(Object.entries(taskEdits).filter(([, e]) => e.sweep !== null).map(([t, e]) => [t, e.sweep as string[]])),
      knobs, uclamp_max_levels: parseLevels(uMax), uclamp_min_levels: parseLevels(uMin), reference,
      power_gating_eff: pgEff, cpu_bw_scale: bwScale,
      freq_margin: num(adv.freqMargin), fits_margin: num(adv.fitsMargin), util_model: adv.utilModel || undefined,
      pelt_halflife_ms: num(adv.halflife), deadline_boost: tri(adv.boost), energy_includes_static: tri(adv.emStatic), top,
      ...(dsu ? { dsu_mode: dsu.mode, dsu_vote: dsu.mode === 'vote' ? dsu.vote : undefined, dsu_fixed_mhz: dsu.mode === 'fixed' ? dsu.fixed_mhz : undefined } : {}),
    }
  }
  const poolNames = rbRaw?.clusters.map((c) => c.name) ?? sortClusters(topo?.clusters ?? [])
  const pool = poolSel ?? rbRaw?.default_pool ?? defaultPool(poolNames)
  const rbRequest = (base: CpuSweepRequest): CpuRebalanceRequest => {
    const locks: Record<string, string> = {}
    for (const [t, st] of Object.entries(taskStates)) if (st === 'exclude') locks[t] = 'exclude'; else if (st.startsWith('pin:')) locks[t] = st.slice(4)
    const byGroup = new Map<string, string[]>()
    const present = new Set(rbRows.map((r) => r.task))
    for (const [t, g] of Object.entries(groups)) if (g && present.has(t) && (taskStates[t] ?? 'auto') === 'auto') byGroup.set(g, [...(byGroup.get(g) ?? []), t])
    return { ...base, top: rbTop, pool, locks, co_move: [...byGroup.values()].filter((g) => g.length > 1) }
  }
  const runRb = async (payload: CpuRebalanceRequest) => {
    const id = ++requestId.current
    setBusy(true); setError(null)
    try {
      const r = await rebalanceApi.run(payload)
      if (id !== requestId.current) return
      setRbRaw(r); setRbSel(r.cases[0] ? `c${r.cases[0].rank}` : 'ref')
      setCmpRb(null); setCmpErr(null)
      let cmpRes: CpuRebalance | null = null
      if (cmpTarget && cmpTarget !== payload.power_params_ref) {
        const exclude = Object.fromEntries(Object.entries(payload.locks).filter(([, v]) => v === 'exclude'))
        try {
          const c = await rebalanceApi.run({ ...payload, power_params_ref: cmpTarget, base_power_params_ref: payload.base_power_params_ref || payload.power_params_ref, pool: [], locks: exclude })
          if (id === requestId.current) { setCmpRb(c); cmpRes = c }
        } catch (e) { if (id === requestId.current) setCmpErr(String((e as Error).message ?? e)) }
      }
      const { default_growth: _growth, cpu_bw_scale: _bw, ...runContext } = payload
      if (id === requestId.current) setRuns((rs) => [...rs.slice(-11), {
        context: JSON.stringify(runContext),
        n: (rs[rs.length - 1]?.n ?? 0) + 1, profile: payload.cpu_profile_ref, target: payload.power_params_ref, cmp: cmpRes ? cmpTarget : null,
        growth: payload.default_growth ?? 1, bwScale: payload.cpu_bw_scale ?? 1, pgEff: payload.power_gating_eff ?? 0.9,
        ref_mw: r.reference.total_mw, best_mw: r.best?.total_mw ?? null, cmp_ref_mw: cmpRes?.reference.total_mw ?? null, cmp_best_mw: cmpRes?.best?.total_mw ?? null,
        winner: r.strategies?.winner ?? null, bw_mbs: r.cpu_bw_mbs ?? null }])
    } catch (e) {
      if (id === requestId.current) setError(String((e as Error).message ?? e))
    } finally { if (id === requestId.current) setBusy(false) }
  }
  const run = async (payload = request()) => {
    if (!profile || !target) return
    if (mode === 'rebalance') return runRb(rbRequest(payload))
    const id = ++requestId.current
    setBusy(true); setError(null)
    try {
      const r = await cpuApi.sweep(payload)
      if (id !== requestId.current) return
      setResult(r); setSel(r.cases[0] ? `c${r.cases[0].rank}` : '')
    } catch (e) {
      if (id === requestId.current) setError(String((e as Error).message ?? e))
    } finally { if (id === requestId.current) setBusy(false) }
  }
  // first look: EAS reproduction + automatic range as soon as the inputs are chosen
  useEffect(() => {
    const selection = JSON.stringify([profile, target, base])
    const changed = inputSelection.current !== selection
    inputSelection.current = selection
    if (changed) { setEdits({}); setDsuExp(null); setDsuReq(null); setPoolSel(null); setTaskStates({}); setRbRaw(null) }
    setResult(null)
    if (profile && target) {
      const req = request(changed ? {} : edits, changed ? null : dsuReq)
      if (mode === 'rebalance') void runRb(changed ? { ...req, top: rbTop, pool: [], locks: {}, co_move: [] } : rbRequest(req))
      else void run(req)
    }
    return () => { ++requestId.current }
  }, [profile, target, base, reference, mode]) // eslint-disable-line react-hooks/exhaustive-deps

  const toggleCell = (task: string, cl: string) => {
    const auto = result?.range.tasks.find((t) => t.task === task)
    const cur = edit(task).sweep ?? clusterNames.filter((c) => auto?.cells[c]?.in_sweep)
    setEdit(task, { sweep: cur.includes(cl) ? cur.filter((c) => c !== cl) : [...cur, cl] })
  }
  // bulk range edits (one state update, no sweep until 계산): column = cluster for every sweepable task
  const sweepable = (t: string) => t !== '(other)'
  const autoSet = (t: string) => clusterNames.filter((c) => result?.range.tasks.find((x) => x.task === t)?.cells[c]?.in_sweep)
  const inSweepOf = (t: string) => edit(t).sweep ?? autoSet(t)
  const columnState = (c: string): 'all' | 'some' | 'none' => {
    const ts = tasks.filter(sweepable), n = ts.filter((t) => inSweepOf(t).includes(c)).length
    return n === 0 ? 'none' : n === ts.length ? 'all' : 'some'
  }
  const setColumn = (c: string, on: boolean) => setEdits((m) => {
    const out = { ...m }
    for (const t of tasks.filter(sweepable)) {
      const cur = (m[t]?.sweep ?? autoSet(t)).filter((x) => x !== c)
      out[t] = { ...(m[t] ?? { sweep: null, threads: '', budget: '', growth: '' }), sweep: on ? sortClusters([...cur, c]) : cur }
    }
    return out
  })
  const applyPreset = (kind: 'auto' | 'measured' | 'meets' | 'fits') => setEdits((m) => {
    const out = { ...m }
    for (const t of tasks.filter(sweepable)) {
      const rt = result?.range.tasks.find((x) => x.task === t)
      const base = m[t] ?? { sweep: null, threads: '', budget: '', growth: '' }
      const pick = kind === 'auto' ? null : kind === 'measured' ? (rt?.measured ?? [])
        : clusterNames.filter((c) => (kind === 'meets' ? rt?.cells[c]?.meets : rt?.cells[c]?.fits))
      out[t] = { ...base, sweep: pick }
    }
    return out
  })
  // DSU experiment re-ranks the cases: keep the selection on the new best
  useEffect(() => { if (result) setSel(result.cases[0] ? `c${result.cases[0].rank}` : '') }, [dsuExp]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (rb) setRbSel(rb.cases[0] ? `c${rb.cases[0].rank}` : 'ref') }, [dsuExp]) // eslint-disable-line react-hooks/exhaustive-deps
  const rbEval = useMemo(() => (pol: DsuPolicy | null) => {
    const r = rbRaw ? (pol ? applyDsuRebalance(rbRaw, pol) : rbRaw) : null
    const b = r?.best ?? null
    return { refMw: r?.reference.total_mw ?? 0, bestMw: b?.total_mw ?? null, deltaMw: b && r ? b.total_mw - r.reference.total_mw : null,
      refDsuMhz: r?.reference.mhz.dsu ?? null, bestDsuMhz: b?.mhz.dsu ?? null, bestKey: b ? b.moved.map((u) => `${u}→${b.assign[u]}`).join(' · ') || '현재 그대로' : '—' }
  }, [rbRaw])
  // setup rows: units of the last result (per task) or the profile's tasks before the first run
  const rbRows: SetupRow[] = useMemo(() => {
    if (rbRaw) {
      const unitOf = new Map(rbRaw.units.flatMap((u) => u.tasks.map((t) => [t, u] as const)))
      const all = (prof?.tasks ?? []).map((t) => t.task).filter((t, i, a) => a.indexOf(t) === i && t !== '(other)')
      return all.map((t) => { const u = unitOf.get(t)
        return { task: t, home: u?.home ?? prof?.tasks?.find((x) => x.task === t)?.cluster ?? '', budget: u?.budget_ms ?? null, util: u?.util_fmax, tms: u?.t_fmax_ms } })
    }
    return (prof?.tasks ?? []).filter((t, i, a) => a.findIndex((x) => x.task === t.task) === i && t.task !== '(other)').map((t) => ({ task: t.task, home: t.cluster, budget: null }))
  }, [rbRaw, prof])
  const rbSpace = useMemo(() => {
    const movable = rbRows.filter((r) => pool.includes(r.home) && (taskStates[r.task] ?? 'auto') === 'auto')
    const grouped = new Set(movable.filter((r) => groups[r.task]).map((r) => groups[r.task]))
    const units = movable.filter((r) => !groups[r.task]).length + grouped.size
    const splits = pool.length ** units
    const sig = (c: string) => { const m = rbRaw?.clusters.find((x) => x.name === c); return m ? `${m.core_type}|${m.cores}|${m.opps_mhz.join(',')}` : c }
    const counts = new Map<string, number>(); pool.forEach((c) => counts.set(sig(c), (counts.get(sig(c)) ?? 0) + 1))
    let reduced = splits
    counts.forEach((n) => { for (let k = 2; k <= n; k++) reduced = Math.floor(reduced / k) })
    return { units, splits, reduced }
  }, [rbRows, pool, taskStates, groups, rbRaw])
  // purpose-panel presets: state first, then one run with the new values (effect sees the updated closure)
  useEffect(() => { if (pendingRun) { setPendingRun(false); void run() } }, [pendingRun]) // eslint-disable-line react-hooks/exhaustive-deps
  const applyDsuToServer = (pol: DsuPolicy | null) => { setDsuReq(pol); setDsuExp(null); void run(request(edits, pol)) }
  const toggleKnob = (k: Knob) => setKnobs((ks) => (ks.includes(k) ? ks.filter((x) => x !== k) : [...ks, k]))

  // ---- results
  const ref = result?.reference
  const knobText = (c: SweepCase) => Object.entries(c.knobs).filter(([, o]) => o.kind !== 'measured').map(([t, o]) => knobLabel(t, o))
  const caseLabel = (c: SweepCase) => knobText(c).join(' · ') || 'EAS 기본 (knob 없음)'
  const sub = (c: SweepCase) => {
    const f = ref && c !== ref ? freqChanges(c, ref) : []
    const eq = c.equivalents?.length ? ` · 동등 ${c.equivalents.length}` : ''
    return `${c.feasible ? '만족' : '미충족'} · slack ${c.min_slack_ms === null ? '—' : fmt(c.min_slack_ms, 1)} ms${f.length ? ` · ${f.join(' ')}` : ''}${eq}`
  }
  const refName = result?.reference_kind === 'eas' ? 'EAS 기본' : '현재 (측정 배치)'
  const byId = (id: string): SweepCase | undefined => {
    if (!result) return undefined
    if (id === 'ref') return result.reference
    if (id === 'eas') return result.eas_default
    if (id.startsWith('c')) return result.cases.find((c) => `c${c.rank}` === id)
    if (id.startsWith('o')) return result.others[Number(id.slice(1))]
    return undefined
  }
  const rows: PowerRow[] = result && ref ? [
    { id: 'ref', label: refName, parts: caseParts(ref), sub: sub(ref) },
    ...(result.reference_kind === 'measured' && !result.cases.some((c) => Object.keys(c.knobs).length === 0)
      ? [{ id: 'eas', label: `EAS 기본 (knob 없음)${result.eas_default.feasible ? '' : ' · 미충족'}`, parts: caseParts(result.eas_default), sub: sub(result.eas_default) }] : []),
    ...result.cases.slice(0, showAllBetter ? result.cases.length : 5).map((c) => ({ id: `c${c.rank}`, label: `#${c.rank} ${caseLabel(c)}`, parts: caseParts(c), sub: sub(c) })),
  ] : []
  const picked = byId(sel)
  const best = result?.cases[0]
  const otherCols: Column<SweepCase>[] = [
    { key: 'mw', label: 'CPU mW', width: 90, align: 'right', sort: (c) => c.total_mw, render: (c) => <span className="mono">{fmt(c.total_mw, 1)}</span> },
    { key: 'd', label: `${refName} 대비`, width: 110, align: 'right', sort: (c) => c.delta_mw ?? 0, render: (c) => <span className={`mono ${(c.delta_mw ?? 0) < 0 ? 'pm-down' : 'pm-up'}`}>{signed(c.delta_mw ?? 0)}</span> },
    { key: 'ok', label: '판정', width: 80, sort: (c) => (c.feasible ? 1 : 0), render: (c) => <span className={`badge ${c.feasible ? 'v-ok' : 'v-fail'}`}>{c.feasible ? '만족' : '미충족'}</span> },
    { key: 'k', label: 'knob', width: 380, render: (c) => <span className="mono faint">{caseLabel(c)}</span> },
  ]
  const tile = (label: string, value: string, note: string, tone = '') =>
    <div key={label} className="panel tb-kpi"><div className="faint" style={{ fontSize: 12 }}>{label}</div><div className={`mono ${tone}`} style={{ fontSize: 20, fontWeight: 600 }}>{value}</div><div className="faint" style={{ fontSize: 11 }}>{note}</div></div>
  const sched = result?.scheduler

  return (
    <div className="page tb-page">
      <p className="cpu-help">측정한 CPU profile(task·thread별 cycle · stall · bus)을 Android <b>EAS + schedutil</b>로 다시 배치해 보고, 기기에서 실제로 바꿀 수 있는 knob(cpuset/affinity 고정·상한, uclamp)을 자동으로 sweep 합니다. 결과는 <b>{refName}</b> 대비 전력이 낮은 순서입니다. 시계열 없이 frame 단위 정상상태로 계산합니다.</p>
      <div className="toolbar" style={{ gap: 10, marginBottom: 8 }}>
        <div className="seg" role="group" aria-label="CPU what-if 방식">
          <button className={mode === 'rebalance' ? 'on' : ''} onClick={() => setMode('rebalance')} title="camera SW task를 MID cluster 사이에서 나누는 최적점 (cpuset)">MID 재분배</button>
          <button className={mode === 'sweep' ? 'on' : ''} onClick={() => setMode('sweep')} title="task별 cpuset / uclamp knob 조합을 자동 탐색해 현재보다 전력이 낮은 배치를 찾음">자동 탐색 (고급)</button>
        </div>
        <span className="faint" style={{ fontSize: 12 }}>{mode === 'rebalance' ? '한 MID cluster에 몰린 task를 같은 tier의 cluster로 나눴을 때 CPU + DSU 전력 최저점' : 'task별 knob 조합 자동 탐색 · 현재보다 전력이 낮은 배치'}</span>
      </div>
      <CpuPurpose rb={rb} cmp={cmpRb} runs={runs} growth={growth} bwScale={bwScale}
        onRebalance={() => { setMode('rebalance'); setPendingRun(true) }}
        onPreset={(p) => { setMode('rebalance'); if (p.growth !== undefined) setGrowth(p.growth); if (p.bwScale !== undefined) setBwScale(p.bwScale); setPendingRun(true) }} />
      {inputs.error && <div className="err">{inputs.error}</div>}
      {inputs.data && (!inputs.data.profiles.length || !inputs.data.topologies.length) && <div className="lib-note warn">
        sweep에 필요한 입력이 없습니다 — 측정 CPU profile <b>{inputs.data.profiles.length}건</b> · CPU topology(power_model_params) <b>{inputs.data.topologies.length}건</b>.
        {!inputs.data.profiles.length && <> task별 cycle · thread를 담은 CPU profile을 측정 evidence로 import하세요 (docs/guides/measurement/cpu-profile-import-ko.md, 예시: examples/measurement-import/cpu-profile-sample/).</>}
        {!inputs.data.topologies.length && <> cpu topology가 있는 power_model_params를 등록하세요.</>}
      </div>}
      <div className="tb-grid">
        <Card id="cpu-in" title="① 기준" note="측정 profile · 적용할 SoC · 비교 기준" help={CPU_HELP.input}>
          <div className="cpu-step" style={{ display: 'grid', gap: 8 }}>
            <label className="cpu-f"><span className="faint">측정 profile</span>
              <select value={profile} onChange={(e) => setProfile(e.target.value)}>{rankProfiles(inputs.data?.profiles ?? [], ctx).map((p) => <option key={p.id} value={p.id}>{p.origin === 'synthetic' ? '[합성] ' : p.origin === 'unknown' ? '[출처 미상] ' : ''}{p.variant_ref ?? p.id} · {p.measured_at?.slice(0, 10) ?? '날짜 없음'}{p.sw_baseline_ref ? ` · ${p.sw_baseline_ref}` : ''}{p.silicon_rev ? ` · ${p.silicon_rev}` : ''} · {p.id}{p.tasks?.length ? '' : ' (task 정보 없음)'}</option>)}</select></label>
            {prof?.origin && prof.origin !== 'physical_capture' && <div className="lib-note warn" style={{ fontSize: 11.5, margin: 0 }}>{prof.origin === 'synthetic' ? '합성 profile — 실기기 측정이 아니므로 결과는 모델 동작 확인용이며 실제 절감 근거가 아닙니다.' : '출처 미상 profile — 측정 방법·장비가 기록되지 않았습니다.'}</div>}
            <label className="cpu-f"><span className="faint">적용할 SoC CPU 구성</span>
              <select value={target} onChange={(e) => { targetPicked.current = true; setTarget(e.target.value) }}>{rankTopologies(inputs.data?.topologies ?? [], prof).map((t) => <option key={t.id} value={t.id}>{t.soc_ref} · v{t.version} · {sortClusters(t.clusters).join(' / ')}{prof?.tasks?.length && clusterCover(t, prof) < 1 ? ' (측정 cluster 불일치)' : ''}</option>)}</select></label>
            {mode === 'rebalance' && <label className="cpu-f" title="같은 측정 profile을 다른 과제의 CPU 구성에도 재분배해 나란히 비교 (MID 구조 변경 영향)"><span className="faint">과제 비교 (선택)</span>
              <select value={cmpTarget} aria-label="비교할 SoC" onChange={(e) => setCmpTarget(e.target.value)}><option value="">— 비교 안 함</option>
                {(inputs.data?.topologies ?? []).filter((t) => t.id !== target).map((t) => <option key={t.id} value={t.id}>{t.soc_ref} · v{t.version} · {sortClusters(t.clusters).join(' / ')}</option>)}</select></label>}
            <label className="cpu-f" title="다른 과제에서 측정한 profile이면 측정한 SoC의 CPU 구성을 고르세요 (core type으로 대응)"><span className="faint">profile을 측정한 SoC</span>
              <select value={base} onChange={(e) => setBase(e.target.value)}><option value="">적용할 SoC와 같음</option>{(inputs.data?.topologies ?? []).map((t) => <option key={t.id} value={t.id}>{t.soc_ref} · {t.id}</option>)}</select></label>
            <div className="cpu-f"><span className="faint">비교 기준 (★)</span>
              <div className="toolbar" style={{ gap: 12 }}>
                <label><input type="radio" checked={reference === 'measured'} onChange={() => setReference('measured')} /> 현재 = 측정 배치</label>
                <label><input type="radio" checked={reference === 'eas'} onChange={() => setReference('eas')} /> EAS 기본</label>
              </div></div>
          </div>
        </Card>
        <Card id="cpu-cond" title="② 조건 · scheduler" help={CPU_HELP.cond} note={sched ? `${sched.from_params ? 'topology 설정' : '기본값'}: margin ${sched.freq_margin} · ${sched.util_model} · PELT ${sched.pelt_halflife_ms} ms · boost ${sched.deadline_boost ? 'on' : 'off'}` : 'EAS + schedutil'}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 8 }}>
            <label className="cpu-f"><span className="faint">fps</span><input type="number" value={fps} min={1} onChange={(e) => setFps(Number(e.target.value))} /></label>
            <label className="cpu-f" title="차기 과제 SW instruction 증가 배율 (전체)"><span className="faint">SW 증가 배율</span><input type="number" step={0.05} value={growth} onChange={(e) => setGrowth(Number(e.target.value))} /></label>
            <label className="cpu-f" title="idle core가 power gating되는 비율"><span className="faint">idle power gating</span><input type="number" step={0.05} value={pgEff} onChange={(e) => setPgEff(Number(e.target.value))} /></label>
            <label className="cpu-f" title="L3/SLC 변경 등으로 DRAM까지 가는 CPU traffic 배율"><span className="faint">CPU BW 배율</span><input type="number" step={0.05} value={bwScale} onChange={(e) => setBwScale(Number(e.target.value))} /></label>
          </div>
          <details style={{ marginTop: 8 }}><summary className="faint" style={{ fontSize: 12 }}>scheduler 보정값 (비우면 topology 설정 사용)</summary>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 8, marginTop: 6 }}>
              <label className="cpu-f" title="schedutil: f = margin × util / capacity × fmax"><span className="faint">freq margin</span><input value={adv.freqMargin} placeholder={String(sched?.freq_margin ?? 1.25)} onChange={(e) => setAdv({ ...adv, freqMargin: e.target.value })} /></label>
              <label className="cpu-f" title="fits_capacity: util × margin ≤ capacity"><span className="faint">fits margin</span><input value={adv.fitsMargin} placeholder={String(sched?.fits_margin ?? 1.25)} onChange={(e) => setAdv({ ...adv, fitsMargin: e.target.value })} /></label>
              <label className="cpu-f" title="util_est = frame 1회 실행의 PELT peak, pelt_avg = 평균"><span className="faint">util model</span><select value={adv.utilModel} onChange={(e) => setAdv({ ...adv, utilModel: e.target.value as Adv['utilModel'] })}><option value="">{sched?.util_model ?? 'util_est'} (설정)</option><option value="util_est">util_est</option><option value="pelt_avg">pelt_avg</option></select></label>
              <label className="cpu-f" title="PELT half-life (pelt multiplier: 32 / 16 / 8 ms)"><span className="faint">PELT half-life ms</span><input value={adv.halflife} placeholder={String(sched?.pelt_halflife_ms ?? 32)} onChange={(e) => setAdv({ ...adv, halflife: e.target.value })} /></label>
              <label className="cpu-f" title="budget이 있는 task는 budget을 맞추는 OPP까지 올림 (ADPF hint / HAL uclamp.min)"><span className="faint">deadline boost</span><select value={adv.boost} onChange={(e) => setAdv({ ...adv, boost: e.target.value as Adv['boost'] })}><option value="">{sched?.deadline_boost === false ? 'off' : 'on'} (설정)</option><option value="on">on</option><option value="off">off</option></select></label>
              <label className="cpu-f" title="EAS 에너지 비교에 leakage 포함 (vendor scheduler)"><span className="faint">EM에 leakage</span><select value={adv.emStatic} onChange={(e) => setAdv({ ...adv, emStatic: e.target.value as Adv['emStatic'] })}><option value="">{sched?.energy_includes_static ? 'on' : 'off'} (설정)</option><option value="on">on</option><option value="off">off</option></select></label>
            </div></details>
        </Card>
        {mode === 'rebalance' && rbRaw?.dsu_params && <Card id="cpu-dsu" title="DSU 동기화 (가정)" defaultWide minHeight={120} help={CPU_HELP.dsu}
          note={`DSU 주파수 = busy cluster vote 최대 · 표를 바꾸면 반환된 분배를 즉시 재계산${dsuExp ? ' · 실험 적용 중' : ''}`}>
          <DsuPanel params={rbRaw.dsu_params} server={rbRaw.dsu_model} measured={rbRaw.dsu_measured} evalPolicy={rbEval} candidates={rbRaw.cases.length + rbRaw.curve.length}
            exp={dsuExp} setExp={setDsuExp} onApply={applyDsuToServer} applied={dsuReq} />
        </Card>}
        {mode === 'sweep' && rawResult?.dsu_params && <Card id="cpu-dsu" title="DSU 동기화 (가정)" defaultWide minHeight={120} help={CPU_HELP.dsu}
          note={`DSU 주파수 = busy cluster vote 최대 · 표를 바꾸면 반환된 후보를 즉시 재계산${dsuExp ? ' · 실험 적용 중' : ''}`}>
          <DsuPanel params={rawResult.dsu_params} server={rawResult.dsu_model} measured={rawResult.dsu_measured} check={rawResult.dsu_check}
            evalPolicy={sweepEval} candidates={rawResult.cases.length + rawResult.others.length}
            exp={dsuExp} setExp={setDsuExp} onApply={applyDsuToServer} applied={dsuReq} />
        </Card>}
        {mode === 'rebalance' && <RebalanceSetup clusters={poolNames} pool={pool} setPool={setPoolSel} rows={rbRows}
          states={taskStates} setState={(t, st) => setTaskStates((m) => ({ ...m, [t]: st }))}
          groups={groups} setGroup={(t, g) => setGroups((m) => ({ ...m, [t]: g }))}
          budgets={Object.fromEntries(Object.entries(edits).map(([t, e]) => [t, e.budget]))} setBudget={(t, v) => setEdit(t, { budget: v })}
          space={rbSpace} method={rbRaw?.method} busy={busy} onRun={() => void run()} top={rbTop} setTop={setRbTop} hasResult={!!rbRaw} knob={rbKnob} setKnob={setRbKnob} />}
        {mode === 'sweep' && <Card id="cpu-range" title="③ Sweep 범위" note="cluster별 · 칸 = fmax에서 task 시간 · ✓ budget 충족 · 체크 = sweep에 포함 · 파란 칸 = 측정 위치" defaultWide help={CPU_HELP.range}>
          <div className="toolbar" style={{ gap: 14, marginBottom: 6, fontSize: 12 }}>
            <span className="faint">knob</span>
            <label><input type="checkbox" checked={knobs.includes('pin')} onChange={() => toggleKnob('pin')} /> cluster 고정 (cpuset/affinity)</label>
            <label><input type="checkbox" checked={knobs.includes('upto')} onChange={() => toggleKnob('upto')} /> 상위 cluster 제외 (cpuset 상한)</label>
            <label><input type="checkbox" checked={knobs.includes('uclamp_max')} onChange={() => toggleKnob('uclamp_max')} /> uclamp.max</label>
            {knobs.includes('uclamp_max') && <input style={{ width: 90 }} value={uMax} placeholder="256, 512" onChange={(e) => setUMax(e.target.value)} />}
            <label><input type="checkbox" checked={knobs.includes('uclamp_min')} onChange={() => toggleKnob('uclamp_min')} /> uclamp.min</label>
            {knobs.includes('uclamp_min') && <input style={{ width: 90 }} value={uMin} placeholder="128, 256" onChange={(e) => setUMin(e.target.value)} />}
          </div>
          {tasks.length > 0 && <div className="toolbar" style={{ gap: 6, marginBottom: 6, fontSize: 12 }}>
            <span className="faint">범위 preset</span>
            <button className="btn tb-mini" onClick={() => applyPreset('auto')} title="task별 자동 범위 (fmax에서 budget 충족 cluster)">자동</button>
            <button className="btn tb-mini" onClick={() => applyPreset('measured')} title="측정에서 돈 cluster만">측정 위치만</button>
            <button className="btn tb-mini" onClick={() => applyPreset('meets')} disabled={!result} title="✓ budget 충족 cluster 전부">✓ 전부</button>
            <button className="btn tb-mini" onClick={() => applyPreset('fits')} disabled={!result} title="capacity 초과(⚠) cluster 제외 전부">⚠ 제외 전부</button>
            <span className="faint">· 열 머리 체크 = 그 cluster를 모든 task에 포함/제외</span>
          </div>}
          {tasks.length ? <div className="table-x"><table className="grid cpu-matrix cpu-range">
            <thead>
              <tr><th>task</th>{clusterNames.map((c) => { const rc = rangeCluster(c); return (
                <th key={c} style={{ borderTop: `3px solid ${colorOf(c)}` }}>
                  <input type="checkbox" aria-label={`${c} 전체 task 포함`} title={`모든 task에 ${c} 포함 / 제외 ((other) 제외)`} checked={columnState(c) === 'all'}
                    ref={(el) => { if (el) el.indeterminate = columnState(c) === 'some' }} onChange={() => setColumn(c, columnState(c) !== 'all')} style={{ marginRight: 4 }} />
                  <span className="sw pm-sw" style={{ background: colorOf(c) }} />{c}
                  {rc && <div className="faint cpu-range-meta">{rc.cores} core · cap {fmt(rc.capacity, 0)}<br />{fmt(rc.opp_min_mhz, 0)}–{fmt(rc.opp_max_mhz, 0)} MHz · {rc.opp_count} OPP</div>}</th>) })}
                <th title="thread 수 (비우면 측정값 · 없으면 1)">thr</th><th title="frame당 허용 시간 (Timing Budget의 SW budget)">budget ms</th><th title="이 task만의 SW 증가 배율">증가</th><th>정책 · 후보</th></tr>
            </thead>
            <tbody>{tasks.map((task) => {
              const rt = result?.range.tasks.find((t) => t.task === task)
              const e = edit(task)
              const inSweep = (c: string) => (e.sweep ?? clusterNames.filter((x) => rt?.cells[x]?.in_sweep)).includes(c)
              const fixed = rt && rt.options.length <= 1 && e.sweep === null
              return (
                <tr key={task}>
                  <td className="mono" title={task === '(other)' ? '어느 task에도 매핑되지 않은 cycle (커널 · 다른 프로세스 · 이름 없는 thread). 기본 정책을 유지하며 sweep에서 제외' : undefined}>{task} <span className="faint">({rt?.measured.join('/') ?? prof?.tasks?.find((t) => t.task === task)?.cluster})</span>
                    {task === '(other)' && <div className="faint" style={{ fontSize: 10.5, fontFamily: 'var(--font)' }}>미매핑 cycle · 기본 정책 유지</div>}</td>
                  {clusterNames.map((c) => {
                    const cell = rt?.cells[c]
                    return <td key={c} className={rt?.measured.includes(c) ? 'measured' : ''}>
                      <label className="cpu-cell" title={cell ? `fmax에서 ${fmt(cell.t_fmax_ms, 2)} ms · util ${fmt(cell.util_fmax, 0)}/${fmt(rangeCluster(c)?.capacity ?? 0, 0)}${cell.fits ? '' : ' · capacity 초과(EAS가 안 보냄)'}` : ''}>
                        <input type="checkbox" disabled={task === '(other)'} checked={inSweep(c)} onChange={() => toggleCell(task, c)} />
                        {cell && <span className={`mono ${cell.meets ? '' : 'pm-up'}`}>{fmt(cell.t_fmax_ms, 1)}{cell.meets ? ' ✓' : ' ✗'}{cell.fits ? '' : ' ⚠'}</span>}
                      </label></td>
                  })}
                  <td><input style={{ width: 36 }} value={e.threads} placeholder={rt ? String(rt.threads.length) : '1'} title={rt?.thread_source === 'measured' ? `측정 thread (TID): ${rt.threads.map((t) => t.name).join(', ')}` : ''} onChange={(ev) => setEdit(task, { threads: ev.target.value })} /></td>
                  <td><input style={{ width: 48 }} value={e.budget} placeholder="—" onChange={(ev) => setEdit(task, { budget: ev.target.value })} /></td>
                  <td><input style={{ width: 40 }} value={e.growth} placeholder={String(growth)} onChange={(ev) => setEdit(task, { growth: ev.target.value })} /></td>
                  <td className="faint" style={{ textAlign: 'left', fontSize: 11 }}>{Object.entries(rt?.policy ?? {}).map(([k, v]) => `${k}=${String(v)}`).join(' ')}{fixed ? ' 고정 (sweep 제외)' : rt ? ` 후보 ${rt.options.length}` : ''}</td>
                </tr>)
            })}</tbody></table></div> : (inputs.data?.profiles.length ?? 0) > 0 && <NoTasks profiles={rankProfiles(inputs.data?.profiles ?? [], ctx).filter((p) => p.tasks?.length)} onPick={setProfile} />}
          <div className="toolbar" style={{ marginTop: 8 }}>
            <span className="faint" style={{ fontSize: 12 }}>{result ? `조합 ${result.range.space.toLocaleString()}개 · 계산 ${result.range.evaluated.toLocaleString()} (${result.range.method === 'beam' ? 'beam 탐색' : '전수'}) · 서로 다른 배치 ${result.range.unique}` : '조합 수는 계산 후 표시'}</span>
            {result?.range.method === 'beam' && <span className="badge v-warn" title={`조합 ${result.range.space.toLocaleString()}개 중 ${result.range.evaluated.toLocaleString()}개만 계산 — 결과는 부분 탐색 기준 순위`}>부분 탐색</span>}
            <span className="grow" />
            <label className="faint" style={{ fontSize: 12, display: 'flex', gap: 4, alignItems: 'center' }}>결과 상위
              <select value={top} onChange={(e) => setTop(Number(e.target.value))} aria-label="결과 상위 N">{[10, 20, 60, 200].map((n) => <option key={n} value={n}>{n}</option>)}</select>개</label>
            <button className="btn primary" disabled={busy || !profile || !target} onClick={() => void run()}>{busy ? '계산 중…' : result ? '다시 계산' : 'Sweep 계산'}</button>
          </div>
        </Card>}
      </div>
      {error && <div className="err">{error}</div>}
      {mode === 'rebalance' && rb && <div className="tb-grid">
        {cmpTarget && <CrossSocCompare a={rb} b={cmpRb ? applyDsuRebalance(cmpRb, dsuExp) : null} aName={topo?.soc_ref ?? target} bName={inputs.data?.topologies.find((t) => t.id === cmpTarget)?.soc_ref ?? cmpTarget} error={cmpErr} busy={busy} />}
        <RebalanceResults r={rb} sel={rbSel} setSel={setRbSel} knob={rbKnob}
          onPickStrategy={(assign) => setTaskStates((m) => ({ ...m, ...Object.fromEntries(Object.entries(assign).flatMap(([u, c]) => u.split('+').map((t) => [t, `pin:${c}` as TaskState]))) }))}
          sensitivity={rbRaw && <AssumptionSensitivity base={rb} dsu={dsuExp}
            runVariant={(patch) => rebalanceApi.run({ ...rbRequest(request(edits, dsuReq)), ...patch }).then((r) => (dsuExp ? applyDsuRebalance(r, dsuExp) : r))} />} /></div>}
      {mode === 'sweep' && result && ref && <>
        {result.warnings.length > 0 && <details className="panel" style={{ padding: '8px 12px', fontSize: 12 }}><summary>참고 {result.warnings.length}</summary>{result.warnings.map((w) => <div key={w} className="faint">{w}</div>)}</details>}
        <section className="tb-kpis" aria-label="요약">
          {tile('측정 (실측 DVFS)', result.measured_mw === null ? '—' : `${fmt(result.measured_mw, 1)} mW`, '측정 residency · gating 그대로')}
          {tile('현재 배치 · 모델', `${fmt(result.measured_placement.total_mw, 1)} mW`, `${result.measured_placement.feasible ? '조건 만족' : '조건 미충족'} · schedutil 주파수`)}
          {tile('EAS 기본', `${fmt(result.eas_default.total_mw, 1)} mW`, `${refName} 대비 ${signed(result.eas_default.total_mw - ref.total_mw)} mW${result.eas_default.feasible ? '' : ' · 미충족'}`)}
          {tile('최저 전력 후보', best ? `${fmt(best.total_mw, 1)} mW` : '없음', best ? `${refName} 대비 ${signed(best.delta_mw ?? 0)} mW · knob ${Object.keys(best.knobs).length}개` : `${refName}보다 낮은 조건 만족 후보 없음`, best && (best.delta_mw ?? 0) < 0 ? 'pm-down' : '')}
        </section>
        <div className="tb-grid">
          <Card id="cpu-cal" title="모델 확인" help={CPU_HELP.cal} note="측정 residency vs EAS 재현 (현재 배치) — 차이가 크면 scheduler 보정값부터 조정">
            <table className="grid pm-table"><thead><tr><th>cluster</th><th style={{ textAlign: 'right' }}>측정 평균 MHz</th><th style={{ textAlign: 'right' }}>모델 MHz</th><th style={{ textAlign: 'right' }}>측정 active</th><th style={{ textAlign: 'right' }}>모델 util</th>
              <th title="측정 주파수 분포 (회색 전체 · 청록 running) · 진한 선 = 측정 평균 · 빨간 점선 = 모델 MHz">측정 분포 vs 모델</th></tr></thead>
              <tbody>{clusterNames.map((c) => {
                const k = result.calibration[c], m = result.measured_placement.clusters[c]
                if (!k && !m) return null
                return <tr key={c}><td><span className="sw pm-sw" style={{ background: colorOf(c) }} />{c}</td>
                  <td className="mono" style={{ textAlign: 'right' }}>{k?.measured_mean_mhz === undefined ? '—' : fmt(k.measured_mean_mhz, 0)}</td>
                  <td className="mono" style={{ textAlign: 'right' }}>{m ? fmt(m.mhz, 0) : '—'}{m && m.boosted_by.length ? <span className="faint"> (boost {m.boosted_by.join(',')})</span> : null}</td>
                  <td className="mono" style={{ textAlign: 'right' }}>{k?.measured_active === undefined ? '—' : `${fmt(k.measured_active * 100, 1)}%`}</td>
                  <td className="mono" style={{ textAlign: 'right' }}>{m ? `${fmt(m.util * 100, 1)}%` : '—'}</td>
                  <td><ModelCheckDist wall={k?.measured_residency} active={k?.measured_residency_active} modelMhz={m?.mhz}
                    fmax={result.range.clusters.find((x) => x.name === c)?.opp_max_mhz} /></td></tr>
              })}</tbody></table>
          </Card>
          <Card id="cpu-stack" title={`${refName} 대비 전력이 낮은 후보`} help={CPU_HELP.better}
            note={`${result.better_count}개 · 낮은 순 · ${showAllBetter ? '전체' : `상위 ${Math.min(5, result.cases.length)}개`} 표시 · 행 클릭 = 아래 세부 · 점선 = ★ ${refName}`} defaultWide minHeight={200}
            actions={result.cases.length > 5 ? <button className="btn tb-mini" onClick={() => setShowAllBetter((v) => !v)}>{showAllBetter ? '상위 5개만' : `전체 ${result.cases.length}개 펼치기`}</button> : undefined}>
            {result.cases.length ? <>
              <PowerStack rows={rows} selected={sel} onPick={setSel} />
              {!showAllBetter && result.cases.length > 5 && <button className="btn" style={{ marginTop: 6 }} onClick={() => setShowAllBetter(true)}>▾ 나머지 {result.cases.length - 5}개 더 보기</button>}
            </> : <div className="empty">{refName}보다 전력이 낮으면서 조건을 만족하는 조합이 없습니다. sweep 범위나 knob을 넓혀 보세요.</div>}
          </Card>
          {picked && <CaseDetail c={picked} reference={ref} refName={refName} title={rows.find((r) => r.id === sel)?.label ?? ''} clusters={clusterNames} colorOf={colorOf} budgets={Object.fromEntries(Object.entries(edits).map(([t, e]) => [t, num(e.budget)]))} />}
          <Card id="cpu-others" title="나머지 조합" note="전력 증가 또는 조건 미충족 · 정렬 가능" defaultWide minHeight={120} help={CPU_HELP.others}>
            <details><summary className="faint" style={{ fontSize: 12 }}>{result.other_count}개 중 {result.others.length}개 펼치기</summary>
              <div className="table-x"><DataTable id="cpu.others" columns={otherCols} rows={result.others} rowKey={(c) => caseLabel(c) + c.total_mw}
                onRowClick={(c) => setSel(`o${result.others.indexOf(c)}`)} rowClass={(c) => (sel === `o${result.others.indexOf(c)}` ? 'selected' : '')} /></div></details>
          </Card>
        </div>
      </>}
    </div>
  )
}

function CaseDetail({ c, reference, refName, title, clusters, colorOf, budgets }: {
  c: SweepCase; reference: SweepCase; refName: string; title: string; clusters: string[]; colorOf: (c: string) => string
  budgets: Record<string, number | undefined>
}) {
  const knobs = Object.entries(c.knobs).filter(([, o]) => o.kind !== 'measured')
  const moved = movedLabel(c, reference)
  const tasks = Object.keys({ ...reference.task_ms, ...c.task_ms })
  const at = (x: SweepCase, t: string) => (x.placement[t] ?? []).map((n) => `${n}@${fmt(x.clusters[n]?.mhz, 0)}`).join(' ')
  return (
    <Card id="cpu-detail" title={`★ ${refName} vs ${title}`} note="무엇을 바꾸나 · cluster/CPU 점유 · task 시간" defaultWide help={CPU_HELP.detail}>
      <div className="cpu-detail">
        <div>
          <h3 className="cpu-h">적용 방법</h3>
          {knobs.length ? <ul className="cpu-knobs">{knobs.map(([t, o]) => <li key={t}><span className="mono">{knobLabel(t, o)}</span> <span className="faint">— {knobHow(o)}</span></li>)}</ul>
            : <div className="faint" style={{ fontSize: 12 }}>knob 없음 (EAS가 그대로 배치)</div>}
          {moved.length > 0 && <div className="faint" style={{ fontSize: 12, marginTop: 4 }}>배치 변화: <span className="mono">{moved.join(' · ')}</span></div>}
          {c.equivalents && c.equivalents.length > 0 && <details style={{ fontSize: 12, marginTop: 4 }}><summary className="faint">같은 OPP · 같은 전력의 다른 방법 {c.equivalents.length}개</summary>
            <ul className="cpu-knobs">{c.equivalents.map((e, i) => <li key={i} className="mono">{Object.entries(e.knobs).map(([t, o]) => knobLabel(t, o)).join(' · ') || 'EAS 기본'} <span className="faint">({fmt(e.total_mw, 1)} mW)</span></li>)}</ul></details>}
          {Object.keys(c.flags).length > 0 && <div style={{ fontSize: 12, marginTop: 4 }}>{Object.entries(c.flags).map(([k, v]) => <span key={k} className={`badge ${k === 'shared_cpu' ? '' : 'v-fail'}`} style={{ marginRight: 4 }} title={Array.isArray(v) ? v.join(', ') : ''}>{({ overutilized: 'capacity 초과', budget_miss: 'budget 미충족', over_period: 'frame 초과', shared_cpu: 'CPU 공유', overloaded_cpu: 'CPU 과부하' } as Record<string, string>)[k] ?? k}{Array.isArray(v) ? `: ${v.join(', ')}` : ''}</span>)}</div>}
          <h3 className="cpu-h" style={{ marginTop: 10 }}>전력 구성</h3>
          <PowerDeltaTable rows={[{ id: 'ref', label: refName, parts: caseParts(reference) }, { id: 'c', label: title.split(' ')[0], parts: caseParts(c) }]} />
        </div>
        <div>
          <h3 className="cpu-h">cluster · CPU 점유 (후보)</h3>
          {clusters.map((n) => {
            const cl = c.clusters[n]
            if (!cl) return null
            const r = reference.clusters[n]
            return (
              <div key={n} className="cpu-cl" style={{ borderLeft: `4px solid ${colorOf(n)}` }}>
                <div className="cpu-cl-head"><b>{n}</b> <span className="mono">{fmt(cl.mhz, 0)} MHz</span>
                  {r && r.mhz !== cl.mhz && <span className="faint mono"> (★ {fmt(r.mhz, 0)})</span>}
                  {cl.boosted_by.length > 0 && <span className="faint"> · schedutil {fmt(cl.sched_mhz, 0)} → boost {cl.boosted_by.join(',')}</span>}
                  <span className="grow" /><span className="mono">{fmt(cl.total_mw, 1)} mW</span>
                  {r && <span className={`mono ${cl.total_mw - r.total_mw < 0 ? 'pm-down' : 'pm-up'}`}> {signed(cl.total_mw - r.total_mw)}</span>}</div>
                {cl.cpus.map((cpu) => (
                  <div key={String(cpu.cpu)} className="cpu-bar-row" title={`${cpu.busy_ms} ms busy / frame`}>
                    <span className="mono faint">cpu{cpu.cpu}</span>
                    <span className="cpu-bar"><span style={{ width: `${Math.min(100, (100 * cpu.util) / Math.max(1, cl.capacity))}%`, background: colorOf(n) }} /></span>
                    <span className="mono" style={{ fontSize: 11 }} title={cpu.threads.some((t) => t.includes('#')) ? '#숫자 = 측정 trace의 thread id (TID)' : undefined}>{cpu.threads.length ? cpu.threads.map(threadLabel).join(', ') : <span className="faint">idle</span>}</span>
                  </div>))}
              </div>)
          })}
        </div>
      </div>
      <table className="grid pm-table" style={{ marginTop: 8 }}>
        <thead><tr><th>task</th><th>★ {refName}</th><th>후보</th><th style={{ textAlign: 'right' }}>시간 ms (★→후보)</th><th style={{ textAlign: 'right' }}>budget</th><th style={{ textAlign: 'right' }}>slack</th></tr></thead>
        <tbody>{tasks.map((t) => {
          const changed = (reference.placement[t] ?? []).join() !== (c.placement[t] ?? []).join()
          const slack = c.slack_ms[t]
          return <tr key={t} className={changed ? 'selected' : ''}><td className="mono">{t}</td><td className="mono">{at(reference, t)}</td><td className="mono">{at(c, t)}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{fmt(reference.task_ms[t], 2)} → {fmt(c.task_ms[t], 2)}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{budgets[t] ?? '—'}</td>
            <td className={`mono ${slack === undefined ? '' : slack < 0.5 ? 'pm-up' : 'pm-down'}`} style={{ textAlign: 'right' }}>{slack === undefined ? '—' : fmt(slack, 2)}</td></tr>
        })}</tbody></table>
    </Card>
  )
}

type Profile = CpuInputs['profiles'][number]
/** Profiles with task cycles first; then the current variant, scenario and project. */
function rankProfiles(list: Profile[], ctx: Ctx): Profile[] {
  const score = (p: Profile) => (p.tasks?.length ? 8 : 0) + (p.variant_ref === ctx.variant ? 4 : 0) + (p.scenario_ref === ctx.scenario ? 2 : 0) + (p.project_ref === ctx.project ? 1 : 0)
  return [...list].sort((a, b) => score(b) - score(a))
}

/** U10: the selected profile cannot be swept — say why and offer the ones that can. */
function NoTasks({ profiles, onPick }: { profiles: Profile[]; onPick: (id: string) => void }) {
  return (
    <div className="empty" style={{ textAlign: 'left' }}>
      선택한 측정 profile에 task별 cycle 정보가 없어 sweep할 수 없습니다 (thread · cycle을 포함한 CPU profile import 필요 — docs/guides/measurement/cpu-profile-import-ko.md).
      {profiles.length > 0 ? <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <span className="faint">task 정보가 있는 profile:</span>
        {profiles.slice(0, 6).map((p) => <button key={p.id} className="btn tb-mini" onClick={() => onPick(p.id)}>{p.variant_ref ?? p.id}</button>)}
      </div> : <div className="faint" style={{ marginTop: 6 }}>task 정보가 있는 profile이 아직 없습니다.</div>}
    </div>
  )
}
