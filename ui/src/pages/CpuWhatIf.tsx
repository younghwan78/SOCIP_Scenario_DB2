import { useEffect, useMemo, useRef, useState } from 'react'
import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { fmt } from '../lib/timingBudget'
import {
  caseParts, cpuApi, freqChanges, knobHow, knobLabel, movedLabel, parseLevels,
  type CpuSweep, type CpuSweepRequest, type Knob, type SweepCase, type SweepRangeCluster,
} from '../lib/cpu'
import { Card } from '../components/TimingCharts'
import { DataTable, type Column } from '../components/DataTable'
import { PowerDeltaTable, PowerStack, type PowerRow } from '../components/PowerModelCharts'
import { partColor, sortClusters } from '../lib/powerModel'

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
  void ctx
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
  const [result, setResult] = useState<CpuSweep | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const requestId = useRef(0)
  const inputSelection = useRef('')
  const [sel, setSel] = useState<string>('')

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
    if (!profile && inputs.data.profiles[0]) setProfile(inputs.data.profiles[0].id)
    if (!target && inputs.data.topologies[0]) setTarget(inputs.data.topologies[0].id)
  }, [inputs.data]) // eslint-disable-line react-hooks/exhaustive-deps

  const request = (taskEdits = edits): CpuSweepRequest => {
    const pick = (k: 'budget' | 'growth' | 'threads') => Object.fromEntries(Object.entries(taskEdits)
      .map(([t, e]) => [t, num(e[k])] as const).filter(([, v]) => v !== undefined)) as Record<string, number>
    return {
      cpu_profile_ref: profile, power_params_ref: target, base_power_params_ref: base || undefined, fps,
      default_growth: growth, growth: pick('growth'), budgets_ms: pick('budget'), threads: pick('threads'),
      sweep_clusters: Object.fromEntries(Object.entries(taskEdits).filter(([, e]) => e.sweep !== null).map(([t, e]) => [t, e.sweep as string[]])),
      knobs, uclamp_max_levels: parseLevels(uMax), uclamp_min_levels: parseLevels(uMin), reference,
      power_gating_eff: pgEff, cpu_bw_scale: bwScale,
      freq_margin: num(adv.freqMargin), fits_margin: num(adv.fitsMargin), util_model: adv.utilModel || undefined,
      pelt_halflife_ms: num(adv.halflife), deadline_boost: tri(adv.boost), energy_includes_static: tri(adv.emStatic),
    }
  }
  const run = async (payload = request()) => {
    if (!profile || !target) return
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
    if (changed) setEdits({})
    setResult(null)
    if (profile && target) void run(request(changed ? {} : edits))
    return () => { ++requestId.current }
  }, [profile, target, base, reference]) // eslint-disable-line react-hooks/exhaustive-deps

  const toggleCell = (task: string, cl: string) => {
    const auto = result?.range.tasks.find((t) => t.task === task)
    const cur = edit(task).sweep ?? clusterNames.filter((c) => auto?.cells[c]?.in_sweep)
    setEdit(task, { sweep: cur.includes(cl) ? cur.filter((c) => c !== cl) : [...cur, cl] })
  }
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
    ...result.cases.slice(0, 12).map((c) => ({ id: `c${c.rank}`, label: `#${c.rank} ${caseLabel(c)}`, parts: caseParts(c), sub: sub(c) })),
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
      {inputs.error && <div className="err">{inputs.error}</div>}
      {inputs.data && (!inputs.data.profiles.length || !inputs.data.topologies.length) && <div className="empty">CPU profile이 있는 측정 evidence와 cpu topology가 있는 power_model_params가 필요합니다 (docs/guides/measurement/cpu-profile-import-ko.md).</div>}
      <div className="tb-grid">
        <Card id="cpu-in" title="① 기준" note="측정 profile · 적용할 SoC · 비교 기준">
          <div className="cpu-step" style={{ display: 'grid', gap: 8 }}>
            <label className="cpu-f"><span className="faint">측정 profile</span>
              <select value={profile} onChange={(e) => setProfile(e.target.value)}>{(inputs.data?.profiles ?? []).map((p) => <option key={p.id} value={p.id}>{p.variant_ref ?? p.id} · {p.id}</option>)}</select></label>
            <label className="cpu-f"><span className="faint">적용할 SoC CPU 구성</span>
              <select value={target} onChange={(e) => setTarget(e.target.value)}>{(inputs.data?.topologies ?? []).map((t) => <option key={t.id} value={t.id}>{t.soc_ref} · {sortClusters(t.clusters).join(' / ')}</option>)}</select></label>
            <label className="cpu-f" title="다른 과제에서 측정한 profile이면 측정한 SoC의 CPU 구성을 고르세요 (core type으로 대응)"><span className="faint">profile을 측정한 SoC</span>
              <select value={base} onChange={(e) => setBase(e.target.value)}><option value="">적용할 SoC와 같음</option>{(inputs.data?.topologies ?? []).map((t) => <option key={t.id} value={t.id}>{t.soc_ref} · {t.id}</option>)}</select></label>
            <div className="cpu-f"><span className="faint">비교 기준 (★)</span>
              <div className="toolbar" style={{ gap: 12 }}>
                <label><input type="radio" checked={reference === 'measured'} onChange={() => setReference('measured')} /> 현재 = 측정 배치</label>
                <label><input type="radio" checked={reference === 'eas'} onChange={() => setReference('eas')} /> EAS 기본</label>
              </div></div>
          </div>
        </Card>
        <Card id="cpu-cond" title="② 조건 · scheduler" note={sched ? `${sched.from_params ? 'topology 설정' : '기본값'}: margin ${sched.freq_margin} · ${sched.util_model} · PELT ${sched.pelt_halflife_ms} ms · boost ${sched.deadline_boost ? 'on' : 'off'}` : 'EAS + schedutil'}>
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
        <Card id="cpu-range" title="③ Sweep 범위" note="cluster별 · 칸 = fmax에서 task 시간 · ✓ budget 충족 · 체크 = sweep에 포함 · 파란 칸 = 측정 위치" defaultWide>
          <div className="toolbar" style={{ gap: 14, marginBottom: 6, fontSize: 12 }}>
            <span className="faint">knob</span>
            <label><input type="checkbox" checked={knobs.includes('pin')} onChange={() => toggleKnob('pin')} /> cluster 고정 (cpuset/affinity)</label>
            <label><input type="checkbox" checked={knobs.includes('upto')} onChange={() => toggleKnob('upto')} /> 상위 cluster 제외 (cpuset 상한)</label>
            <label><input type="checkbox" checked={knobs.includes('uclamp_max')} onChange={() => toggleKnob('uclamp_max')} /> uclamp.max</label>
            {knobs.includes('uclamp_max') && <input style={{ width: 90 }} value={uMax} placeholder="256, 512" onChange={(e) => setUMax(e.target.value)} />}
            <label><input type="checkbox" checked={knobs.includes('uclamp_min')} onChange={() => toggleKnob('uclamp_min')} /> uclamp.min</label>
            {knobs.includes('uclamp_min') && <input style={{ width: 90 }} value={uMin} placeholder="128, 256" onChange={(e) => setUMin(e.target.value)} />}
          </div>
          {tasks.length ? <div className="table-x"><table className="grid cpu-matrix cpu-range">
            <thead>
              <tr><th>task</th>{clusterNames.map((c) => { const rc = rangeCluster(c); return (
                <th key={c} style={{ borderTop: `3px solid ${colorOf(c)}` }}><span className="sw pm-sw" style={{ background: colorOf(c) }} />{c}
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
                  <td className="mono">{task} <span className="faint">({rt?.measured.join('/') ?? prof?.tasks?.find((t) => t.task === task)?.cluster})</span></td>
                  {clusterNames.map((c) => {
                    const cell = rt?.cells[c]
                    return <td key={c} className={rt?.measured.includes(c) ? 'measured' : ''}>
                      <label className="cpu-cell" title={cell ? `fmax에서 ${fmt(cell.t_fmax_ms, 2)} ms · util ${fmt(cell.util_fmax, 0)}/${fmt(rangeCluster(c)?.capacity ?? 0, 0)}${cell.fits ? '' : ' · capacity 초과(EAS가 안 보냄)'}` : ''}>
                        <input type="checkbox" disabled={task === '(other)'} checked={inSweep(c)} onChange={() => toggleCell(task, c)} />
                        {cell && <span className={`mono ${cell.meets ? '' : 'pm-up'}`}>{fmt(cell.t_fmax_ms, 1)}{cell.meets ? ' ✓' : ' ✗'}{cell.fits ? '' : ' ⚠'}</span>}
                      </label></td>
                  })}
                  <td><input style={{ width: 36 }} value={e.threads} placeholder={rt ? String(rt.threads.length) : '1'} title={rt?.thread_source === 'measured' ? `측정 thread: ${rt.threads.map((t) => t.name).join(', ')}` : ''} onChange={(ev) => setEdit(task, { threads: ev.target.value })} /></td>
                  <td><input style={{ width: 48 }} value={e.budget} placeholder="—" onChange={(ev) => setEdit(task, { budget: ev.target.value })} /></td>
                  <td><input style={{ width: 40 }} value={e.growth} placeholder={String(growth)} onChange={(ev) => setEdit(task, { growth: ev.target.value })} /></td>
                  <td className="faint" style={{ textAlign: 'left', fontSize: 11 }}>{Object.entries(rt?.policy ?? {}).map(([k, v]) => `${k}=${String(v)}`).join(' ')}{fixed ? ' 고정 (sweep 제외)' : rt ? ` 후보 ${rt.options.length}` : ''}</td>
                </tr>)
            })}</tbody></table></div> : <div className="empty">profile에 task별 cycle 정보가 없습니다.</div>}
          <div className="toolbar" style={{ marginTop: 8 }}>
            <span className="faint" style={{ fontSize: 12 }}>{result ? `조합 ${result.range.space.toLocaleString()}개 · 계산 ${result.range.evaluated.toLocaleString()} (${result.range.method === 'beam' ? 'beam 탐색' : '전수'}) · 서로 다른 배치 ${result.range.unique}` : '조합 수는 계산 후 표시'}</span><span className="grow" />
            <button className="btn primary" disabled={busy || !profile || !target} onClick={() => void run()}>{busy ? '계산 중…' : result ? '다시 계산' : 'Sweep 계산'}</button>
          </div>
        </Card>
      </div>
      {error && <div className="err">{error}</div>}
      {result && ref && <>
        {result.warnings.length > 0 && <details className="panel" style={{ padding: '8px 12px', fontSize: 12 }}><summary>참고 {result.warnings.length}</summary>{result.warnings.map((w) => <div key={w} className="faint">{w}</div>)}</details>}
        <section className="tb-kpis" aria-label="요약">
          {tile('측정 (실측 DVFS)', result.measured_mw === null ? '—' : `${fmt(result.measured_mw, 1)} mW`, '측정 residency · gating 그대로')}
          {tile('현재 배치 · 모델', `${fmt(result.measured_placement.total_mw, 1)} mW`, `${result.measured_placement.feasible ? '조건 만족' : '조건 미충족'} · schedutil 주파수`)}
          {tile('EAS 기본', `${fmt(result.eas_default.total_mw, 1)} mW`, `${refName} 대비 ${signed(result.eas_default.total_mw - ref.total_mw)} mW${result.eas_default.feasible ? '' : ' · 미충족'}`)}
          {tile('최저 전력 후보', best ? `${fmt(best.total_mw, 1)} mW` : '없음', best ? `${refName} 대비 ${signed(best.delta_mw ?? 0)} mW · knob ${Object.keys(best.knobs).length}개` : `${refName}보다 낮은 조건 만족 후보 없음`, best && (best.delta_mw ?? 0) < 0 ? 'pm-down' : '')}
        </section>
        <div className="tb-grid">
          <Card id="cpu-cal" title="모델 확인" note="측정 residency vs EAS 재현 (현재 배치) — 차이가 크면 scheduler 보정값부터 조정">
            <table className="grid pm-table"><thead><tr><th>cluster</th><th style={{ textAlign: 'right' }}>측정 평균 MHz</th><th style={{ textAlign: 'right' }}>모델 MHz</th><th style={{ textAlign: 'right' }}>측정 active</th><th style={{ textAlign: 'right' }}>모델 util</th></tr></thead>
              <tbody>{clusterNames.map((c) => {
                const k = result.calibration[c], m = result.measured_placement.clusters[c]
                if (!k && !m) return null
                return <tr key={c}><td><span className="sw pm-sw" style={{ background: colorOf(c) }} />{c}</td>
                  <td className="mono" style={{ textAlign: 'right' }}>{k?.measured_mean_mhz === undefined ? '—' : fmt(k.measured_mean_mhz, 0)}</td>
                  <td className="mono" style={{ textAlign: 'right' }}>{m ? fmt(m.mhz, 0) : '—'}{m && m.boosted_by.length ? <span className="faint"> (boost {m.boosted_by.join(',')})</span> : null}</td>
                  <td className="mono" style={{ textAlign: 'right' }}>{k?.measured_active === undefined ? '—' : `${fmt(k.measured_active * 100, 1)}%`}</td>
                  <td className="mono" style={{ textAlign: 'right' }}>{m ? `${fmt(m.util * 100, 1)}%` : '—'}</td></tr>
              })}</tbody></table>
          </Card>
          <Card id="cpu-stack" title={`${refName} 대비 전력이 낮은 후보`} note={`${result.better_count}개 · 낮은 순 · 행 클릭 = 아래 세부 · 점선 = ★ ${refName}`} defaultWide minHeight={200}>
            {result.cases.length ? <PowerStack rows={rows} selected={sel} onPick={setSel} /> : <div className="empty">{refName}보다 전력이 낮으면서 조건을 만족하는 조합이 없습니다. sweep 범위나 knob을 넓혀 보세요.</div>}
          </Card>
          {picked && <CaseDetail c={picked} reference={ref} refName={refName} title={rows.find((r) => r.id === sel)?.label ?? ''} clusters={clusterNames} colorOf={colorOf} budgets={Object.fromEntries(Object.entries(edits).map(([t, e]) => [t, num(e.budget)]))} />}
          <Card id="cpu-others" title="나머지 조합" note="전력 증가 또는 조건 미충족 · 정렬 가능" defaultWide minHeight={120}>
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
    <Card id="cpu-detail" title={`★ ${refName} vs ${title}`} note="무엇을 바꾸나 · cluster/CPU 점유 · task 시간" defaultWide>
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
                    <span className="mono" style={{ fontSize: 11 }}>{cpu.threads.length ? cpu.threads.join(', ') : <span className="faint">idle</span>}</span>
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
