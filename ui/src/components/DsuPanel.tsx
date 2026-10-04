// CPU what-if: DSU <-> cluster clock coupling as an editable architecture assumption.
// Edits are evaluated client-side on the returned cases (no new sweep); "서버에 적용" reruns the full sweep with it.
import { useMemo, useState } from 'react'
import type { CpuSweep, SweepCase } from '../lib/cpu'
import { fmt } from '../lib/timingBudget'
import {
  applyDsu, expandVote, monotone, proportionalVote, shiftVote, summarize, voteYaml,
  type DsuModelInfo, type DsuParams, type DsuPolicy, type VoteTable,
} from '../lib/dsu'

const MODE_LABEL: Record<DsuPolicy['mode'], string> = {
  vote: 'vote 표 (busy cluster 최대)', proportional: '비례 (가장 바쁜 cluster f/fmax)', measured: '측정 residency 고정', fixed: '고정 MHz',
}

export interface DsuEval { refMw: number; bestMw: number | null; deltaMw: number | null; refDsuMhz: number | null; bestDsuMhz: number | null; bestKey: string }

const sweepKey = (c: SweepCase | null) => (c ? Object.entries(c.knobs).filter(([, o]) => o.kind !== 'measured').map(([t, o]) => `${t}→${o.clusters?.join('/') ?? o.value ?? o.kind}`).join(' · ') || 'EAS 기본' : '—')
/** DsuPanel evaluator for an automatic-sweep response */
export function sweepEvaluator(raw: CpuSweep) {
  return (pol: DsuPolicy | null): DsuEval => { const s = summarize(pol ? applyDsu(raw, pol) : raw); return { ...s, bestKey: sweepKey(s.best) } }
}

export function DsuPanel({ params: p, server, measured, check, evalPolicy, candidates, exp, setExp, onApply, applied }: {
  params: DsuParams | null | undefined
  server: DsuModelInfo | null | undefined
  measured?: Record<string, number> | null
  check?: { measured_mean_mhz: number; model_mhz: number | null } | null
  /** power summary of the returned candidates under a rule (null = server result) */
  evalPolicy: (pol: DsuPolicy | null) => DsuEval
  candidates: number
  exp: DsuPolicy | null
  setExp: (p: DsuPolicy | null) => void
  /** rerun with this rule (null = topology / auto) */
  onApply: (p: DsuPolicy | null) => void
  applied: DsuPolicy | null
}) {
  const [saved, setSaved] = useState<{ A?: DsuPolicy; B?: DsuPolicy }>({})
  const [copied, setCopied] = useState(false)
  const startVote = (): VoteTable => (p ? expandVote(server?.vote ?? exp?.vote ?? proportionalVote(p), p) : {})
  const cur: DsuPolicy = exp ?? (server ? { mode: server.mode, vote: server.vote, fixed_mhz: server.fixed_mhz } : { mode: 'proportional' })
  const rows = useMemo(() => {
    if (!p) return []
    const out: { key: string; label: string; pol: DsuPolicy | null }[] = [{ key: 'srv', label: `서버 결과 (${server ? MODE_LABEL[server.mode] : '—'})`, pol: null }]
    if (exp) out.push({ key: 'exp', label: '실험 (편집 중)', pol: exp })
    if (exp?.mode === 'vote' && exp.vote) {
      out.push({ key: 'lo', label: '실험 · 전체 −1 step (낙관)', pol: { mode: 'vote', vote: shiftVote(exp.vote, p, -1) } })
      out.push({ key: 'hi', label: '실험 · 전체 +1 step (비관)', pol: { mode: 'vote', vote: shiftVote(exp.vote, p, +1) } })
    }
    if (saved.A) out.push({ key: 'A', label: '정책 A', pol: saved.A })
    if (saved.B) out.push({ key: 'B', label: '정책 B', pol: saved.B })
    return out.map((r) => ({ ...r, s: evalPolicy(r.pol) }))
  }, [evalPolicy, exp, saved, p, server])
  if (!p) return <div className="faint" style={{ fontSize: 12 }}>topology에 DSU OPP가 없어 DSU 가정을 다룰 수 없습니다.</div>
  const bestKey = (s: DsuEval) => s.bestKey
  const baseBest = rows[0] ? bestKey(rows[0].s) : ''
  const vote = cur.mode === 'vote' ? expandVote(cur.vote ?? {}, p) : null
  const setCell = (cl: string, i: number, d: number) => {
    const t = { ...(vote ?? startVote()) }
    const pts = t[cl].map((x, j) => (j === i ? [x[0], d] : x) as [number, number])
    t[cl] = monotone(i === 0 ? pts : pts.map((x, j) => (j < i ? [x[0], Math.min(x[1], d)] : x) as [number, number]))
    setExp({ mode: 'vote', vote: t })
  }
  const same = (a: DsuPolicy | null, b: DsuPolicy | null) => JSON.stringify(a) === JSON.stringify(b)

  return (
    <div className="dsu-panel">
      <div className="toolbar" style={{ gap: 10, fontSize: 12, flexWrap: 'wrap' }}>
        <span className="faint">서버 적용 규칙</span>
        <span className="badge">{server ? `${MODE_LABEL[server.mode]}${server.source ? ` · ${server.source}` : ''}` : '—'}</span>
        {check && <span className="faint" title="측정 배치에서 모델 DSU MHz vs 측정 평균 — 가정 확인용">측정 평균 {fmt(check.measured_mean_mhz, 0)} MHz · 모델 {check.model_mhz ?? '—'} MHz</span>}
        <span className="grow" />
        <label className="cpu-f" style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}><span className="faint">실험 규칙</span>
          <select value={exp ? exp.mode : ''} aria-label="DSU 실험 규칙" onChange={(e) => {
            const m = e.target.value as DsuPolicy['mode'] | ''
            setExp(m === '' ? null : m === 'vote' ? { mode: 'vote', vote: startVote() } : m === 'fixed' ? { mode: 'fixed', fixed_mhz: p.opps[0].mhz } : { mode: m })
          }}>
            <option value="">— (서버 결과 그대로)</option>
            <option value="vote">{MODE_LABEL.vote}</option>
            <option value="proportional">{MODE_LABEL.proportional}</option>
            {measured && <option value="measured">{MODE_LABEL.measured}</option>}
            <option value="fixed">{MODE_LABEL.fixed}</option>
          </select></label>
        {exp?.mode === 'fixed' && <select aria-label="DSU 고정 MHz" value={exp.fixed_mhz} onChange={(e) => setExp({ mode: 'fixed', fixed_mhz: Number(e.target.value) })}>
          {p.opps.map((o) => <option key={o.mhz} value={o.mhz}>{o.mhz} MHz</option>)}</select>}
      </div>
      {vote && <div className="table-x" style={{ marginTop: 6 }}>
        <table className="tb-mini-table dsu-vote" aria-label="DSU vote 표">
          <thead><tr><th>cluster</th><th colSpan={Math.max(...Object.values(vote).map((v) => v.length))}>cluster OPP (MHz) → DSU 최소 MHz</th></tr></thead>
          <tbody>{Object.entries(vote).map(([cl, pts]) => (
            <tr key={cl}><td className="mono">{cl}</td>
              {pts.map(([f, d], i) => <td key={f}><div className="faint mono" style={{ fontSize: 10.5 }}>{f}</div>
                <select aria-label={`${cl} ${f} MHz DSU`} value={d} onChange={(e) => setCell(cl, i, Number(e.target.value))}>
                  {p.opps.map((o) => <option key={o.mhz} value={o.mhz}>{o.mhz}</option>)}</select></td>)}
            </tr>))}</tbody>
        </table>
        <div className="toolbar" style={{ gap: 6, marginTop: 6 }}>
          {server?.vote && <button className="btn tb-mini" onClick={() => setExp({ mode: 'vote', vote: expandVote(server.vote!, p) })}>topology 값</button>}
          <button className="btn tb-mini" onClick={() => setExp({ mode: 'vote', vote: proportionalVote(p) })} title="비례 규칙과 같은 결과가 나오는 표">비례로 채우기</button>
          <button className="btn tb-mini" onClick={() => { void navigator.clipboard?.writeText(voteYaml(vote)).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) }) }}
            title="power_model_params cpu.dsu에 붙여 넣을 YAML">{copied ? '복사됨' : 'YAML 복사'}</button>
        </div>
      </div>}
      <div className="toolbar" style={{ gap: 6, marginTop: 8 }}>
        <button className="btn tb-mini" disabled={!exp} onClick={() => setSaved((s) => ({ ...s, A: exp! }))}>A로 저장</button>
        <button className="btn tb-mini" disabled={!exp} onClick={() => setSaved((s) => ({ ...s, B: exp! }))}>B로 저장</button>
        <span className="grow" />
        {applied && <span className="faint" style={{ fontSize: 12 }}>서버 계산에 실험 규칙 적용 중</span>}
        <button className="btn tb-mini" disabled={same(exp, applied)} onClick={() => onApply(exp)}
          title="반환된 후보 재정렬이 아니라 전체 조합을 이 규칙으로 다시 sweep">{exp ? '이 규칙으로 다시 계산' : '서버 기본(auto)으로 다시 계산'}</button>
      </div>
      <table className="tb-mini-table" style={{ marginTop: 8, width: '100%' }} aria-label="DSU 정책 비교">
        <thead><tr><th>정책</th><th style={{ textAlign: 'right' }}>★ mW</th><th style={{ textAlign: 'right' }}>최저 mW</th><th style={{ textAlign: 'right' }}>Δ</th><th style={{ textAlign: 'right' }}>DSU MHz ★→최저</th><th>최저 배치</th></tr></thead>
        <tbody>{rows.map((r) => { const k = bestKey(r.s)
          return <tr key={r.key}><td>{r.label}</td><td className="mono" style={{ textAlign: 'right' }}>{fmt(r.s.refMw, 1)}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{r.s.bestMw === null ? '—' : fmt(r.s.bestMw, 1)}</td>
            <td className={`mono ${(r.s.deltaMw ?? 0) < 0 ? 'pm-down' : ''}`} style={{ textAlign: 'right' }}>{r.s.deltaMw === null ? '—' : fmt(r.s.deltaMw, 1)}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{r.s.refDsuMhz ?? '—'} → {r.s.bestDsuMhz ?? '—'}</td>
            <td className="mono faint" style={{ fontSize: 11 }}>{k}{r.key !== 'srv' && k !== baseBest && <span className="badge v-warn" style={{ marginLeft: 6 }}>최적 배치 바뀜</span>}</td></tr> })}</tbody>
      </table>
      {exp && <div className="faint" style={{ fontSize: 11.5, marginTop: 4 }}>실험 규칙은 서버가 반환한 후보({candidates}개) 안에서 다시 계산·정렬합니다. 전체 조합 순위는 “이 규칙으로 다시 계산”.</div>}
    </div>
  )
}
