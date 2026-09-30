import { useEffect, useState } from 'react'
import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { fmt } from '../lib/timingBudget'
import { cpuApi, parseListMap, parseNumberMap, type CpuCase, type CpuWhatIf } from '../lib/cpu'
import { Card } from '../components/TimingCharts'
import { DataTable, type Column } from '../components/DataTable'

// Per-frame CPU placement / frequency what-if from a measured PMU profile.
// No time series: each task's measured cycles are split into core (IPC/f-dependent)
// and stall (memory time) parts and re-evaluated on the chosen cluster / OPP.
export function CpuWhatIfPage({ ctx }: { ctx: Ctx }) {
  void ctx
  const inputs = useAsync(() => cpuApi.inputs(), [])
  const [profile, setProfile] = useState('')
  const [target, setTarget] = useState('')
  const [base, setBase] = useState('')
  const [fps, setFps] = useState(30)
  const [growth, setGrowth] = useState(1.0)
  const [taskGrowth, setTaskGrowth] = useState('')
  const [candidates, setCandidates] = useState('')
  const [budgets, setBudgets] = useState('')
  const [utilCap, setUtilCap] = useState(0.8)
  const [pgEff, setPgEff] = useState(0.9)
  const [bwScale, setBwScale] = useState(1.0)
  const [result, setResult] = useState<CpuWhatIf | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [sel, setSel] = useState<number | null>(null)

  useEffect(() => {
    if (!inputs.data) return
    if (!profile && inputs.data.profiles[0]) setProfile(inputs.data.profiles[0].id)
    if (!target && inputs.data.topologies[0]) setTarget(inputs.data.topologies[0].id)
  }, [inputs.data]) // eslint-disable-line react-hooks/exhaustive-deps

  const run = async () => {
    setBusy(true); setError(null)
    try {
      const r = await cpuApi.whatif({
        cpu_profile_ref: profile, power_params_ref: target, base_power_params_ref: base || undefined, fps,
        default_growth: growth, growth: parseNumberMap(taskGrowth), candidates: parseListMap(candidates),
        budgets_ms: parseNumberMap(budgets), util_cap: utilCap, power_gating_eff: pgEff, cpu_bw_scale: bwScale,
      })
      setResult(r); setSel(r.cases[0]?.rank ?? null)
    } catch (e) { setError(String((e as Error).message ?? e)) } finally { setBusy(false) }
  }

  const topoOpts = inputs.data?.topologies ?? []
  const clusters = topoOpts.find((t) => t.id === target)?.clusters ?? []
  const picked: CpuCase | undefined = result?.cases.find((c) => c.rank === sel) ?? result?.base
  const cols: Column<CpuCase>[] = [
    { key: 'rank', label: '#', width: 50, align: 'right', sort: (c) => c.rank ?? 0, render: (c) => <span className="mono">{c.rank}{result?.pareto_ranks.includes(c.rank ?? -1) ? ' ★' : ''}</span> },
    { key: 'mw', label: 'CPU mW', width: 100, align: 'right', sort: (c) => c.total_mw, render: (c) => <span className="mono">{fmt(c.total_mw, 1)}</span> },
    { key: 'd', label: 'Δ vs base', width: 100, align: 'right', sort: (c) => c.delta_mw ?? 0, render: (c) => <span className="mono">{(c.delta_mw ?? 0) >= 0 ? '+' : ''}{fmt(c.delta_mw ?? 0, 1)}</span> },
    { key: 'ok', label: '판정', width: 70, sort: (c) => (c.feasible ? 1 : 0), render: (c) => <span className={`badge ${c.feasible ? 'v-ok' : 'v-fail'}`}>{c.feasible ? 'OK' : 'FAIL'}</span> },
    { key: 'slack', label: '최소 slack ms', width: 110, align: 'right', sort: (c) => c.min_slack_ms ?? 1e9, render: (c) => <span className="mono">{c.min_slack_ms === null ? '—' : fmt(c.min_slack_ms, 2)}</span> },
    { key: 'bw', label: 'CPU BW MB/s', width: 110, align: 'right', sort: (c) => c.cpu_bw_mbs, render: (c) => <span className="mono">{fmt(c.cpu_bw_mbs, 0)}</span> },
    { key: 'pl', label: '배치', width: 420, render: (c) => <span className="mono faint">{Object.entries(c.placement).map(([t, cl]) => `${t}→${cl}`).join('  ')}</span> },
  ]
  const field = (label: string, el: JSX.Element, hint?: string) => <label className="cpu-f" title={hint}><span className="faint">{label}</span>{el}</label>
  return (
    <div className="page tb-page">
      <div className="toolbar cpu-form" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        {field('실측 profile', <select value={profile} onChange={(e) => setProfile(e.target.value)}>{(inputs.data?.profiles ?? []).map((p) => <option key={p.id} value={p.id}>{p.id}</option>)}</select>, 'cpu.*_pf observation이 있는 측정 evidence')}
        {field('대상 topology', <select value={target} onChange={(e) => setTarget(e.target.value)}>{topoOpts.map((t) => <option key={t.id} value={t.id}>{t.id} ({t.soc_ref})</option>)}</select>)}
        {field('측정 SoC topology', <select value={base} onChange={(e) => setBase(e.target.value)}><option value="">대상과 같음</option>{topoOpts.map((t) => <option key={t.id} value={t.id}>{t.id}</option>)}</select>, '다른 과제에서 측정한 profile이면 그 SoC topology')}
        {field('fps', <input type="number" value={fps} min={1} onChange={(e) => setFps(Number(e.target.value))} style={{ width: 70 }} />)}
        {field('SW growth', <input type="number" step={0.05} value={growth} onChange={(e) => setGrowth(Number(e.target.value))} style={{ width: 70 }} />, 'instruction 배율 (전체)')}
        {field('task별 growth', <input value={taskGrowth} placeholder="eis=1.3" onChange={(e) => setTaskGrowth(e.target.value)} style={{ width: 130 }} />)}
        {field('배치 후보', <input value={candidates} placeholder={clusters.length ? `eis=${clusters.slice(0, 2).join(',')}` : 'task=CL1,CL2'} onChange={(e) => setCandidates(e.target.value)} style={{ width: 260 }} />, 'task=cluster,cluster; …')}
        {field('budget ms', <input value={budgets} placeholder="eis=6; post_irta=8" onChange={(e) => setBudgets(e.target.value)} style={{ width: 160 }} />, 'task별 frame당 허용 시간 (Timing Budget의 SW budget)')}
        {field('util cap', <input type="number" step={0.05} value={utilCap} onChange={(e) => setUtilCap(Number(e.target.value))} style={{ width: 60 }} />)}
        {field('PG 효율', <input type="number" step={0.05} value={pgEff} onChange={(e) => setPgEff(Number(e.target.value))} style={{ width: 60 }} />, 'idle core의 power gating 비율')}
        {field('CPU BW 배율', <input type="number" step={0.05} value={bwScale} onChange={(e) => setBwScale(Number(e.target.value))} style={{ width: 60 }} />, 'L3/SLC 변화 등에 따른 DRAM traffic 배율')}
        <button className="btn primary" disabled={busy || !profile || !target} onClick={run}>{busy ? '계산 중…' : '계산'}</button>
      </div>
      {inputs.error && <div className="err">{inputs.error}</div>}
      {inputs.data && (!inputs.data.profiles.length || !inputs.data.topologies.length) && <div className="empty">CPU profile이 있는 측정 evidence와 cpu topology가 있는 power_model_params가 필요합니다 (docs/guides/measurement/cpu-profile-import-ko.md).</div>}
      {error && <div className="err">{error}</div>}
      {result && <>
        {result.warnings.length > 0 && <details className="panel" style={{ padding: '8px 12px', fontSize: 12 }}><summary>경고 {result.warnings.length}</summary>{result.warnings.map((w) => <div key={w} className="faint">{w}</div>)}</details>}
        <section className="tb-kpis" aria-label="요약">
          {([['측정 placement · 측정 DVFS', result.measured_mw === null ? '—' : `${fmt(result.measured_mw, 1)} mW`, 'profile의 residency · gating 그대로'],
             ['측정 placement · 이상적 DVFS', `${fmt(result.base.total_mw, 1)} mW`, '조건 만족 최소 전력 OPP'],
             ['최저 case', result.cases[0] ? `${fmt(result.cases[0].total_mw, 1)} mW` : '—', result.cases[0]?.feasible ? 'OK' : '조건 미충족'],
             ['case 수', String(result.case_count), `Pareto ${result.pareto_ranks.length}개 (★)`]] as const).map(([l, v, n]) =>
            <div key={l} className="panel tb-kpi"><div className="faint" style={{ fontSize: 12 }}>{l}</div><div className="mono" style={{ fontSize: 20, fontWeight: 600 }}>{v}</div><div className="faint" style={{ fontSize: 11 }}>{n}</div></div>)}
        </section>
        <div className="tb-grid">
          <Card id="cpu-cases" title="배치 case" note="행 클릭 = cluster 상세 · ★ = power–slack Pareto" defaultWide minHeight={200}>
            <div className="table-x"><DataTable id="cpu.cases" columns={cols} rows={result.cases} rowKey={(c) => String(c.rank)}
              onRowClick={(c) => setSel(c.rank ?? null)} rowClass={(c) => (c.rank === sel ? 'selected' : '')} /></div>
          </Card>
          {picked && <Card id="cpu-detail" title={`cluster 상세 — case ${picked.rank ?? 'base'}`} note="OPP = 조건 만족 최소 전력" defaultWide>
            <table className="grid"><thead><tr><th>cluster</th><th style={{ textAlign: 'right' }}>MHz</th><th style={{ textAlign: 'right' }}>mV</th><th style={{ textAlign: 'right' }}>util</th><th style={{ textAlign: 'right' }}>dynamic</th><th style={{ textAlign: 'right' }}>static</th><th style={{ textAlign: 'right' }}>합계 mW</th><th>task (ms/frame)</th></tr></thead>
              <tbody>{Object.entries(picked.clusters).map(([name, c]) => (
                <tr key={name} className={c.feasible === false ? 'v-fail' : ''}><td className="mono">{name}</td><td className="mono" style={{ textAlign: 'right' }}>{fmt(c.mhz, 0)}</td><td className="mono" style={{ textAlign: 'right' }}>{fmt(c.mv, 0)}</td>
                  <td className="mono" style={{ textAlign: 'right' }}>{fmt(c.util * 100, 1)}%</td><td className="mono" style={{ textAlign: 'right' }}>{fmt(c.dynamic_mw, 1)}</td><td className="mono" style={{ textAlign: 'right' }}>{fmt(c.static_mw, 1)}</td>
                  <td className="mono" style={{ textAlign: 'right' }}>{fmt(c.total_mw, 1)}</td><td className="mono faint">{Object.entries(c.tasks_ms).map(([t, ms]) => `${t} ${fmt(ms, 2)}`).join(' · ') || '—'}</td></tr>))}
                {picked.dsu && <tr><td className="mono">DSU</td><td /><td /><td className="mono" style={{ textAlign: 'right' }}>{fmt(picked.dsu.active_ratio * 100, 1)}%</td><td className="mono" style={{ textAlign: 'right' }}>{fmt(picked.dsu.dynamic_mw, 1)}</td><td className="mono" style={{ textAlign: 'right' }}>{fmt(picked.dsu.static_mw, 1)}</td><td className="mono" style={{ textAlign: 'right' }}>{fmt(picked.dsu.total_mw, 1)}</td><td /></tr>}
              </tbody></table>
          </Card>}
        </div>
      </>}
    </div>
  )
}
