import { useMemo } from 'react'
import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { fmt, timingApi, verdictChip, type EisMode, type Statistic, type TimingReport } from '../lib/timingBudget'
import { Card, ClockChart, Gantt, Intervals, PowerBw, SlotBudget, WhatIf } from '../components/TimingCharts'

const SCALES = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5]

export function TimingBudgetPage({ ctx }: { ctx: Ctx }) {
  const { scenario, variant } = ctx
  const statistic = (ctx.params.stat === 'mean' || ctx.params.stat === 'min' ? ctx.params.stat : 'max') as Statistic
  const eis = (ctx.params.eis === 'on' || ctx.params.eis === 'off' ? ctx.params.eis : 'auto') as EisMode
  const scale = SCALES.includes(Number(ctx.params.scale)) ? Number(ctx.params.scale) : 1.0
  const set = (k: string, v: string | undefined) => ctx.navigate(undefined, { [k]: v }, true)

  const q = useAsync(() => (variant ? timingApi.variant(scenario, variant, { statistic, eis, runtime_scale: scale }) : Promise.reject(new Error('variant를 선택하세요 (Ctrl K)'))), [scenario, variant, statistic, eis, scale])
  const wq = useAsync(() => (variant ? timingApi.variant(scenario, variant, { statistic: 'max', eis: 'auto', runtime_scale: 1, include_whatif: true }) : Promise.resolve(null)), [scenario, variant])
  const r = q.data?.report
  const whatif = wq.data?.report.whatif ?? []

  return (
    <div className="page tb-page">
      <div className="toolbar" style={{ flexWrap: 'wrap', gap: 14 }}>
        <Seg label="SW 통계" value={statistic} options={[['max', 'max'], ['mean', 'mean']]} onPick={(v) => set('stat', v === 'max' ? undefined : v)} />
        <Seg label="EIS" value={eis} options={[['auto', `auto${r ? (r.eis.auto ? ' (ON)' : ' (OFF)') : ''}`], ['on', 'ON'], ['off', 'OFF']]} onPick={(v) => set('eis', v === 'auto' ? undefined : v)} />
        <Seg label="차기 SW 증가" value={String(scale)} options={SCALES.map((s) => [String(s), `×${s.toFixed(1)}`])} onPick={(v) => set('scale', v === '1' ? undefined : v)} />
        <span className="grow" />
        {r && <span className={`badge ${verdictChip(r.verdict.status).cls}`} title={r.verdict.reasons.join('\n')}>{verdictChip(r.verdict.status).label}</span>}
        {r && <span className="chip">{fmt(r.fps, 0)} fps · P {fmt(r.period_ms, 3)} ms</span>}
        {r && <span className="chip" title={r.dvfs.tables.join(', ')}>DVFS {r.dvfs.applied ? r.dvfs.table_ref ?? 'custom' : '미연결'}</span>}
        <button className="btn" onClick={() => ctx.navigate('timing-fleet', {})}>전체 scenario →</button>
      </div>
      {q.error && <div className="err">{q.error}</div>}
      {q.loading && !r && <div className="empty">계산 중…</div>}
      {r && <Body r={r} ctx={ctx} whatif={whatif} whatLoading={wq.loading} current={{ statistic, eis: r.eis.on, scale }} />}
    </div>
  )
}

function Body({ r, whatif, whatLoading, current }: { r: TimingReport; ctx: Ctx; whatif: NonNullable<TimingReport['whatif']>; whatLoading: boolean; current: { statistic: string; eis: boolean; scale: number } }) {
  const st = useMemo(() => Object.fromEntries(r.stages.map((s) => [s.id, s])), [r])
  const nrtDriver = useMemo(() => {
    const rows = r.ips.filter((i) => i.stage === 'nrt' && i.rule_clock_mhz)
    return rows.sort((a, b) => b.set_clock_mhz / (b.rule_clock_mhz ?? 1) - a.set_clock_mhz / (a.rule_clock_mhz ?? 1))[0]
  }, [r])
  const iv = r.intervals
  const kpis = [
    { label: 'RT HW / 75% 예산', value: `${fmt(st.rt.hw_ms, 2)}`, unit: `/ ${fmt(st.rt.budget_ms, 2)} ms`, note: 'SW margin 25% rule', bad: st.rt.hw_ms > st.rt.budget_ms },
    { label: 'NRT SW (runtime+latency)', value: fmt(st.nrt.sw_ms, 2), unit: 'ms', note: `HW 예산 ${fmt(st.nrt.budget_ms, 2)} ms`, bad: !st.nrt.feasible },
    { label: 'Post SW (EIS 등)', value: fmt(st.post.sw_ms, 2), unit: 'ms', note: r.eis.on ? 'EIS ON' : 'EIS OFF', bad: !st.post.feasible },
    { label: `NRT clock${nrtDriver ? ` · ${nrtDriver.node.toUpperCase()}` : ''}`, value: fmt(nrtDriver?.set_clock_mhz, 0), unit: 'MHz', note: nrtDriver ? `rule ${fmt(nrtDriver.rule_clock_mhz, 0)} MHz · ×${fmt(nrtDriver.set_clock_mhz / (nrtDriver.rule_clock_mhz ?? 1), 2)}${nrtDriver.dvfs_level !== null ? ` · L${nrtDriver.dvfs_level}` : ''}` : '—', bad: false },
    { label: 'Preview / Video 간격', value: `${fmt(iv.preview.max_ms, 2)} / ${fmt(iv.video.max_ms, 2)}`, unit: 'ms', note: iv.ok ? `목표 ${fmt(iv.target_ms, 2)} ±${fmt(iv.tolerance * 100, 1)}% ✓` : '목표 이탈', bad: !iv.ok },
    { label: 'Power · BW', value: fmt(r.power.total_mw, 0), unit: 'mW', note: `CPU ${fmt(r.power.cpu_mw, 0)} · HW ${fmt(r.power.hw_mw, 0)} · BW ${fmt(r.power.bw_mw, 0)} · ${fmt(r.bw.total_mbs / 1000, 2)} GB/s`, bad: false },
  ]
  return <>
    <section className="tb-kpis" aria-label="요약">
      {kpis.map((k) => (
        <div key={k.label} className="panel tb-kpi">
          <div className="faint" style={{ fontSize: 12 }}>{k.label}</div>
          <div><span className="mono" style={{ fontSize: 20, fontWeight: 600, color: k.bad ? 'var(--del-text)' : 'var(--text)' }}>{k.value}</span> <span className="faint" style={{ fontSize: 12 }}>{k.unit}</span></div>
          <div className="faint" style={{ fontSize: 11 }}>{k.note}</div>
        </div>
      ))}
    </section>
    {r.verdict.reasons.length > 0 && <div className="err" style={{ fontSize: 13 }}>{r.verdict.reasons.slice(0, 4).map((x) => <div key={x}>{x}</div>)}</div>}
    <div className="tb-grid">
      <Card id="slot" title="① 1 frame 예산 — stage별 slot" note="stage는 memory로 pipeline · 각 stage가 1 frame 안에 끝나야 함" defaultWide><SlotBudget report={r} /></Card>
      <Card id="clock" title="⑤ IP별 필요 clock · DVFS level" note="RT·Output 25% rule, NRT·Post는 SW 반영 예산 · domain 정렬 반영"><ClockChart ips={r.ips} /></Card>
      <Card id="power" title="⑥ 예상 Power · BW" note="CPU(SW) / HW(IP별) / BW(HW·SW) 비중"><PowerBw report={r} /></Card>
      <Card id="gantt" title="② Pipeline timeline" note={`${r.timeline.length ? Math.max(...r.timeline.map((t) => t.frame)) + 1 : 0} frames · 명도 = frame`} defaultWide><Gantt report={r} /></Card>
      <Card id="interval" title="③ 출력 frame 간격 · pipeline latency" note="합격 기준 = 간격 · latency는 참고"><Intervals report={r} /></Card>
      <Card id="whatif" title="④ 차기 SW 증가 → NRT 필요 clock" note="NRT 예산 = period − SW(runtime+latency)">
        {whatLoading && !whatif.length ? <div className="empty">what-if 계산 중…</div> : <WhatIf rows={whatif} current={current} />}
      </Card>
    </div>
    {r.warnings.length > 0 && <details className="panel" style={{ padding: '8px 12px', fontSize: 12 }}><summary>경고 {r.warnings.length}</summary>{r.warnings.map((w) => <div key={w} className="faint">{w}</div>)}</details>}
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
