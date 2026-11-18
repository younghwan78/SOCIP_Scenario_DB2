import { useState } from 'react'
import type { Ctx } from '../App'
import { api, type ResolvedVariant } from '../lib/api'
import { concurrencyApi, memberLabel, type ConcurrentResult } from '../lib/concurrency'
import { useAsync } from '../lib/route'
import { fmt, type TimingOptions } from '../lib/timingBudget'
import { TimingVerdictBadge } from './TimingVerdictBadge'

type Member = { scenario_id: string; variant_id: string }

/** S-06: this variant together with 1-3 others, composed from their own reports (no joint simulation). */
export function ConcurrentCard({ ctx, options, configProfileRef, blocked }: {
  ctx: Ctx; options: Partial<TimingOptions>; configProfileRef?: string | null
  /** why the composition cannot run with the page's current condition (members are composed at their own defaults) */
  blocked?: string | null
}) {
  const [others, setOthers] = useState<Member[]>([])
  const [pickScenario, setPickScenario] = useState('')
  const [pickVariant, setPickVariant] = useState('')
  const [result, setResult] = useState<ConcurrentResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const variantsQ = useAsync(() => (pickScenario ? api.variants(pickScenario).then((p) => p.items) : Promise.resolve([] as ResolvedVariant[])), [pickScenario])
  const add = () => {
    if (!pickScenario || !pickVariant || others.length >= 3) return
    const self = pickScenario === ctx.scenario && pickVariant === ctx.variant
    if (self || others.some((o) => o.scenario_id === pickScenario && o.variant_id === pickVariant)) return
    setOthers([...others, { scenario_id: pickScenario, variant_id: pickVariant }]); setResult(null)
  }
  const run = async () => {
    setBusy(true); setError(null)
    try {
      setResult(await concurrencyApi.compose([{ scenario_id: ctx.scenario, variant_id: ctx.variant }, ...others], options, configProfileRef))
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
        <span className="mono">{memberLabel(`${ctx.scenario}/${ctx.variant}`)}</span>
        {others.map((o, i) => (
          <span key={`${o.scenario_id}/${o.variant_id}`} className="badge">
            + {memberLabel(`${o.scenario_id}/${o.variant_id}`)}{' '}
            <button className="btn tb-mini" aria-label="제거" onClick={() => { setOthers(others.filter((_, j) => j !== i)); setResult(null) }}>×</button>
          </span>
        ))}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
        {others.length < 3 && <>
          <select aria-label="동시 실행 scenario" value={pickScenario} onChange={(e) => { setPickScenario(e.target.value); setPickVariant('') }}>
            <option value="">scenario 선택</option>
            {ctx.catalog.map((c) => <option key={c.scenario_id} value={c.scenario_id}>{c.scenario_id}</option>)}
          </select>
          <select aria-label="동시 실행 variant" value={pickVariant} onChange={(e) => setPickVariant(e.target.value)} disabled={!pickScenario}>
            <option value="">variant 선택</option>
            {(variantsQ.data ?? []).map((v) => <option key={v.id} value={v.id}>{v.id}</option>)}
          </select>
          <button className="btn tb-mini" onClick={add} disabled={!pickVariant}>추가</button>
        </>}
        <button className="btn tb-mini primary" onClick={run} disabled={!others.length || busy || !!blocked}>{busy ? '계산 중…' : '합성'}</button>
      </div>
      {blocked && <div className="faint" data-testid="concurrent-blocked">{blocked}</div>}
      {error && <div className="err">{error}</div>}
      {result && <ConcurrentView r={result} />}
    </div>
  )
}

export function ConcurrentView({ r }: { r: ConcurrentResult }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }} data-testid="concurrent-view">
      <div>
        <TimingVerdictBadge status={r.verdict.status} /> 합계 <b>{fmt(r.power.total_mw, 1)} mW</b>
        <span className="faint"> (각자 합 {fmt(r.power.sum_of_members_mw, 1)} + 공유 DVFS {fmt(r.power.dvfs_raise_mw, 1)}) · BW {fmt(r.bw.total_mbs, 0)} MB/s · CPU 부하 {fmt(r.cpu.load_core_eq, 2)} core</span>
      </div>
      <div className="table-x">
        <table>
          <thead><tr><th>member</th><th>판정</th><th>Total mW</th><th>CPU</th><th>HW</th><th>BW</th><th>공유 DVFS Δ</th><th>MB/s</th></tr></thead>
          <tbody>
            {r.members.map((m) => (
              <tr key={m.member}>
                <td className="mono">{memberLabel(m.member)}</td><td>{m.verdict ?? '—'}</td>
                <td>{fmt(m.total_mw, 1)}</td><td>{fmt(m.cpu_mw, 1)}</td><td>{fmt(m.hw_mw, 1)}</td><td>{fmt(m.bw_mw, 1)}</td>
                <td>{m.dvfs_raise_mw ? `+${fmt(m.dvfs_raise_mw, 1)}` : '—'}</td><td>{fmt(m.bw_mbs, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {r.shared_domains.map((d) => (
        <div key={d.group} className="faint">공유 DVFS {d.group}: {fmt(d.clock_mhz, 0)} MHz · {fmt(d.mv, 0)} mV ({d.members.map(memberLabel).join(', ')}){d.delta_mw ? ` · +${fmt(d.delta_mw, 1)} mW` : ''}</div>
      ))}
      {r.verdict.notes.map((n) => <div key={n} className="faint">{n}</div>)}
      <details className="faint"><summary>합성 범위 밖</summary>{r.limits.map((l) => <div key={l}>{l}</div>)}</details>
    </div>
  )
}
