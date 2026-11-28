import { useState } from 'react'
import type { Ctx } from '../App'
import { api, type ResolvedVariant } from '../lib/api'
import { concurrencyApi, memberLabel, type ConcurrentResult } from '../lib/concurrency'
import { useAsync } from '../lib/route'
import { fmt, type TimingOptions } from '../lib/timingBudget'
import { TimingVerdictBadge } from './TimingVerdictBadge'

type Member = { scenario_id: string; variant_id: string }

/** X-14: a short condition summary of a variant for the picker (first few design conditions). */
export function conditionSummary(dc: Record<string, unknown> | null | undefined, n = 3): string {
  return Object.entries(dc ?? {}).filter(([, v]) => v != null && v !== '' && typeof v !== 'object').slice(0, n).map(([k, v]) => `${k} ${String(v)}`).join(' · ')
}

/** X-14: common companions of a concurrent run (another use case at the same time); each adds that scenario's
 * default variant. Matched on the scenario id so a ported project with the same naming gets them too. */
const COMPANIONS: { label: string; match: RegExp }[] = [
  { label: '음성 통화', match: /call-voice/ }, { label: '녹화', match: /cam-recording-e/ },
  { label: 'game', match: /game-play/ }, { label: '음악 재생', match: /aud-mp3/ },
]
export function companionPresets(catalog: { scenario_id: string; scenario_name: string; default_variant_id?: string | null }[], self: string): { label: string; member: Member; name: string }[] {
  return COMPANIONS.flatMap((c) => {
    const s = catalog.find((x) => c.match.test(x.scenario_id) && x.scenario_id !== self && x.default_variant_id)
    return s ? [{ label: c.label, name: s.scenario_name, member: { scenario_id: s.scenario_id, variant_id: s.default_variant_id! } }] : []
  })
}

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
  const addMember = (m: Member) => {
    if (others.length >= 3) return
    const self = m.scenario_id === ctx.scenario && m.variant_id === ctx.variant
    if (self || others.some((o) => o.scenario_id === m.scenario_id && o.variant_id === m.variant_id)) return
    setOthers([...others, m]); setResult(null)
  }
  const add = () => { if (pickScenario && pickVariant) addMember({ scenario_id: pickScenario, variant_id: pickVariant }) }
  const scnName = (sid: string) => ctx.catalog.find((c) => c.scenario_id === sid)?.scenario_name ?? sid
  const presets = companionPresets(ctx.catalog, ctx.scenario)
  const run = async () => {
    setBusy(true); setError(null)
    try {
      setResult(await concurrencyApi.compose([{ scenario_id: ctx.scenario, variant_id: ctx.variant }, ...others], options, configProfileRef))
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
        <span title={`${ctx.scenario}/${ctx.variant}`}>{scnName(ctx.scenario)} <span className="mono faint">{ctx.variant}</span></span>
        {others.map((o, i) => (
          <span key={`${o.scenario_id}/${o.variant_id}`} className="badge">
            + <span title={`${o.scenario_id}/${o.variant_id}`}>{scnName(o.scenario_id)} <span className="mono">{o.variant_id}</span></span>{' '}
            <button className="btn tb-mini" aria-label="제거" onClick={() => { setOthers(others.filter((_, j) => j !== i)); setResult(null) }}>×</button>
          </span>
        ))}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
        {others.length < 3 && <>
          <select aria-label="동시 실행 scenario" value={pickScenario} onChange={(e) => { setPickScenario(e.target.value); setPickVariant('') }}>
            <option value="">scenario 선택</option>
            {ctx.catalog.map((c) => <option key={c.scenario_id} value={c.scenario_id} title={c.scenario_id}>{c.scenario_name}</option>)}
          </select>
          <select aria-label="동시 실행 variant" value={pickVariant} onChange={(e) => setPickVariant(e.target.value)} disabled={!pickScenario}>
            <option value="">variant 선택</option>
            {(variantsQ.data ?? []).map((v) => { const sum = conditionSummary(v.design_conditions); return <option key={v.id} value={v.id} title={v.id}>{v.id}{sum ? ` — ${sum}` : ''}</option> })}
          </select>
          <button className="btn tb-mini" onClick={add} disabled={!pickVariant}>추가</button>
          {presets.length > 0 && <span className="faint t-caption" data-testid="concurrent-presets">자주 쓰는 조합:{' '}
            {presets.map((p) => <button key={p.label} className="btn tb-mini" title={`${p.name} · ${p.member.variant_id} (catalog 기본 = id 순 첫 variant)`} onClick={() => addMember(p.member)}>+ {p.label}</button>)}</span>}
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
