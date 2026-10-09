// Power-saving options (IQ 평가 대상): knob values / substitute IP modes explored on top of a variant.
import { useState } from 'react'
import { fmt } from '../lib/timingBudget'
import {
  CAT_COLOR, REVIEW, REVIEW_ORDER, archApi,
  type BoardRow, type OptionItem, type OptionResult, type ReviewStatus,
} from '../lib/archExplore'

const KIND: Record<string, string> = { knob: 'arch knob', ip_mode: 'IP mode' }

export function signed(v: number | null | undefined, d = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  return `${v > 0 ? '+' : ''}${fmt(v, d)}`
}

export function ReviewBadge({ status }: { status?: ReviewStatus }) {
  if (!status) return null
  const r = REVIEW[status]
  return <span className={`badge ${r.cls}`}>{r.label}</span>
}

/** Top attribution categories as small coloured chips. */
function Causes({ by }: { by: Record<string, number> }) {
  const top = Object.entries(by).filter(([, v]) => Math.abs(v) >= 0.05).slice(0, 3)
  if (!top.length) return <span className="faint">—</span>
  return <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap' }}>{top.map(([k, v]) =>
    <span key={k} className="mono" style={{ fontSize: 11 }}><i className="ax-dot" style={{ background: CAT_COLOR[k] ?? '#9A9387' }} />{k} {signed(v)}</span>)}</span>
}

export const OPTION_NOTE = 'Δ = option 적용 후 compression·DVFS를 다시 탐색한 최저 power − variant 추천 조합 · raw Δ = baseline끼리 (option 자체 효과)'

export function OptionResults({ results, best }: { results: OptionResult[]; best?: string | null }) {
  if (!results.length) return <div className="empty">탐색된 option 조합이 없습니다.</div>
  const fixedCol = results.some((r) => r.effect_given_fixed != null)
  return (
    <div className="table-x">
      <table className="tb-mini-table" style={{ width: '100%' }} aria-label="power option 조합">
        <thead><tr><th>Option 조합</th><th>종류</th><th title="variant 추천 조합 대비">Δ mW</th><th>Δ%</th><th title="compression·DVFS 재탐색 전 baseline끼리 비교">raw Δ</th><th>Δ BW MB/s</th>{fixedCol && <th title="항상 이득인 option을 고정했을 때 나머지 option이 더하는 효과">고정 대비</th>}<th>원인</th><th>spec</th><th>IQ</th></tr></thead>
        <tbody>{results.map((r) => (
          <tr key={r.key} className={r.key === best ? 'selected' : ''} title={r.key}>
            <td>{r.labels.join(' + ')}</td>
            <td className="faint" style={{ fontSize: 11 }}>{r.kinds.map((k) => KIND[k] ?? k).join(', ')}</td>
            <td className="mono" style={{ color: (r.delta_mw ?? 0) < 0 ? 'var(--primary-strong)' : (r.delta_mw ?? 0) > 0 ? 'var(--del-text)' : undefined }}><b>{signed(r.delta_mw)}</b></td>
            <td className="mono">{r.delta_pct === null ? '—' : `${signed(r.delta_pct)}%`}</td>
            <td className="mono faint">{signed(r.raw_delta_mw)}</td>
            <td className="mono">{signed(r.delta_bw_mbs, 0)}</td>
            {fixedCol && <td className="mono">{r.effect_given_fixed == null ? <span className="faint">—</span> : signed(r.effect_given_fixed)}</td>}
            <td><Causes by={r.attribution.by_category} /></td>
            <td title={r.spec_reasons.join('\n')}><span className={`badge ${r.spec_ok ? 'v-ok' : 'v-fail'}`}>{r.spec_ok ? 'OK' : 'Fail'}</span></td>
            <td>{r.review_status ? <ReviewBadge status={r.review_status} /> : <span className="faint" style={{ fontSize: 11 }}>{r.iq_eval === 'required' ? '평가 필요' : '—'}</span>}</td>
          </tr>))}</tbody>
      </table>
    </div>
  )
}

function itemDetail(i: OptionItem): string {
  if (i.kind === 'ip_mode') {
    const up = i.unit_power_mw_mp !== undefined && i.unit_power_mw_mp !== null ? ` · unit power ${fmt(i.from_unit_power_mw_mp, 2)}→${fmt(i.unit_power_mw_mp, 2)} mW/MP` : ''
    const ppc = i.ppc !== undefined && i.ppc !== null && i.ppc !== i.from_ppc ? ` · ppc ${fmt(i.from_ppc, 1)}→${fmt(i.ppc, 1)}` : ''
    return `${i.ip_ref ?? ''} ${i.from}→${i.value}${up}${ppc}${i.source ? ` · ${i.source}` : ''}`
  }
  return `${i.from} → ${i.value}`
}

/** Per-item IQ review controls (scenario-wide or this variant only). */
export function OptionReviewPanel({ row, onChanged }: { row: BoardRow; onChanged: () => void }) {
  const po = row.power_options
  const [edit, setEdit] = useState<string>()
  const [status, setStatus] = useState<ReviewStatus>('iq_eval')
  const [scope, setScope] = useState<'scenario' | 'variant'>('scenario')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string>()
  if (!po || !po.items.length) return null
  const open = (key: string) => {
    const it = po.items.find((i) => i.key === key)
    setEdit(key); setErr(undefined)
    setStatus(it?.review.status === 'candidate' ? 'iq_eval' : (it?.review.status ?? 'iq_eval'))
    setScope(it?.review.scope === 'variant' ? 'variant' : 'scenario'); setNote(it?.review.note ?? '')
  }
  const save = async () => {
    if (!edit) return
    setBusy(true); setErr(undefined)
    try {
      await archApi.setOptionReview({ scenario_id: row.scenario_id, variant_id: scope === 'variant' ? row.variant_id : '*', option_key: edit, status, note: note || undefined })
      setEdit(undefined); onChanged()
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      <table className="tb-mini-table" style={{ width: '100%' }} aria-label="option IQ 검토">
        <thead><tr><th>Option</th><th>변경</th><th>IQ 상태</th><th>범위</th><th>메모</th><th /></tr></thead>
        <tbody>{po.items.map((i) => (
          <tr key={i.key} className={edit === i.key ? 'selected' : ''}>
            <td>{i.label} <span className="faint" style={{ fontSize: 11 }}>{KIND[i.kind]}</span></td>
            <td className="mono faint" style={{ fontSize: 11 }}>{itemDetail(i)}</td>
            <td><ReviewBadge status={i.review.status} /></td>
            <td className="faint" style={{ fontSize: 11 }}>{i.review.scope === 'variant' ? '이 variant' : i.review.scope === 'scenario' ? 'scenario 전체' : '—'}</td>
            <td style={{ fontSize: 12 }}>{i.review.note ?? ''}</td>
            <td><button className="btn sm" onClick={() => open(i.key)}>상태 변경</button></td>
          </tr>))}</tbody>
      </table>
      {edit && (
        <div className="ax-row" style={{ gap: 8, flexWrap: 'wrap' }} role="group" aria-label="IQ 상태 변경">
          <span className="mono" style={{ fontSize: 12 }}>{edit}</span>
          <div className="seg sm">{REVIEW_ORDER.map((s) => <button key={s} className={status === s ? 'on' : ''} onClick={() => setStatus(s)}>{REVIEW[s].label}</button>)}</div>
          <div className="seg sm">
            <button className={scope === 'scenario' ? 'on' : ''} onClick={() => setScope('scenario')}>scenario 전체</button>
            <button className={scope === 'variant' ? 'on' : ''} onClick={() => setScope('variant')}>이 variant만</button>
          </div>
          <input className="input" style={{ flex: 1, minWidth: 200 }} placeholder="메모 (IQ 평가 결과, 담당, 일정)" value={note} onChange={(e) => setNote(e.target.value)} />
          <button className="btn primary" disabled={busy} onClick={save}>저장</button>
          <button className="btn" onClick={() => setEdit(undefined)}>취소</button>
          {err && <span className="err" style={{ margin: 0 }}>{err}</span>}
        </div>)}
      <div className="faint" style={{ fontSize: 11 }}>채택해도 variant는 바뀌지 않습니다. 정식 적용은 authoring에서 variant의 design_conditions(knob) 또는 node sim mode로 반영합니다.</div>
    </div>
  )
}
