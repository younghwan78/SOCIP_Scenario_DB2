import { useMemo, useState } from 'react'
import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { fmt, type Statistic } from '../lib/timingBudget'
import {
  DEFAULT_RUN, METRIC_COLOR, archApi, caseCount, caseDelta, levels, runBody, short,
  type DistKey, type ExpCase, type RunDetail, type RunOptions, type VariantResult,
} from '../lib/archExplore'
import { Card } from '../components/TimingCharts'
import { AxisSpread, BufferSavings, DomainLevels, RangeBoxes, SplitBar, SplitLegend } from '../components/ArchCharts'
import { DataTable, type Column } from '../components/DataTable'

const METRICS: [DistKey, string, string][] = [['total_mw', 'Total', 'mW'], ['cpu_mw', 'CPU', 'mW'], ['hw_mw', 'IP', 'mW'], ['bw_mw', 'BW power', 'mW'], ['bw_mbs', 'BW', 'MB/s']]
const SCALES = [1.0, 1.1, 1.2, 1.3, 1.5]

export function ExplorePage({ ctx }: { ctx: Ctx }) {
  const runId = ctx.params.run
  const [tick, setTick] = useState(0)
  const runsQ = useAsync(() => archApi.runs(), [tick])
  const runQ = useAsync(() => (runId ? archApi.run(runId) : Promise.resolve(null)), [runId])
  const [showForm, setShowForm] = useState(!runId)
  const pick = (id: string | undefined) => ctx.navigate(undefined, { run: id, v: undefined })

  return (
    <div className="page tb-page">
      <div className="toolbar" style={{ gap: 12, flexWrap: 'wrap' }}>
        <span className="muted" style={{ fontSize: 13 }}>탐색 run</span>
        <select className="input" value={runId ?? ''} onChange={(e) => pick(e.target.value || undefined)} aria-label="탐색 run" style={{ minWidth: 360 }}>
          <option value="">— 선택 —</option>
          {(runsQ.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.title} · {r.summary.spec_ok}/{r.summary.variants} · {r.created_at?.slice(0, 16).replace('T', ' ')}</option>)}
        </select>
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
  const set = <K extends keyof RunOptions>(k: K, v: RunOptions[K]) => setO((p) => ({ ...p, [k]: v }))
  const toggle = <T,>(list: T[], v: T) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v])
  const cases = caseCount(o)
  const variants = ctx.catalog.filter((c) => scenarios.includes(c.scenario_id)).reduce((s, c) => s + c.variant_count, 0)
  const typeLabel = ctx.catalog.filter((c) => scenarios.includes(c.scenario_id)).map((c) => c.scenario_name).join(' + ')
  const run = async () => {
    setBusy(true); setErr(undefined)
    try { onDone(await archApi.createRun(runBody(scenarios, title, typeLabel, o))) } catch (e) { setErr(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
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
            <label className="ax-check"><input type="checkbox" checked={o.allow_lossy} onChange={() => set('allow_lossy', !o.allow_lossy)} />lossy 추천 허용</label></div>
          <div className="ax-row"><span className="ax-label">추천 기준</span>
            <div className="seg sm">{(['max', 'mean'] as Statistic[]).map((s) => <button key={s} className={o.objective_statistic === s ? 'on' : ''} onClick={() => set('objective_statistic', s)}>SW {s}</button>)}</div>
            <span className="faint" style={{ fontSize: 12 }}>× 증가</span>
            <div className="seg sm">{[1.0, 1.1, 1.2].map((s) => <button key={s} className={o.objective_scale === s ? 'on' : ''} onClick={() => set('objective_scale', s)}>×{s.toFixed(1)}</button>)}</div>
            <span className="faint" style={{ fontSize: 12 }}>= eligible 중 최저 total power</span></div>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <span className="chip" title="파생(-explored-/-timing-) variant는 제외">variant ≤{variants} × 최대 {cases.toLocaleString()} 조합</span>
        <span className="faint" style={{ fontSize: 12 }}>SW 통계·증가 = timeline sim · DVFS·compression = analytic · 추천 조합은 재시뮬레이션 검증</span>
        <span className="grow" />
        {err && <span className="err" style={{ margin: 0 }}>{err}</span>}
        <button className="btn primary" disabled={busy || !scenarios.length || !o.statistics.length || !o.runtime_scales.length || cases > 200000} onClick={run}>
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
  const sel = run.variants.find((v) => v.variant_id === ctx.params.v)
  const rows = run.variants.filter((v) => filter === 'all' || (filter === 'ok') === v.spec_ok)
  const ranked = order === 'name' ? rows : [...rows].sort((a, b) => (a.recommended?.[metric] ?? a.distribution[metric].median) - (b.recommended?.[metric] ?? b.distribution[metric].median))
  const s = run.summary
  const sample = (run.dvfs_table_ref ?? '').includes('sample')
  const choose = (vid: string) => ctx.navigate(undefined, { v: vid === ctx.params.v ? undefined : vid }, true)
  const promoteAll = async () => {
    setBusy(true); setMsg(undefined)
    try { const r = await archApi.promote(run.id); setMsg(`${r.promoted.length}개 variant를 최저 power 조합으로 등록 (건너뜀 ${r.skipped.length})`) } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  const report = async () => {
    setBusy(true); setMsg(undefined)
    try { const r = await archApi.createReport(run.id); ctx.navigate('reports', { report: r.id }) } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); setBusy(false) }
  }
  const kpis = [
    ['탐색 variant', `${s.variants}`, s.errors ? `실패 ${s.errors}` : run.scenario_type],
    ['spec 만족', `${s.spec_ok} / ${s.variants}`, `미달 ${s.variants - s.spec_ok}`],
    ['조합 수', s.cases.toLocaleString(), `eligible ${s.eligible_cases.toLocaleString()}`],
    ['추천 검증', `${s.verified} / ${s.spec_ok}`, '재시뮬레이션 |Δ| < 0.5%'],
    ['추천 power', s.recommended_power_mw ? `${fmt(s.recommended_power_mw[0], 0)}–${fmt(s.recommended_power_mw[1], 0)}` : '—', 'mW (scenario별 최저)'],
  ]
  const cols: Column<VariantResult>[] = [
    { key: 'v', label: 'Variant', width: 210, sticky: true, sort: (r) => r.variant_id, render: (r) => <span className="mono">{short(r.variant_id)}</span> },
    { key: 'fps', label: 'fps', width: 52, align: 'right', firstDir: -1, sort: (r) => r.fps, render: (r) => fmt(r.fps, 0) },
    { key: 'spec', label: 'spec', width: 64, sort: (r) => (r.spec_ok ? 1 : 0), title: (r) => r.spec_reasons.join('\n'), render: (r) => <span className={`badge ${r.spec_ok ? 'v-ok' : 'v-fail'}`}>{r.spec_ok ? 'OK' : 'Fail'}</span> },
    { key: 'tot', label: '추천 mW', width: 160, align: 'right', firstDir: -1, sort: (r) => r.recommended?.total_mw ?? -1, render: (r) => r.recommended ? <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}><SplitBar p={r.recommended} width={70} /><b className="mono">{fmt(r.recommended.total_mw, 1)}</b></span> : '—' },
    { key: 'cpu', label: 'CPU', width: 64, align: 'right', firstDir: -1, sort: (r) => r.recommended?.cpu_mw ?? -1, render: (r) => fmt(r.recommended?.cpu_mw, 0) },
    { key: 'hw', label: 'HW', width: 64, align: 'right', firstDir: -1, sort: (r) => r.recommended?.hw_mw ?? -1, render: (r) => fmt(r.recommended?.hw_mw, 0) },
    { key: 'bwp', label: 'BW', width: 64, align: 'right', firstDir: -1, sort: (r) => r.recommended?.bw_mw ?? -1, render: (r) => fmt(r.recommended?.bw_mw, 0) },
    { key: 'bw', label: 'BW MB/s', width: 84, align: 'right', firstDir: -1, sort: (r) => r.recommended?.bw_mbs ?? -1, render: (r) => fmt(r.recommended?.bw_mbs, 0) },
    { key: 'save', label: 'baseline 대비', width: 108, align: 'right', firstDir: 1, sort: (r) => (r.recommended ? r.recommended.total_mw - r.baseline.total_mw : 0), render: (r) => r.recommended ? <span className="mono" style={{ color: 'var(--primary-strong)' }}>{fmt(r.recommended.total_mw - r.baseline.total_mw, 1)}</span> : '—' },
    { key: 'range', label: 'range mW', width: 104, align: 'right', firstDir: -1, sort: (r) => r.distribution.total_mw.max - r.distribution.total_mw.min, render: (r) => <span className="mono">{fmt(r.distribution.total_mw.min, 0)}–{fmt(r.distribution.total_mw.max, 0)}</span> },
    { key: 'comp', label: 'Comp', width: 62, align: 'right', firstDir: -1, sort: (r) => r.recommended?.compression.length ?? -1, title: (r) => r.recommended?.compression.join(', '), render: (r) => r.recommended ? `${r.recommended.compression.length}${r.recommended.lossy ? ' L' : ''}` : '—' },
    { key: 'dvfs', label: 'DVFS', width: 170, sort: (r) => levels(r.recommended?.dvfs), render: (r) => <span className="mono faint">{levels(r.recommended?.dvfs) || '—'}</span> },
    { key: 'margin', label: 'SW margin', width: 90, align: 'right', firstDir: 1, sort: (r) => r.sw_margin.worst?.margin_pct ?? 999, title: (r) => r.sw_margin.recommendations.join('\n'), render: (r) => <span className="mono" style={{ color: (r.sw_margin.worst?.margin_pct ?? 1) < 0 ? 'var(--del-text)' : undefined }}>{fmt(r.sw_margin.worst?.margin_pct, 1)}%</span> },
    { key: 'grow', label: 'SW 증가 허용', width: 96, align: 'right', firstDir: -1, sort: (r) => r.sw_margin.growth_tolerance ?? 0, render: (r) => (r.sw_margin.growth_tolerance ? `×${fmt(r.sw_margin.growth_tolerance, 1)}` : '—') },
    { key: 'ver', label: '검증', width: 70, align: 'right', sort: (r) => Math.abs(r.recommended?.verified?.delta_pct ?? 99), render: (r) => { const v = r.recommended?.verified; return v ? <span title={`sim ${fmt(v.sim_total_mw, 2)} / analytic ${fmt(v.analytic_total_mw, 2)} mW`} style={{ color: v.ok ? 'var(--primary-strong)' : 'var(--del-text)' }}>{v.ok ? '✓' : '✗'} {fmt(v.delta_pct, 2)}%</span> : '—' } },
  ]
  return <>
    <section className="tb-kpis" aria-label="run 요약">
      {kpis.map(([l, v, n]) => <div key={l} className="panel tb-kpi"><div className="faint" style={{ fontSize: 12 }}>{l}</div><div className="mono" style={{ fontSize: 20, fontWeight: 600 }}>{v}</div><div className="faint" style={{ fontSize: 11 }}>{n}</div></div>)}
    </section>
    <div className="toolbar" style={{ gap: 10, flexWrap: 'wrap' }}>
      <span className="chip">{run.soc_ref ?? '—'}</span><span className="chip">{run.scenario_type}</span>
      <span className={`chip ${sample ? 'mode-warn' : ''}`} title="DVFS table">DVFS {run.dvfs_table_ref ?? '미연결'}{sample ? ' · SAMPLE' : ''}</span>
      <span className="chip mode-info">MIF DVFS 미반영 · CPU 가정 모델</span>
      <span className="grow" />
      {msg && <span className="faint" style={{ fontSize: 12 }}>{msg}</span>}
      <button className="btn" disabled={busy} onClick={promoteAll} title="spec 만족 variant 전체를 최저 power 조합으로 current 등록">최저 power 조합 전체 등록</button>
      <button className="btn primary" disabled={busy} onClick={report}>검토 보고서 생성</button>
    </div>
    {run.errors.length > 0 && <div className="err">{run.errors.length}개 variant 계산 실패: {run.errors.slice(0, 3).map((e) => e.variant_id).join(', ')}</div>}
    <div className="tb-grid">
      {sel && <VariantDetail key={sel.variant_id} v={sel} run={run} />}
      <Card id="ax-range" title="Scenario별 Power · BW range" note="행 클릭 = 조합 상세" defaultWide
        actions={<>
          <div className="seg sm">{METRICS.map(([k, l]) => <button key={k} className={metric === k ? 'on' : ''} onClick={() => setMetric(k)}><span className="ax-dot" style={{ background: METRIC_COLOR[k] }} />{l}</button>)}</div>
          <div className="seg sm">{(['ok', 'fail', 'all'] as const).map((f) => <button key={f} className={filter === f ? 'on' : ''} onClick={() => setFilter(f)}>{f === 'all' ? '전체' : f === 'ok' ? `만족 ${s.spec_ok}` : `미달 ${s.variants - s.spec_ok}`}</button>)}</div>
          <div className="seg sm">{(['power', 'name'] as const).map((f) => <button key={f} className={order === f ? 'on' : ''} onClick={() => setOrder(f)}>{f === 'power' ? '추천값 순' : '이름 순'}</button>)}</div></>}>
        <RangeBoxes unit={METRICS.find((m) => m[0] === metric)?.[2] ?? ''} selected={ctx.params.v} onPick={choose}
          color={METRIC_COLOR[metric]} split={metric === 'total_mw'}
          rows={ranked.map((v) => ({ id: v.variant_id, label: short(v.variant_id), dist: v.distribution[metric], ok: v.spec_ok,
            marker: v.recommended ? v.recommended[metric] : null, base: v.baseline[metric], parts: v.recommended }))} />
      </Card>
      <Card id="ax-table" title="Variant 표" note="header 클릭 = 정렬 · 행 클릭 = 조합 상세" defaultWide minHeight={260}>
        <SplitLegend />
        <div className="table-scroll" style={{ maxHeight: 560 }}>
          <DataTable id="arch.variants" columns={cols} rows={rows} rowKey={(r) => r.variant_id} onRowClick={(r) => choose(r.variant_id)} defaultSort={{ key: 'tot', dir: -1 }}
            rowClass={(r) => (r.variant_id === ctx.params.v ? 'selected' : '')} />
        </div>
      </Card>
    </div>
  </>
}

// ---------------------------------------------------------------- one variant
function VariantDetail({ v, run }: { v: VariantResult; run: RunDetail }) {
  const rec = v.recommended
  const cands: { rank: string; c: ExpCase }[] = rec ? [{ rank: '추천', c: rec }, ...v.alternatives.map((c, i) => ({ rank: `#${i + 2}`, c })), { rank: 'baseline', c: v.baseline }] : [{ rank: 'baseline', c: v.baseline }]
  const [pick, setPick] = useState<string | undefined>(rec?.key)
  const [reason, setReason] = useState('')
  const [msg, setMsg] = useState<string>()
  const promote = async () => {
    const chosen = pick && pick !== rec?.key ? pick : undefined
    try {
      const r = await archApi.promote(run.id, [v.variant_id], chosen, reason || undefined)
      setMsg(r.promoted.length ? `등록: ${r.promoted[0].id} (${fmt(r.promoted[0].total_mw, 1)} mW)` : `건너뜀: ${r.skipped[0]?.reason}`)
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }
  const m = v.sw_margin
  return <>
    <Card id="ax-cases" title={`${short(v.variant_id)} — 추천 · 대안 조합`} note={`${v.counts.cases.toLocaleString()} 조합 · eligible ${v.counts.eligible.toLocaleString()} · ${fmt(v.fps, 0)} fps${v.eis_on ? ' · EIS' : ''}`} defaultWide>
      {!v.spec_ok && <div className="err" style={{ fontSize: 12 }}>{v.spec_reasons.slice(0, 3).map((x) => <div key={x}>{x}</div>)}</div>}
      <table className="tb-mini-table" style={{ width: '100%' }}>
        <thead><tr><th /><th>순위</th><th>Total mW</th><th>CPU / IP / BW</th><th>BW MB/s</th><th>Δ 추천 대비</th><th>SW</th><th>Compression</th><th>DVFS</th></tr></thead>
        <tbody>{cands.map(({ rank, c }) => {
          const d = rec ? caseDelta(c, rec) : null
          return (
            <tr key={c.key} className={pick === c.key ? 'selected' : ''} onClick={() => setPick(c.key)} style={{ cursor: 'pointer' }}>
              <td><input type="radio" checked={pick === c.key} onChange={() => setPick(c.key)} aria-label={`${rank} 선택`} /></td>
              <td>{rank}{c.lossy && c.compression.length ? <span className="badge v-warn" style={{ marginLeft: 4 }}>lossy</span> : null}{c.assumed_ratio && c.compression.length ? <span className="badge v-warn" style={{ marginLeft: 4 }} title="catalog에 없는 ratio 사용">가정</span> : null}</td>
              <td className="mono"><b>{fmt(c.total_mw, 1)}</b></td>
              <td><span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}><SplitBar p={c} width={80} /><span className="mono faint">{fmt(c.cpu_mw, 0)}/{fmt(c.hw_mw, 0)}/{fmt(c.bw_mw, 0)}</span></span></td>
              <td className="mono">{fmt(c.bw_mbs, 0)}</td>
              <td className="mono" style={{ color: d && d.total > 0 ? 'var(--del-text)' : undefined }}>{d ? `${d.total >= 0 ? '+' : ''}${fmt(d.total, 1)}` : '—'}</td>
              <td className="mono faint">{c.statistic} ×{c.runtime_scale}</td>
              <td title={c.compression.join(', ')}>{c.compression.length ? `${c.compression.length} buf` : '—'}</td>
              <td className="mono faint">{levels(c.dvfs)}{c.dvfs_raise ? ` (+${c.dvfs_raise})` : ''}</td>
            </tr>)
        })}</tbody>
      </table>
      <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <input className="input" style={{ flex: 1, minWidth: 240 }} placeholder={pick === rec?.key ? '사유 (선택)' : '추천 외 조합 선택 사유 (필수)'} value={reason} onChange={(e) => setReason(e.target.value)} />
        <button className="btn primary" disabled={!v.spec_ok || (pick !== rec?.key && !reason)} onClick={promote}>예측으로 등록 (current)</button>
        {msg && <span className="faint" style={{ fontSize: 12 }}>{msg}</span>}
      </div>
    </Card>
    <Card id="ax-spread" title="Power range 원인 (축별)" note="SW · compression · DVFS"><AxisSpread spread={v.axis_spread} /></Card>
    <Card id="ax-sw" title="SW timing margin · 권고" note="(P − SW − overhead − HW@set clock)/P">
      <table className="tb-mini-table" style={{ width: '100%' }}>
        <thead><tr><th>stage</th><th>margin</th><th>SW / P</th><th>병목</th><th>latency 비중</th></tr></thead>
        <tbody>{m.stages.map((s) => <tr key={s.stage}><td>{s.stage.toUpperCase()}</td>
          <td className="mono" style={{ color: s.margin_pct < 0 ? 'var(--del-text)' : undefined }}>{fmt(s.margin_pct, 1)}% · {fmt(s.slack_ms, 2)} ms</td>
          <td className="mono">{fmt(s.sw_share_pct, 0)}%</td><td className="mono">{s.bottleneck} {fmt(s.bottleneck_ms, 1)} ms</td><td className="mono">{fmt(s.latency_share_pct, 0)}%</td></tr>)}</tbody>
      </table>
      <div className="faint" style={{ fontSize: 12, margin: '6px 0' }}>SW 증가 허용 {m.growth_tolerance ? `×${fmt(m.growth_tolerance, 1)}` : '—'} (탐색 최대 ×{fmt(m.growth_tested_max, 1)}) · max–mean 편차 {fmt(m.stat_spread_ms, 1)} ms</div>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>{m.recommendations.map((r) => <li key={r}>{r}</li>)}</ul>
    </Card>
    <Card id="ax-comp" title="Compression BW 절감 (buffer별)" note="단독 적용 시 Δ · 합산 가능(port 독립)"><BufferSavings buffers={v.buffers} selected={rec?.compression ?? []} /></Card>
    <Card id="ax-dvfs" title="DVFS domain level" note="scenario별 level · +level은 전압↑ → power↑"><DomainLevels domains={v.domains} chosen={rec?.dvfs ?? {}} /></Card>
  </>
}
