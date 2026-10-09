import { useMemo, useState } from 'react'
import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { fmt, type Statistic } from '../lib/timingBudget'
import {
  DEFAULT_RUN, METRIC_COLOR, archApi, bestOption, caseCount, caseDelta, coverageOf, levels, promoteTargets, runBody, short, variantKey,
  type DistKey, type ExpCase, type RunDetail, type RunOptions, type VariantResult,
} from '../lib/archExplore'
import { Card } from '../components/TimingCharts'
import { AxisSpread, BufferSavings, CompositionBars, DomainLevels, IpModes, RangeBoxes, SplitBar, SplitLegend } from '../components/ArchCharts'
import { DataTable, type Column } from '../components/DataTable'
import { OPTION_NOTE, OptionResults, signed } from '../components/PowerOptions'
import { TiersView } from '../components/ExploreTiers'
import { useBattery, type Battery } from '../lib/battery'
import { JUDGE_CLASS, JUDGE_LABEL, judgePower, useReferences } from '../lib/review'
import { VariantFailures } from '../components/VariantFailures'
import { ProfileSelect } from '../components/ProfileSelect'
import { useSimProfiles } from '../lib/simProfile'

const METRICS: [DistKey, string, string][] = [['total_mw', 'Total', 'mW'], ['cpu_mw', 'CPU', 'mW'], ['bw_cpu_mw', 'CPU BW', 'mW'], ['hw_mw', 'IP', 'mW'], ['bw_ip_mw', 'IP BW', 'mW'], ['bw_mbs', 'BW MB/s', 'MB/s']]
const SCALES = [1.0, 1.1, 1.2, 1.3, 1.5]

export function ExplorePage({ ctx }: { ctx: Ctx }) {
  const runId = ctx.params.run
  const [tick, setTick] = useState(0)
  // default: runs of the selected 과제 only; other projects are an explicit, read-only comparison mode
  const [allProjects, setAllProjects] = useState(false)
  const runsQ = useAsync(() => archApi.runs(allProjects ? undefined : ctx.project || undefined), [tick, ctx.project, allProjects])
  const runs = runsQ.data ?? []
  const runQ = useAsync(() => (runId ? archApi.run(runId) : Promise.resolve(null)), [runId])
  const [showForm, setShowForm] = useState(!runId)
  const pick = (id: string | undefined) => ctx.navigate(undefined, { run: id, v: undefined })

  return (
    <div className="page tb-page">
      <div className="toolbar" style={{ gap: 12, flexWrap: 'wrap' }}>
        <span className="muted" style={{ fontSize: 13 }}>탐색 run</span>
        <select className="input" value={runId ?? ''} onChange={(e) => pick(e.target.value || undefined)} aria-label="탐색 run" style={{ minWidth: 360 }}
          disabled={runsQ.loading && !runsQ.data}>
          <option value="">{runsQ.loading && !runsQ.data ? '조회 중…' : runsQ.error ? '조회 실패' : runs.length ? '— 선택 —' : '탐색 run 없음'}</option>
          {runs.map((r) => <option key={r.id} value={r.id}>{allProjects ? `[${r.project_ref ?? '—'}] ` : ''}{r.title} · {r.summary.spec_ok}/{r.summary.variants} · {r.created_at?.slice(0, 16).replace('T', ' ')}</option>)}
        </select>
        <label className="ax-check" title="다른 과제의 run도 목록에 표시 (비교 보기 전용 · 예측 등록 불가)">
          <input type="checkbox" checked={allProjects} onChange={() => setAllProjects((x) => !x)} />다른 과제 포함 (비교)</label>
        {runsQ.error && <span className="err" style={{ margin: 0 }}>run 목록 조회 실패: {runsQ.error}</span>}
        <button className={`btn ${showForm ? 'primary' : ''}`} onClick={() => setShowForm((s) => !s)}>{showForm ? '새 탐색 닫기' : '＋ 새 탐색'}</button>
        <span className="grow" />
        <a className="btn" href={`#/predictions?scenario=${encodeURIComponent(ctx.scenario)}`}>예측 현황 →</a>
        <a className="btn" href="#/reports">검토 보고서 →</a>
      </div>
      {showForm && <RunForm ctx={ctx} onDone={(r) => { setTick((t) => t + 1); setShowForm(false); pick(r.id) }} />}
      {runQ.error && <div className="err">{runQ.error}</div>}
      {runQ.loading && runId && <div className="empty">run 불러오는 중…</div>}
      {runQ.data && <RunView key={runQ.data.id} run={runQ.data} ctx={ctx} />}
      {!runId && !showForm && <div className="empty">탐색 run을 선택하거나 새 탐색을 실행하세요.</div>}
    </div>
  )
}

// ---------------------------------------------------------------- new run
function RunForm({ ctx, onDone }: { ctx: Ctx; onDone: (r: RunDetail) => void }) {
  const [o, setO] = useState<RunOptions>(DEFAULT_RUN)
  const [scenarios, setScenarios] = useState<string[]>([ctx.scenario])
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string>()
  const [cfgSel, setCfgSel] = useState<string | undefined>(ctx.params.cfg)
  const sp = useSimProfiles(ctx.project, cfgSel)
  const set = <K extends keyof RunOptions>(k: K, v: RunOptions[K]) => setO((p) => ({ ...p, [k]: v }))
  const toggle = <T,>(list: T[], v: T) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v])
  const cases = caseCount(o)
  const variants = ctx.catalog.filter((c) => scenarios.includes(c.scenario_id)).reduce((s, c) => s + c.variant_count, 0)
  const typeLabel = ctx.catalog.filter((c) => scenarios.includes(c.scenario_id)).map((c) => c.scenario_name).join(' + ')
  const run = async () => {
    setBusy(true); setErr(undefined)
    try { onDone(await archApi.createRun(runBody(scenarios, title, typeLabel, o, sp.ref))) } catch (e) { setErr(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  const byCat = useMemo(() => {
    const g: Record<string, typeof ctx.catalog> = {}
    ctx.catalog.forEach((c) => { const k = c.category[0] ?? 'etc'; (g[k] ??= []).push(c) })
    return g
  }, [ctx.catalog])
  return (
    <section className="panel" style={{ padding: 14, display: 'grid', gap: 12 }} aria-label="새 탐색">
      <div className="ax-form">
        <div>
          <div className="ax-label">Scenario Type (탐색 대상)</div>
          <div className="ax-scen">
            {Object.entries(byCat).map(([cat, items]) => (
              <div key={cat}><span className="faint" style={{ fontSize: 11 }}>{cat}</span>
                {items.map((c) => <label key={c.scenario_id} className="ax-check"><input type="checkbox" checked={scenarios.includes(c.scenario_id)} onChange={() => setScenarios((s) => toggle(s, c.scenario_id))} />{c.scenario_name} <span className="faint">({c.variant_count})</span></label>)}
              </div>))}
          </div>
        </div>
        <div style={{ display: 'grid', gap: 10, alignContent: 'start' }}>
          <label className="ax-row"><span className="ax-label">제목</span><input className="input" style={{ flex: 1, minWidth: 260 }} value={title} placeholder={`${typeLabel} exploration`} onChange={(e) => setTitle(e.target.value)} /></label>
          <div className="ax-row"><span className="ax-label">SW 통계 (range)</span>
            {(['mean', 'max'] as Statistic[]).map((s) => <label key={s} className="ax-check"><input type="checkbox" checked={o.statistics.includes(s)} onChange={() => set('statistics', toggle(o.statistics, s))} />{s}</label>)}</div>
          <div className="ax-row"><span className="ax-label">차기 SW 증가</span>
            {SCALES.map((s) => <label key={s} className="ax-check"><input type="checkbox" checked={o.runtime_scales.includes(s)} onChange={() => set('runtime_scales', toggle(o.runtime_scales, s))} />×{s.toFixed(1)}</label>)}</div>
          <div className="ax-row"><span className="ax-label">DVFS headroom</span>
            <div className="seg sm">{[0, 1, 2].map((k) => <button key={k} className={o.dvfs_headroom_levels === k ? 'on' : ''} onClick={() => set('dvfs_headroom_levels', k)}>+{k} level</button>)}</div></div>
          <div className="ax-row"><span className="ax-label">Compression</span>
            {(['lossy', 'lossless'] as const).map((m) => <label key={m} className="ax-check"><input type="checkbox" checked={o.modes.includes(m)} onChange={() => set('modes', toggle(o.modes, m))} />{m}</label>)}
            <span className="faint" style={{ fontSize: 12 }}>buffer ≤</span>
            <input className="input" type="number" min={0} max={12} value={o.max_buffers} style={{ width: 64 }} onChange={(e) => set('max_buffers', Math.max(0, Math.min(12, Number(e.target.value) || 0)))} />
            <label className="ax-check"><input type="checkbox" checked={o.allow_lossy} onChange={() => set('allow_lossy', !o.allow_lossy)} />lossy 추천 허용</label>
            <label className="ax-check" title="체크 = variant의 측정 CPU profile을 EAS + schedutil로 재현해 SW 증가 축마다 cluster OPP·DSU·leakage와 CPU BW(측정 bus bytes)를 계산. profile이 없는 variant는 기존 가정 모델 유지 (결과의 CPU power 근거에 표시)"><input type="checkbox" checked={o.cpu_model === 'profile'} onChange={() => set('cpu_model', o.cpu_model === 'profile' ? 'flat' : 'profile')} />CPU: 측정 profile (EAS)</label>
            <label className="ax-check" title="해제하면 IP catalog에 압축 지원이 기재되지 않은 DMA도 탐색 (지원 여부 확인 전 잠재 절감 확인용)"><input type="checkbox" checked={o.require_declared} onChange={() => set('require_declared', !o.require_declared)} />지원 DMA만 (catalog 선언)</label></div>
          <div className="ax-row"><span className="ax-label">고객 budget</span>
            <span className="faint" style={{ fontSize: 12 }}>power ≤</span>
            <input className="input" type="number" min={0} placeholder="없음" value={o.power_budget_mw ?? ''} style={{ width: 80 }} aria-label="power budget mW"
              onChange={(e) => set('power_budget_mw', Number(e.target.value) > 0 ? Number(e.target.value) : null)} /><span className="faint" style={{ fontSize: 12 }}>mW · BW ≤</span>
            <input className="input" type="number" min={0} placeholder="없음" value={o.bw_budget_mbs ?? ''} style={{ width: 90 }} aria-label="BW budget MB/s"
              onChange={(e) => set('bw_budget_mbs', Number(e.target.value) > 0 ? Number(e.target.value) : null)} /><span className="faint" style={{ fontSize: 12 }}>MB/s</span>
            <label className="ax-check" title="variant마다 전과제 기준(review_policy power_reference) × (1 + 허용 %)를 power 상한으로 — 위 입력값과 함께 있으면 더 낮은 값. 기준이 없는 variant는 위 입력값만"><input type="checkbox" checked={!!o.budget_from_reference} onChange={() => set('budget_from_reference', !o.budget_from_reference)} />전과제 기준을 상한으로</label>
            <span className="faint" style={{ fontSize: 12 }}>넘는 조합은 추천 제외 · 미모델 IP가 있으면 판정 불가(unknown)</span></div>
          <div className="ax-row"><span className="ax-label">추천 기준</span>
            <div className="seg sm">{(['max', 'mean'] as Statistic[]).map((s) => <button key={s} className={o.objective_statistic === s ? 'on' : ''} onClick={() => set('objective_statistic', s)}>SW {s}</button>)}</div>
            <span className="faint" style={{ fontSize: 12 }}>× 증가</span>
            <div className="seg sm">{[1.0, 1.1, 1.2].map((s) => <button key={s} className={o.objective_scale === s ? 'on' : ''} onClick={() => set('objective_scale', s)}>×{s.toFixed(1)}</button>)}</div>
            <span className="faint" style={{ fontSize: 12 }}>= eligible 중 최저 total power</span></div>
          <div className="ax-row"><span className="ax-label">Power option</span>
            <label className="ax-check"><input type="checkbox" checked={o.options.knobs} onChange={() => set('options', { ...o.options, knobs: !o.options.knobs })} />arch knob (bcrop, L0 skip …)</label>
            <label className="ax-check" title="IP catalog sim.modes 중 현재 mode를 대체(substitutes)할 수 있는 mode를 unit power·ppc로 재시뮬레이션"><input type="checkbox" checked={o.options.modes} onChange={() => set('options', { ...o.options, modes: !o.options.modes })} />IP mode (대체 가능 mode · unit power별)</label>
            <span className="faint" style={{ fontSize: 12 }}>조합 ≤</span>
            <input className="input" type="number" min={1} max={256} value={o.options.max_sets} style={{ width: 70 }} aria-label="option 조합 상한"
              onChange={(e) => set('options', { ...o.options, max_sets: Math.max(1, Math.min(256, Number(e.target.value) || 1)) })} />
            <span className="faint" style={{ fontSize: 12 }}>full factorial · 조합별 재시뮬레이션 · variant 아님 (IQ 평가 대상)</span></div>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <span className="chip" title="파생(-explored-/-timing-) variant는 제외">variant ≤{variants} × 최대 {cases.toLocaleString()} 조합</span>
        <span className="faint" style={{ fontSize: 12 }}>SW 통계·증가 = timeline sim · DVFS·compression = analytic · 추천 조합은 재시뮬레이션 검증</span>
        <ProfileSelect profiles={sp.profiles} value={sp.ref} onChange={setCfgSel} />
        <span className="grow" />
        {(sp.error || err) && <span className="err" style={{ margin: 0 }}>{sp.error || err}</span>}
        <button className="btn primary" disabled={busy || !sp.ready || !scenarios.length || !o.statistics.length || !o.runtime_scales.length || cases > 200000} onClick={run}>
          {busy ? `탐색 중… (variant당 ~0.5 s)` : '탐색 실행'}</button>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------- run detail
function RunView({ run, ctx }: { run: RunDetail; ctx: Ctx }) {
  const [metric, setMetric] = useState<DistKey>('total_mw')
  const [filter, setFilter] = useState<'all' | 'ok' | 'fail'>('ok')
  const [order, setOrder] = useState<'power' | 'name'>('power')
  const [msg, setMsg] = useState<string>()
  const [busy, setBusy] = useState(false)
  const sel = run.variants.find((v) => variantKey(v) === ctx.params.v)
  const rows = run.variants.filter((v) => filter === 'all' || (filter === 'ok') === v.spec_ok)
  const ranked = order === 'name' ? rows : [...rows].sort((a, b) => (a.recommended?.[metric] ?? a.distribution[metric]?.median ?? 0) - (b.recommended?.[metric] ?? b.distribution[metric]?.median ?? 0))
  const s = run.summary
  const sample = (run.dvfs_table_ref ?? '').includes('sample')
  const choose = (vid: string) => ctx.navigate(undefined, { v: vid === ctx.params.v ? undefined : vid }, true)
  const foreign = !!ctx.project && run.project_ref !== ctx.project
  const targets = promoteTargets(run)
  const [confirm, setConfirm] = useState(false)
  const promoteAll = async () => {
    if (busy || foreign) return
    setBusy(true); setMsg(undefined)
    try {
      const r = await archApi.promote(run.id, undefined, undefined, undefined, undefined, run.project_ref ?? undefined)
      setMsg(`${r.promoted.length}개 variant를 최저 power 조합으로 등록 (건너뜀 ${r.skipped.length})`); setConfirm(false)
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  const report = async () => {
    if (busy) return
    setBusy(true); setMsg(undefined)
    try { const r = await archApi.createReport(run.id); ctx.navigate('reports', { report: r.id }) } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); setBusy(false) }
  }
  const kpis = [
    ['탐색 variant', `${s.variants}`, s.errors ? `실패 ${s.errors}` : run.scenario_type],
    ['spec 만족', `${s.spec_ok} / ${s.variants}`, `미달 ${s.variants - s.spec_ok}`],
    ['조합 수', s.cases.toLocaleString(), `eligible ${s.eligible_cases.toLocaleString()}`],
    ['추천 검증', `${s.verified} / ${s.spec_ok}`, '재시뮬레이션 power·BW 일치 + 제약 재적용'],
    ['추천 power', s.recommended_power_mw ? `${fmt(s.recommended_power_mw[0], 0)}–${fmt(s.recommended_power_mw[1], 0)}` : '—', 'mW (scenario별 최저)'],
    ['Power option (절감 variant)', `${s.power_options?.variants ?? 0}`, s.power_options?.best_saving_mw ? `최대 절감 ${fmt(s.power_options.best_saving_mw[0], 1)} ~ ${fmt(s.power_options.best_saving_mw[1], 1)} mW` : `${s.power_options?.sets ?? 0} 조합 · IQ 평가 대상`],
  ]
  const refs = useReferences(run.project_ref ?? undefined)
  const iqKeepRun = refs?.policy.register_baseline === 'iq_keep'
  const baseOf = (r: VariantResult) => (iqKeepRun ? r.keep_total_mw ?? r.tiers?.keep?.best.total_mw : undefined) ?? r.recommended?.total_mw ?? null
  const cols: Column<VariantResult>[] = [
    { key: 'v', label: 'Variant', width: 210, sticky: true, sort: (r) => r.variant_id, render: (r) => <span className="mono">{short(r.variant_id)}</span> },
    { key: 'fps', label: 'fps', width: 52, align: 'right', firstDir: -1, sort: (r) => r.fps, render: (r) => fmt(r.fps, 0) },
    { key: 'spec', label: 'spec', width: 96, sort: (r) => (r.spec_ok ? 1 : 0), title: (r) => [...r.spec_reasons, ...(coverageOf(r) === 'partial' ? [`전력 미모델 IP: ${(r.coverage?.zero_power_ips ?? []).join(', ')} — power는 모델된 IP 합계`] : [])].join('\n'),
      render: (r) => <span style={{ display: 'inline-flex', gap: 4 }}><span className={`badge ${r.spec_ok ? 'v-ok' : 'v-fail'}`}>{r.spec_ok ? 'OK' : 'Fail'}</span>
        {coverageOf(r) === 'partial' && <span className="badge v-warn">부분</span>}</span> },
    { key: 'tot', label: '추천 mW', width: 160, align: 'right', firstDir: -1, sort: (r) => r.recommended?.total_mw ?? -1, render: (r) => r.recommended ? <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}><SplitBar p={r.recommended} width={70} /><b className="mono">{fmt(r.recommended.total_mw, 1)}</b></span> : '—' },
    { key: 'cpu', label: 'CPU', width: 64, align: 'right', firstDir: -1, sort: (r) => r.recommended?.cpu_mw ?? -1, render: (r) => fmt(r.recommended?.cpu_mw, 0) },
    { key: 'hw', label: 'HW', width: 64, align: 'right', firstDir: -1, sort: (r) => r.recommended?.hw_mw ?? -1, render: (r) => fmt(r.recommended?.hw_mw, 0) },
    { key: 'bwip', label: 'IP BW', width: 70, align: 'right', firstDir: -1, sort: (r) => r.recommended?.bw_ip_mw ?? r.recommended?.bw_mw ?? -1, render: (r) => fmt(r.recommended?.bw_ip_mw ?? r.recommended?.bw_mw, 0) },
    { key: 'bwcpu', label: 'CPU BW', width: 74, align: 'right', firstDir: -1, sort: (r) => r.recommended?.bw_cpu_mw ?? -1, render: (r) => fmt(r.recommended?.bw_cpu_mw, 1) },
    { key: 'bw', label: 'BW MB/s', width: 84, align: 'right', firstDir: -1, sort: (r) => r.recommended?.bw_mbs ?? -1, render: (r) => fmt(r.recommended?.bw_mbs, 0) },
    ...(refs?.policy.power_reference ? [{ key: 'ref', label: '전과제 대비', width: 110, align: 'right' as const, firstDir: -1 as const,
      headTitle: `과제 review policy의 전과제 값 대비 (≤ +${refs.policy.power_reference.tolerance_pct}% 유사) · 기준 = ${iqKeepRun ? '화질 유지 최적 (기본 등록)' : '추천'}`,
      sort: (r: VariantResult) => judgePower(baseOf(r), refs.references[r.variant_id], refs.tolerance_pct)?.delta_pct ?? null,
      render: (r: VariantResult) => { const j = judgePower(baseOf(r), refs.references[r.variant_id], refs.tolerance_pct)
        return j ? <span className="mono">{j.delta_mw >= 0 ? '+' : ''}{fmt(j.delta_mw, 0)} <span className={`badge ${JUDGE_CLASS[j.status]}`} style={{ fontSize: 10.5 }}>{JUDGE_LABEL[j.status]}</span></span> : <span className="faint">—</span> } }] : []),
    { key: 'save', label: 'baseline 대비', width: 108, align: 'right', firstDir: 1, sort: (r) => (r.recommended ? r.recommended.total_mw - r.baseline.total_mw : 0), render: (r) => r.recommended ? <span className="mono" style={{ color: 'var(--primary-strong)' }}>{fmt(r.recommended.total_mw - r.baseline.total_mw, 1)}</span> : '—' },
    { key: 'opt', label: '절감 option', width: 120, align: 'right', firstDir: 1, sort: (r) => bestOption(r.power_options)?.delta_mw ?? 0,
      title: (r) => { const b = bestOption(r.power_options); return b ? `${b.labels.join(' + ')}\n${OPTION_NOTE}` : (r.power_options?.notes ?? []).join('\n') },
      render: (r) => { const b = bestOption(r.power_options); return b ? <span className="mono" style={{ color: 'var(--primary-strong)' }}><b>{signed(b.delta_mw)}</b> <span className="faint" style={{ fontSize: 11 }}>{signed(b.delta_pct)}%</span></span> : <span className="faint">—</span> } },
    { key: 'range', label: '설계공간 mW', width: 104, title: () => '탐색 조합의 power 분포 (설계공간 범위) — 실측 신뢰구간 아님', align: 'right', firstDir: -1, sort: (r) => r.distribution.total_mw.max - r.distribution.total_mw.min, render: (r) => <span className="mono">{fmt(r.distribution.total_mw.min, 0)}–{fmt(r.distribution.total_mw.max, 0)}</span> },
    { key: 'comp', label: 'Comp', width: 62, align: 'right', firstDir: -1, sort: (r) => r.recommended?.compression.length ?? -1, title: (r) => r.recommended?.compression.join(', '), render: (r) => r.recommended ? `${r.recommended.compression.length}${r.recommended.lossy ? ' L' : ''}` : '—' },
    { key: 'dvfs', label: 'DVFS', width: 170, sort: (r) => levels(r.recommended?.dvfs), render: (r) => <span className="mono faint">{levels(r.recommended?.dvfs) || '—'}</span> },
    { key: 'margin', label: 'SW margin', width: 90, align: 'right', firstDir: 1, sort: (r) => r.sw_margin.worst?.margin_pct ?? 999, title: (r) => r.sw_margin.recommendations.join('\n'), render: (r) => <span className="mono" style={{ color: (r.sw_margin.worst?.margin_pct ?? 1) < 0 ? 'var(--del-text)' : undefined }}>{fmt(r.sw_margin.worst?.margin_pct, 1)}%</span> },
    { key: 'grow', label: 'SW 증가 허용', width: 110, align: 'right', firstDir: -1, sort: (r) => r.sw_margin.growth_tolerance_fixed ?? r.sw_margin.growth_tolerance ?? 0,
      title: () => '추천 DVFS 고정 / DVFS 재선택', render: (r) => `${r.sw_margin.growth_tolerance_fixed ? `×${fmt(r.sw_margin.growth_tolerance_fixed, 1)}` : '—'} / ${r.sw_margin.growth_tolerance ? `×${fmt(r.sw_margin.growth_tolerance, 1)}` : '—'}` },
    { key: 'ver', label: '검증', width: 70, align: 'right', sort: (r) => Math.abs(r.recommended?.verified?.delta_pct ?? 99), render: (r) => { const v = r.recommended?.verified; return v ? <span title={[`sim ${fmt(v.sim_total_mw, 2)} / analytic ${fmt(v.analytic_total_mw, 2)} mW`, ...(v.sim_bw_mbs !== undefined ? [`BW sim ${fmt(v.sim_bw_mbs, 0)} / analytic ${fmt(v.analytic_bw_mbs, 0)} MB/s`] : []), ...(v.reasons ?? [])].join('\n')} style={{ color: v.ok ? 'var(--primary-strong)' : 'var(--del-text)' }}>{v.ok ? '✓' : '✗'} {fmt(v.delta_pct, 2)}%</span> : '—' } },
  ]
  return <>
    <section className="tb-kpis" aria-label="run 요약">
      {kpis.map(([l, v, n]) => <div key={l} className="panel tb-kpi"><div className="faint" style={{ fontSize: 12 }}>{l}</div><div className="mono" style={{ fontSize: 20, fontWeight: 600 }}>{v}</div><div className="faint" style={{ fontSize: 11 }}>{n}</div></div>)}
    </section>
    <div className="toolbar" style={{ gap: 10, flexWrap: 'wrap' }} aria-label="run 범위">
      <span className={`chip ${foreign ? 'mode-warn' : ''}`} title="이 run의 과제(project)">Project {run.project_ref ?? '—'}</span>
      <span className="chip" title="Target SoC">SoC {run.soc_ref ?? '—'}</span>
      <span className="chip" title="Sim config profile">Profile {run.config_profile_ref ?? '기본'}</span>
      <span className="chip">{run.scenario_type}</span>
      <span className={`chip ${sample ? 'mode-warn' : ''}`} title="DVFS table">DVFS {run.dvfs_table_ref ?? '미연결'}{sample ? ' · SAMPLE' : ''}</span>
      <span className="chip mode-info">MIF DVFS 미반영 · CPU 가정 모델</span>
      <span className="grow" />
      {msg && <span className="faint" style={{ fontSize: 12 }}>{msg}</span>}
      <button className="btn" disabled={busy || foreign || !targets.length} onClick={() => setConfirm((c) => !c)}
        title={foreign ? '다른 과제의 run — 비교 보기 전용' : 'spec 만족 variant 전체를 최저 power 조합으로 current 등록 (대상 확인 후)'}>최저 power 조합 전체 등록…</button>
      <button className="btn primary" disabled={busy} onClick={report}>{busy ? '처리 중…' : '검토 보고서 생성'}</button>
    </div>
    {foreign && <div className="err" role="status">이 run은 다른 과제({run.project_ref ?? '—'})의 결과입니다 — 비교 보기 전용이며, 현재 과제({ctx.project})의 예측으로 등록할 수 없습니다.</div>}
    {confirm && !foreign && <section className="panel" style={{ padding: 12, display: 'grid', gap: 8 }} aria-label="등록 대상 확인">
      <div><b>Project {run.project_ref}</b> · {targets.length}개 variant의 current 예측을 최저 power 조합으로 교체합니다. spec 미달 {run.variants.length - targets.length}개는 건너뜀.</div>
      <div className="faint mono" style={{ fontSize: 12, maxHeight: 120, overflow: 'auto' }}>{targets.map((v) => `${short(v.variant_id)} ${fmt(v.recommended?.total_mw, 1)} mW${coverageOf(v) === 'partial' ? ' (부분 모델)' : ''}`).join(' · ')}</div>
      <div style={{ display: 'flex', gap: 8 }}>
        <button className="btn primary" disabled={busy} onClick={promoteAll}>{busy ? '등록 중…' : `${targets.length}개 등록`}</button>
        <button className="btn" disabled={busy} onClick={() => setConfirm(false)}>취소</button></div>
    </section>}
    <VariantFailures errors={run.errors} />
    <div className="tb-grid">
      {sel && <VariantDetail key={variantKey(sel)} v={sel} run={run} readOnly={foreign} />}
      <Card id="ax-range" title="Scenario별 Power · BW range" note="행 클릭 = 조합 상세" defaultWide
        actions={<>
          <div className="seg sm">{METRICS.map(([k, l]) => <button key={k} className={metric === k ? 'on' : ''} onClick={() => setMetric(k)}><span className="ax-dot" style={{ background: METRIC_COLOR[k] }} />{l}</button>)}</div>
          <div className="seg sm">{(['ok', 'fail', 'all'] as const).map((f) => <button key={f} className={filter === f ? 'on' : ''} onClick={() => setFilter(f)}>{f === 'all' ? '전체' : f === 'ok' ? `만족 ${s.spec_ok}` : `미달 ${s.variants - s.spec_ok}`}</button>)}</div>
          <div className="seg sm">{(['power', 'name'] as const).map((f) => <button key={f} className={order === f ? 'on' : ''} onClick={() => setOrder(f)}>{f === 'power' ? '추천값 순' : '이름 순'}</button>)}</div></>}>
        <RangeBoxes unit={METRICS.find((m) => m[0] === metric)?.[2] ?? ''} selected={ctx.params.v} onPick={choose}
          color={METRIC_COLOR[metric]}
          rows={ranked.map((v) => ({ id: variantKey(v), label: short(v.variant_id), dist: v.distribution[metric], ok: v.spec_ok,
            marker: v.recommended?.[metric] ?? null, base: v.baseline[metric] ?? null }))} />
      </Card>
      <Card id="ax-comp-bars" title="추천 조합 Power 구성" note="CPU · CPU BW · IP · IP BW (mW) · range 카드와 같은 순서" defaultWide>
        <CompositionBars selected={ctx.params.v} onPick={choose} rows={ranked.map((v) => ({ id: variantKey(v), label: short(v.variant_id), p: v.recommended }))} />
      </Card>
      <Card id="ax-table" title="Variant 표" note="header 클릭 = 정렬 · 행 클릭 = 조합 상세" defaultWide minHeight={260}>
        <SplitLegend />
        <div className="table-x">
          <DataTable id="arch.variants" columns={cols} rows={rows} rowKey={variantKey} onRowClick={(r) => choose(variantKey(r))} defaultSort={{ key: 'tot', dir: -1 }}
            rowClass={(r) => (variantKey(r) === ctx.params.v ? 'selected' : '')} />
        </div>
      </Card>
    </div>
  </>
}

// ---------------------------------------------------------------- one variant
function VariantDetail({ v, run, readOnly }: { v: VariantResult; run: RunDetail; readOnly: boolean }) {
  const battery = useBattery(run.project_ref ?? undefined)
  const refs = useReferences(run.project_ref ?? undefined)
  // list rows are summaries; slices, buffers, DVFS domains, IP modes and option results load per variant
  const fullQ = useAsync(() => (v.detail === false ? archApi.runVariant(run.id, v.scenario_id, v.variant_id) : Promise.resolve(v)),
    [run.id, v.scenario_id, v.variant_id])
  if (fullQ.error) return <div className="err" style={{ gridColumn: '1 / -1' }}>{short(v.variant_id)} 상세 조회 실패: {fullQ.error}</div>
  if (!fullQ.data) return <div className="empty" style={{ gridColumn: '1 / -1' }}>{short(v.variant_id)} 상세 불러오는 중…</div>
  return <VariantDetailBody v={fullQ.data} run={run} readOnly={readOnly} battery={battery} iqKeep={refs?.policy.register_baseline === 'iq_keep'} />
}

function VariantDetailBody({ v, run, readOnly, battery, iqKeep = false }: { v: VariantResult; run: RunDetail; readOnly: boolean; battery: Battery; iqKeep?: boolean }) {
  const rec = v.recommended
  const listed = new Set([rec?.key, ...v.alternatives.map((c) => c.key), v.baseline.key])
  const pareto = (v.pareto ?? []).filter((c) => !listed.has(c.key))
  // project policy "iq_keep": the default registration is the IQ/performance-keeping optimum (tier A), not the lossy minimum
  const keepCase = iqKeep ? v.tiers?.keep?.best ?? null : null
  const keepRow = keepCase && keepCase.key !== rec?.key ? [{ rank: '기본 등록 · 화질 유지', c: keepCase }] : []
  const defaultKey = keepCase?.key ?? rec?.key
  const cands: { rank: string; c: ExpCase }[] = rec
    ? [...keepRow, { rank: keepRow.length ? '최저 power (lossy)' : '추천', c: rec }, ...v.alternatives.map((c, i) => ({ rank: `#${i + 2}`, c })), ...pareto.map((c, i) => ({ rank: `Pareto ${i + 1}`, c })), { rank: 'baseline', c: v.baseline }]
    : [{ rank: 'baseline', c: v.baseline }]
  const seenKeys = new Set<string>()
  const candRows = cands.filter((x) => (seenKeys.has(x.c.key) ? false : (seenKeys.add(x.c.key), true)))
  const [pick, setPick] = useState<string | undefined>(defaultKey)
  const [reason, setReason] = useState('')
  const [msg, setMsg] = useState<string>()
  const [busy, setBusy] = useState(false)
  const promote = async () => {
    if (busy || readOnly) return
    const chosen = pick && pick !== defaultKey ? pick : undefined
    setBusy(true); setMsg(undefined)
    try {
      const r = await archApi.promote(run.id, [v.variant_id], chosen, reason || undefined, v.scenario_id, run.project_ref ?? undefined)
      setMsg(r.promoted.length ? `등록: ${r.promoted[0].id} (${fmt(r.promoted[0].total_mw, 1)} mW)` : `건너뜀: ${r.skipped[0]?.reason}`)
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  const m = v.sw_margin
  return <>
    <Card id="ax-cases" title={`${short(v.variant_id)} — 추천 · 대안 조합`} note={`${v.counts.cases.toLocaleString()} 조합 · eligible ${v.counts.eligible.toLocaleString()} · ${fmt(v.fps, 0)} fps${v.eis_on ? ' · EIS' : ''} · 판정 ${v.throughput_model === 'pipelined' ? 'pipeline buffering' : 'stage 1 frame'}${keepRow.length ? ' · 기본 등록 = 화질 유지 최적 (과제 기준)' : ''}`} defaultWide>
      {(v.ip_modes ?? []).length > 0 && <div className="faint" style={{ fontSize: 12, marginBottom: 6 }}>
        IP mode (모든 조합 공통): {(v.ip_modes ?? []).map((m) => `${m.node.toUpperCase()} ${m.mode}${m.unit_power_mw_mp !== null ? ` ${fmt(m.unit_power_mw_mp, 2)}` : ''}`).join(' · ')} <span className="mono">mW/MP</span>
        {(v.ip_modes ?? []).some((m) => m.alternatives.some((a) => a.explorable)) && <> · 대체 mode 결과는 아래 Power option / IP mode 카드</>}</div>}
      {v.power_budget?.mw && <div className="faint" style={{ fontSize: 12, marginBottom: 4 }}>power budget ≤ <b className="mono">{v.power_budget.mw.toFixed(0)}</b> mW ({v.power_budget.source}{v.power_budget.reference_mw ? ` · 기준 ${v.power_budget.reference_mw.toFixed(0)} mW` : ''})
        {v.status?.power_budget_status && <span className={`badge ${v.status.power_budget_status === 'pass' ? 'v-ok' : v.status.power_budget_status === 'fail' ? 'v-fail' : 'v-info'}`} style={{ marginLeft: 6 }}>{v.status.power_budget_status}</span>}</div>}
      {!v.spec_ok && <div className="err" style={{ fontSize: 12 }}>{v.spec_reasons.slice(0, 3).map((x) => <div key={x}>{x}</div>)}</div>}
      {coverageOf(v) === 'partial' && <div className="faint" style={{ fontSize: 12, marginBottom: 6 }}>
        <span className="badge v-warn">부분 모델</span> 전력 미모델 IP {(v.coverage?.zero_power_ips ?? []).join(', ')} — Total은 모델된 IP 합계(하한)
        {v.status?.power_budget_status === 'unknown' ? ' · power budget 판정 불가' : ''}</div>}
      <table className="tb-mini-table" style={{ width: '100%' }}>
        <thead><tr><th /><th>순위</th><th>Total mW</th><th title="CPU / CPU BW / IP / IP BW">CPU / CPU BW / IP / IP BW</th><th>BW MB/s</th><th>Δ 추천 대비</th><th>SW</th><th>Compression</th><th>DVFS</th></tr></thead>
        <tbody>{candRows.map(({ rank, c }) => {
          const d = rec ? caseDelta(c, rec) : null
          return (
            <tr key={c.key} className={pick === c.key ? 'selected' : ''} onClick={() => setPick(c.key)} style={{ cursor: 'pointer' }}>
              <td><input type="radio" checked={pick === c.key} onChange={() => setPick(c.key)} aria-label={`${rank} 선택`} /></td>
              <td>{rank}{c.lossy && c.compression.length ? <span className="badge v-warn" style={{ marginLeft: 4 }}>lossy</span> : null}{c.assumed_ratio && c.compression.length ? <span className="badge v-warn" style={{ marginLeft: 4 }} title="catalog에 없는 ratio 사용">가정</span> : null}</td>
              <td className="mono"><b>{fmt(c.total_mw, 1)}</b></td>
              <td><span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}><SplitBar p={c} width={80} /><span className="mono faint">{fmt(c.cpu_mw, 0)}/{fmt(c.bw_cpu_mw, 0)}/{fmt(c.hw_mw, 0)}/{fmt(c.bw_ip_mw ?? c.bw_mw, 0)}</span></span></td>
              <td className="mono">{fmt(c.bw_mbs, 0)}</td>
              <td className="mono" style={{ color: d && d.total > 0 ? 'var(--del-text)' : undefined }}>{d ? `${d.total >= 0 ? '+' : ''}${fmt(d.total, 1)}` : '—'}</td>
              <td className="mono faint">{c.statistic} ×{c.runtime_scale}</td>
              <td title={c.compression.join(', ')}>{c.compression.length ? `${c.compression.length} buf` : '—'}</td>
              <td className="mono faint">{levels(c.dvfs)}{c.dvfs_raise ? ` (+${c.dvfs_raise})` : ''}</td>
            </tr>)
        })}</tbody>
      </table>
      <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <input className="input" style={{ flex: 1, minWidth: 240 }} placeholder={pick === defaultKey || pick === rec?.key ? '사유 (선택)' : '추천 외 조합 선택 사유 (필수)'} value={reason} onChange={(e) => setReason(e.target.value)} />
        <button className="btn primary" disabled={busy || readOnly || !v.spec_ok || (pick !== defaultKey && pick !== rec?.key && !reason)} onClick={promote}
          title={readOnly ? '다른 과제의 run — 비교 보기 전용' : undefined}>{busy ? '등록 중…' : '예측으로 등록 (current)'}</button>
        {msg && <span className="faint" style={{ fontSize: 12 }}>{msg}</span>}
      </div>
    </Card>
 <Card id="ax-tiers" title={`${short(v.variant_id)} — 화질·성능 유지 최적 범위 vs Power 우선 메뉴`} note="A = lossy · IQ option 없이 timing 만족 최저 + 최저 +3% 이내 평가 조합 · B = 화질을 희생할 때 항목별 단독 효과" defaultWide>
      <TiersView v={v} battery={battery} /></Card>
 {v.power_options && <Card id="ax-options" title="Power option 조합 (IQ 평가 대상)" note={`${OPTION_NOTE}${(v.power_options.fixed ?? []).length ? ' · 고정 대비 = 항상 이득인 option을 고정했을 때 나머지 option의 추가 효과' : ''}`} defaultWide>
      <div style={{ display: 'grid', gap: 8 }}>
        <div className="faint" style={{ fontSize: 12 }}>
          {v.power_options.dimensions.map((d) => `${d.label}: ${d.current} → ${d.items.map((i) => i.value).join(' / ')}`).join(' · ') || '적용 가능한 option 없음'}
          {v.power_options.status === 'ok' ? ` · ${v.power_options.sets} 조합` : ''}</div>
        {v.power_options.notes.length > 0 && <ul className="faint" style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>{v.power_options.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
        {v.power_options.errors.length > 0 && <div className="err" style={{ fontSize: 12 }}>{v.power_options.errors.map((e) => `${e.key}: ${e.error}`).join(' · ')}</div>}
        {v.power_options.status === 'ok' && <OptionResults results={v.power_options.results} best={v.power_options.best} />}
        <div className="faint" style={{ fontSize: 11 }}>예측으로 등록하면 이 결과가 예측 현황에 함께 저장되고, 거기서 IQ 평가 상태를 관리합니다.</div>
      </div>
    </Card>}
    <Card id="ax-spread" title="Power range 원인 (축별)" note="SW · compression · DVFS"><AxisSpread spread={v.axis_spread} /></Card>
    <Card id="ax-sw" title="SW timing margin · 권고" note="(P − SW − overhead − HW@set clock)/P">
      <table className="tb-mini-table" style={{ width: '100%' }}>
        <thead><tr><th>stage</th><th>margin</th><th>SW / P</th><th>병목</th><th>latency 비중</th></tr></thead>
        <tbody>{m.stages.map((s) => <tr key={s.stage}><td>{s.stage.toUpperCase()}</td>
          <td className="mono" style={{ color: s.margin_pct < 0 ? 'var(--del-text)' : undefined }}>{fmt(s.margin_pct, 1)}% · {fmt(s.slack_ms, 2)} ms</td>
          <td className="mono">{fmt(s.sw_share_pct, 0)}%</td><td className="mono">{s.bottleneck} {fmt(s.bottleneck_ms, 1)} ms</td><td className="mono">{fmt(s.latency_share_pct, 0)}%</td></tr>)}</tbody>
      </table>
      <div className="faint" style={{ fontSize: 12, margin: '6px 0' }}>
        SW 증가 허용 — DVFS 재선택 {m.growth_tolerance ? `×${fmt(m.growth_tolerance, 1)}` : '—'} · <b>추천 DVFS 고정 {m.growth_tolerance_fixed ? `×${fmt(m.growth_tolerance_fixed, 1)}` : '—'}</b> (탐색 최대 ×{fmt(m.growth_tested_max, 1)}) · max–mean 편차 {fmt(m.stat_spread_ms, 1)} ms
        {(m.growth_fixed_rows ?? []).some((r) => !r.ok && r.short_domains.length) && <> · 고정 시 부족 domain: {(m.growth_fixed_rows ?? []).filter((r) => !r.ok).map((r) => `×${fmt(r.runtime_scale, 1)} ${r.short_domains.join('/') || 'timing'}`).join(', ')}</>}</div>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>{m.recommendations.map((r) => <li key={r}>{r}</li>)}</ul>
    </Card>
    <Card id="ax-modes" title="IP mode · unit power" note="IP별 현재 mode와 대안 mode · mode마다 unit power가 다름" defaultWide>
      <IpModes rows={v.ip_modes ?? []} results={v.power_options?.results} /></Card>
    <Card id="ax-comp" title="Compression BW 절감 (buffer별)" note="지원 DMA만 탐색 · 단독 적용 시 Δ · 합산 가능(port 독립)"><BufferSavings buffers={v.buffers} selected={rec?.compression ?? []} /></Card>
    <Card id="ax-dvfs" title="DVFS domain level" note="scenario별 level · +level은 전압↑ → power↑"><DomainLevels domains={v.domains} chosen={rec?.dvfs ?? {}} /></Card>
  </>
}
