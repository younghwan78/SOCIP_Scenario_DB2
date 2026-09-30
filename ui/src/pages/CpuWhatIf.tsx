import { useEffect, useMemo, useState } from 'react'
import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { fmt } from '../lib/timingBudget'
import { caseCount, caseParts, cpuApi, type CpuCase, type CpuWhatIf } from '../lib/cpu'
import { Card } from '../components/TimingCharts'
import { DataTable, type Column } from '../components/DataTable'
import { PowerDeltaTable, PowerStack, type PowerRow } from '../components/PowerModelCharts'

type TaskOpt = { clusters: string[]; budget: string; growth: string }

// CPU placement / frequency what-if from a measured per-frame PMU profile.
// ① what to start from → ② conditions → ③ which cluster each task may run on,
// then compare every placement against the measured one (★).
export function CpuWhatIfPage({ ctx }: { ctx: Ctx }) {
  void ctx
  const inputs = useAsync(() => cpuApi.inputs(), [])
  const [profile, setProfile] = useState('')
  const [target, setTarget] = useState('')
  const [base, setBase] = useState('')
  const [fps, setFps] = useState(30)
  const [growth, setGrowth] = useState(1.0)
  const [utilCap, setUtilCap] = useState(0.8)
  const [pgEff, setPgEff] = useState(0.9)
  const [bwScale, setBwScale] = useState(1.0)
  const [opts, setOpts] = useState<Record<string, TaskOpt>>({})
  const [result, setResult] = useState<CpuWhatIf | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [sel, setSel] = useState<string>('base')

  const prof = inputs.data?.profiles.find((p) => p.id === profile)
  const topo = inputs.data?.topologies.find((t) => t.id === target)
  const clusters = topo?.clusters ?? []
  const tasks = prof?.tasks ?? []
  const measuredOn = (task: string) => tasks.find((t) => t.task === task)?.cluster ?? ''

  useEffect(() => {
    if (!inputs.data) return
    if (!profile && inputs.data.profiles[0]) setProfile(inputs.data.profiles[0].id)
    if (!target && inputs.data.topologies[0]) setTarget(inputs.data.topologies[0].id)
  }, [inputs.data]) // eslint-disable-line react-hooks/exhaustive-deps
  // default matrix: every task stays where it was measured (if that cluster exists on the target)
  useEffect(() => {
    setOpts(Object.fromEntries(tasks.map((t) => [t.task, { clusters: clusters.includes(t.cluster) ? [t.cluster] : [], budget: '', growth: '' }])))
    setResult(null)
  }, [profile, target]) // eslint-disable-line react-hooks/exhaustive-deps

  const candidates = useMemo(() => Object.fromEntries(Object.entries(opts).filter(([, o]) => o.clusters.length > 0).map(([t, o]) => [t, o.clusters])), [opts])
  const nCases = caseCount(candidates)
  const toggle = (task: string, cl: string) => setOpts((m) => {
    const o = m[task] ?? { clusters: [], budget: '', growth: '' }
    const next = o.clusters.includes(cl) ? o.clusters.filter((c) => c !== cl) : [...o.clusters, cl]
    return { ...m, [task]: { ...o, clusters: next } }
  })
  const setField = (task: string, k: 'budget' | 'growth', v: string) => setOpts((m) => ({ ...m, [task]: { ...(m[task] ?? { clusters: [], budget: '', growth: '' }), [k]: v } }))
  const allClusters = (on: boolean) => setOpts((m) => Object.fromEntries(Object.entries(m).map(([t, o]) => [t, { ...o, clusters: on ? [...clusters] : clusters.includes(measuredOn(t)) ? [measuredOn(t)] : [] }])))

  const run = async () => {
    setBusy(true); setError(null)
    const numOf = (k: 'budget' | 'growth') => Object.fromEntries(Object.entries(opts).filter(([, o]) => o[k] !== '' && Number.isFinite(Number(o[k]))).map(([t, o]) => [t, Number(o[k])]))
    try {
      const r = await cpuApi.whatif({
        cpu_profile_ref: profile, power_params_ref: target, base_power_params_ref: base || undefined, fps,
        default_growth: growth, growth: numOf('growth'), candidates, budgets_ms: numOf('budget'),
        util_cap: utilCap, power_gating_eff: pgEff, cpu_bw_scale: bwScale,
      })
      setResult(r); setSel(r.cases[0] ? String(r.cases[0].rank) : 'base')
    } catch (e) { setError(String((e as Error).message ?? e)) } finally { setBusy(false) }
  }

  const caseById = (id: string): CpuCase | undefined => (id === 'base' ? result?.base : result?.cases.find((c) => String(c.rank) === id))
  const moved = (c: CpuCase) => Object.entries(c.placement).filter(([t, cl]) => cl !== result?.base.placement[t]).map(([t, cl]) => `${t}→${cl}`)
  const same = result?.cases.find((c) => moved(c).length === 0)
  const rows: PowerRow[] = result ? [
    { id: 'base', label: same ? `측정 배치 (=#${same.rank})` : '측정 배치', parts: caseParts(result.base), sub: `이상적 DVFS · slack ${result.base.min_slack_ms === null ? '—' : fmt(result.base.min_slack_ms, 1)} ms` },
    ...result.cases.filter((c) => moved(c).length > 0).slice(0, 12).map((c) => ({
      id: String(c.rank), label: `#${c.rank} ${moved(c).join(' ')}`, parts: caseParts(c),
      sub: `${c.feasible ? '조건 만족' : '조건 미충족'} · slack ${c.min_slack_ms === null ? '—' : fmt(c.min_slack_ms, 1)} ms · BW ${fmt(c.cpu_bw_mbs, 0)} MB/s`,
    })),
  ] : []
  const picked = caseById(sel)
  const best = result?.cases.find((c) => c.feasible)
  const cols: Column<CpuCase>[] = [
    { key: 'rank', label: '#', width: 56, align: 'right', sort: (c) => c.rank ?? 0, render: (c) => <span className="mono">{c.rank}{result?.pareto_ranks.includes(c.rank ?? -1) ? ' ★' : ''}</span> },
    { key: 'mw', label: 'CPU mW', width: 90, align: 'right', sort: (c) => c.total_mw, render: (c) => <span className="mono">{fmt(c.total_mw, 1)}</span> },
    { key: 'd', label: '측정 배치 대비', width: 110, align: 'right', sort: (c) => c.delta_mw ?? 0, render: (c) => <span className={`mono ${(c.delta_mw ?? 0) < 0 ? 'pm-down' : (c.delta_mw ?? 0) > 0 ? 'pm-up' : ''}`}>{(c.delta_mw ?? 0) >= 0 ? '+' : ''}{fmt(c.delta_mw ?? 0, 1)}</span> },
    { key: 'ok', label: '판정', width: 80, sort: (c) => (c.feasible ? 1 : 0), render: (c) => <span className={`badge ${c.feasible ? 'v-ok' : 'v-fail'}`}>{c.feasible ? '만족' : '미충족'}</span> },
    { key: 'slack', label: '최소 slack', width: 90, align: 'right', sort: (c) => c.min_slack_ms ?? 1e9, render: (c) => <span className="mono">{c.min_slack_ms === null ? '—' : `${fmt(c.min_slack_ms, 2)} ms`}</span> },
    { key: 'bw', label: 'CPU BW', width: 100, align: 'right', sort: (c) => c.cpu_bw_mbs, render: (c) => <span className="mono">{fmt(c.cpu_bw_mbs, 0)} MB/s</span> },
    { key: 'pl', label: '측정 배치에서 바뀐 것', width: 360, render: (c) => <span className="mono faint">{moved(c).join('  ') || '(측정 배치 그대로)'}</span> },
  ]
  const tile = (label: string, value: string, note: string, tone = '') =>
    <div key={label} className="panel tb-kpi"><div className="faint" style={{ fontSize: 12 }}>{label}</div><div className={`mono ${tone}`} style={{ fontSize: 20, fontWeight: 600 }}>{value}</div><div className="faint" style={{ fontSize: 11 }}>{note}</div></div>

  return (
    <div className="page tb-page">
      <p className="cpu-help">측정한 CPU profile(task별 cycle · stall · bus)을 기준으로, task를 어느 cluster에서 어떤 주파수로 돌릴 때 CPU 전력과 timing 여유가 어떻게 달라지는지 비교합니다. 시계열 없이 frame 단위로 계산하며 ★ = 측정 배치입니다.</p>
      {inputs.error && <div className="err">{inputs.error}</div>}
      {inputs.data && (!inputs.data.profiles.length || !inputs.data.topologies.length) && <div className="empty">CPU profile이 있는 측정 evidence와 cpu topology가 있는 power_model_params가 필요합니다 (docs/guides/measurement/cpu-profile-import-ko.md).</div>}
      <div className="tb-grid">
        <Card id="cpu-in" title="① 기준" note="측정 profile · 적용할 SoC">
          <div className="cpu-step" style={{ display: 'grid', gap: 8 }}>
            <label className="cpu-f"><span className="faint">측정 profile</span>
              <select value={profile} onChange={(e) => setProfile(e.target.value)}>{(inputs.data?.profiles ?? []).map((p) => <option key={p.id} value={p.id}>{p.variant_ref ?? p.id} · {p.id}</option>)}</select></label>
            <label className="cpu-f"><span className="faint">적용할 SoC CPU 구성</span>
              <select value={target} onChange={(e) => setTarget(e.target.value)}>{(inputs.data?.topologies ?? []).map((t) => <option key={t.id} value={t.id}>{t.soc_ref} · {t.clusters.join(' / ')}</option>)}</select></label>
            <label className="cpu-f" title="다른 과제에서 측정한 profile이면, 측정한 SoC의 CPU 구성을 고르세요 (core type으로 대응)"><span className="faint">profile을 측정한 SoC</span>
              <select value={base} onChange={(e) => setBase(e.target.value)}><option value="">적용할 SoC와 같음</option>{(inputs.data?.topologies ?? []).map((t) => <option key={t.id} value={t.id}>{t.soc_ref} · {t.id}</option>)}</select></label>
          </div>
        </Card>
        <Card id="cpu-cond" title="② 조건" note="SW 증가 · DVFS 판정 기준">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 8 }}>
            <label className="cpu-f"><span className="faint">fps</span><input type="number" value={fps} min={1} onChange={(e) => setFps(Number(e.target.value))} /></label>
            <label className="cpu-f" title="차기 과제 SW instruction 증가 배율 (전체)"><span className="faint">SW 증가 배율</span><input type="number" step={0.05} value={growth} onChange={(e) => setGrowth(Number(e.target.value))} /></label>
            <label className="cpu-f" title="cluster 전체 사용률 상한 (core 수 × frame 기준)"><span className="faint">사용률 상한</span><input type="number" step={0.05} value={utilCap} onChange={(e) => setUtilCap(Number(e.target.value))} /></label>
            <label className="cpu-f" title="idle core가 power gating되는 비율"><span className="faint">idle power gating</span><input type="number" step={0.05} value={pgEff} onChange={(e) => setPgEff(Number(e.target.value))} /></label>
            <label className="cpu-f" title="L3/SLC 변경 등으로 DRAM까지 가는 CPU traffic 배율"><span className="faint">CPU BW 배율</span><input type="number" step={0.05} value={bwScale} onChange={(e) => setBwScale(Number(e.target.value))} /></label>
          </div>
        </Card>
        <Card id="cpu-matrix" title="③ 배치 후보 · task budget" note="체크 = 그 cluster에서 실행해 봄 · 파란 칸 = 측정 위치" defaultWide
          actions={<><button className="btn tb-mini" onClick={() => allClusters(false)}>측정 배치만</button><button className="btn tb-mini" onClick={() => allClusters(true)}>모든 cluster</button></>}>
          {tasks.length ? <div className="table-x"><table className="grid cpu-matrix">
            <thead><tr><th>task (측정 위치)</th>{clusters.map((c) => <th key={c}>{c}</th>)}<th title="frame당 허용 시간 (Timing Budget의 SW budget)">budget ms</th><th title="이 task만의 SW 증가 배율">증가 배율</th></tr></thead>
            <tbody>{tasks.map((t) => (
              <tr key={t.task}><td className="mono">{t.task} <span className="faint">({t.cluster})</span></td>
                {clusters.map((c) => <td key={c} className={c === t.cluster ? 'measured' : ''}><input type="checkbox" aria-label={`${t.task} on ${c}`} checked={opts[t.task]?.clusters.includes(c) ?? false} onChange={() => toggle(t.task, c)} /></td>)}
                <td><input style={{ width: 64 }} value={opts[t.task]?.budget ?? ''} placeholder="—" onChange={(e) => setField(t.task, 'budget', e.target.value)} /></td>
                <td><input style={{ width: 56 }} value={opts[t.task]?.growth ?? ''} placeholder={String(growth)} onChange={(e) => setField(t.task, 'growth', e.target.value)} /></td></tr>))}
            </tbody></table></div> : <div className="empty">profile에 task별 cycle 정보가 없습니다.</div>}
          <div className="toolbar" style={{ marginTop: 8 }}>
            <span className="faint" style={{ fontSize: 12 }}>{nCases}개 배치를 비교합니다{nCases > 5000 ? ' — 5000개 초과, 후보를 줄이세요' : ''}</span><span className="grow" />
            <button className="btn primary" disabled={busy || !profile || !target || nCases > 5000} onClick={run}>{busy ? '계산 중…' : '비교 계산'}</button>
          </div>
        </Card>
      </div>
      {error && <div className="err">{error}</div>}
      {result && <>
        {result.warnings.length > 0 && <details className="panel" style={{ padding: '8px 12px', fontSize: 12 }}><summary>참고 {result.warnings.length}</summary>{result.warnings.map((w) => <div key={w} className="faint">{w}</div>)}</details>}
        <section className="tb-kpis" aria-label="요약">
          {tile('측정 배치 · 측정 DVFS', result.measured_mw === null ? '—' : `${fmt(result.measured_mw, 1)} mW`, '측정 주파수 residency · gating 그대로')}
          {tile('측정 배치 · 최적 DVFS', `${fmt(result.base.total_mw, 1)} mW`, '조건 만족하는 최소 전력 OPP')}
          {tile('최저 전력 배치', best ? `${fmt(best.total_mw, 1)} mW` : '없음', best ? `측정 배치 대비 ${(best.delta_mw ?? 0) >= 0 ? '+' : ''}${fmt(best.delta_mw ?? 0, 1)} mW` : '조건 만족 배치 없음', best && (best.delta_mw ?? 0) < 0 ? 'pm-down' : '')}
          {tile('비교한 배치', String(result.case_count), `★ power–slack 최적 ${result.pareto_ranks.length}개`)}
        </section>
        <div className="tb-grid">
          <Card id="cpu-stack" title="배치별 CPU 전력 구성" note="막대 = cluster별 전력(동적+정적) · 점선 = ★ 측정 배치 · 행 클릭 = 아래에서 비교" defaultWide minHeight={200}>
            <PowerStack rows={rows} selected={sel} onPick={setSel} />
          </Card>
          {picked && sel !== 'base' && <Card id="cpu-vs" title={`★ 측정 배치 vs #${picked.rank}`} note="어느 cluster에서 전력이 늘고 줄었나" defaultWide>
            <PowerDeltaTable rows={[rows[0], { id: sel, label: `#${picked.rank}`, parts: caseParts(picked) }]} />
            <table className="grid pm-table" style={{ marginTop: 8 }}>
              <thead><tr><th>task</th><th>측정 배치</th><th>#{picked.rank}</th><th style={{ textAlign: 'right' }}>시간 ms (측정→변경)</th><th style={{ textAlign: 'right' }}>budget</th><th style={{ textAlign: 'right' }}>slack</th></tr></thead>
              <tbody>{Object.keys(picked.placement).map((t) => {
                const b = result.base.placement[t], c = picked.placement[t]
                const tb = result.base.clusters[b]?.tasks_ms[t], tc = picked.clusters[c]?.tasks_ms[t]
                const slack = picked.slack_ms[t]
                return <tr key={t} className={b !== c ? 'selected' : ''}><td className="mono">{t}</td><td className="mono">{b} @{fmt(result.base.clusters[b]?.mhz, 0)}</td><td className="mono">{c} @{fmt(picked.clusters[c]?.mhz, 0)}</td>
                  <td className="mono" style={{ textAlign: 'right' }}>{fmt(tb, 2)} → {fmt(tc, 2)}</td>
                  <td className="mono" style={{ textAlign: 'right' }}>{opts[t]?.budget || '—'}</td>
                  <td className={`mono ${slack === undefined ? '' : slack < 0.5 ? 'pm-up' : 'pm-down'}`} style={{ textAlign: 'right' }}>{slack === undefined ? '—' : fmt(slack, 2)}</td></tr>
              })}</tbody></table>
          </Card>}
          <Card id="cpu-cases" title="전체 배치 표" note="정렬 가능 · ★ = power–slack 최적" defaultWide minHeight={160}>
            <details><summary className="faint" style={{ fontSize: 12 }}>{result.case_count}개 배치 펼치기</summary>
              <div className="table-x"><DataTable id="cpu.cases" columns={cols} rows={result.cases} rowKey={(c) => String(c.rank)}
                onRowClick={(c) => setSel(String(c.rank))} rowClass={(c) => (String(c.rank) === sel ? 'selected' : '')} /></div></details>
          </Card>
        </div>
      </>}
    </div>
  )
}
