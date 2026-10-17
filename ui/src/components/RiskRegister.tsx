// Live project risk register (RPT-04): automatic rows from project reports, owner / status / note kept by people.
import { useState } from 'react'
import { usePref } from './Layout'
import { useAsync } from '../lib/route'
import { isOpen, risksApi, SEVERITY_CLASS, SEVERITY_LABEL, STATUS_LABEL, type Risk, type RiskStatus } from '../lib/reviewRisks'

const TREND: Record<string, string> = { new: '신규', ongoing: '유지', reopened: '재발', resolve_candidate: '해소 후보' }

function Row({ r, onSaved }: { r: Risk; onSaved: (r: Risk) => void }) {
  const [owner, setOwner] = useState(r.owner ?? '')
  const [status, setStatus] = useState<RiskStatus>(r.status)
  const [note, setNote] = useState(r.note ?? '')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const dirty = owner !== (r.owner ?? '') || status !== r.status || note !== (r.note ?? '')
  const save = async () => {
    setBusy(true); setErr(null)
    try { onSaved(await risksApi.update(r.id, { owner, status, note })) } catch (e) { setErr(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  const candidate = r.auto_state === 'resolve_candidate'
  return (
    <tr className={isOpen(r) ? '' : 'risk-closed'}>
      <td className="mono">{r.label}</td>
      <td><span className={`badge ${SEVERITY_CLASS[r.severity]}`}>{SEVERITY_LABEL[r.severity]}</span></td>
      <td>{r.category}</td>
      <td><b>{r.title}</b><div className="faint" style={{ fontSize: 11.5 }}>{r.detail}</div>
        {r.mitigation && <div style={{ fontSize: 11.5 }}>완화안: {r.mitigation}</div>}
        {candidate && <div className="badge v-ok" style={{ marginTop: 3 }}>해소 후보 — 규칙이 더 이상 발생하지 않음, 확인 후 종료</div>}
        {err && <div className="err" style={{ margin: 0 }}>{err}</div>}</td>
      <td className="faint" style={{ fontSize: 11.5 }} title={r.affected.join('\n')}>{r.affected.length ? `${r.affected.length} variant` : '전체'}</td>
      <td><input className="input" aria-label={`${r.label} owner`} value={owner} placeholder="owner" onChange={(e) => setOwner(e.target.value)} style={{ width: 90 }} /></td>
      <td><select aria-label={`${r.label} 상태`} value={status} onChange={(e) => setStatus(e.target.value as RiskStatus)}>
        {(Object.keys(STATUS_LABEL) as RiskStatus[]).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}</select></td>
      <td><input className="input" aria-label={`${r.label} 의견`} value={note} placeholder="의견 · 결정" onChange={(e) => setNote(e.target.value)} style={{ width: '100%', minWidth: 140 }} /></td>
      <td className="faint" style={{ fontSize: 11.5 }}>{TREND[r.trend ?? ''] ?? (candidate ? '해소 후보' : '—')}<div>{r.last_seen_at?.slice(0, 10)}</div></td>
      <td><button className="btn tb-mini primary" disabled={!dirty || busy} onClick={save}>{busy ? '…' : '저장'}</button></td>
    </tr>
  )
}

export function RiskRegisterCard({ projectRef, tick }: { projectRef: string; tick: number }) {
  const [local, setLocal] = useState(0)
  const q = useAsync(() => (projectRef ? risksApi.list(projectRef) : Promise.resolve([] as Risk[])), [projectRef, tick, local])
  const [showClosed, setShowClosed] = useState(false)
  const [openPanel, setOpenPanel] = usePref<boolean>('reports.risks.open', false)
  const rows = (q.data ?? []).filter((r) => showClosed || isOpen(r) || r.auto_state === 'resolve_candidate')
  const hidden = (q.data ?? []).length - rows.length
  const open = (q.data ?? []).filter(isOpen)
  const count = (sev: Risk['severity']) => open.filter((r) => r.severity === sev).length
  return (
    <details className="panel risk-panel" aria-label="Risk register" open={openPanel} onToggle={(e) => setOpenPanel((e.target as HTMLDetailsElement).open)}>
      <summary>
        <b>Risk register (live)</b>
        <span className="faint" style={{ fontSize: 12 }}>열린 {open.length}건</span>
        {open.length > 0 && <><span className="badge v-fail">C {count('critical')}</span><span className="badge v-warn">H {count('high')}</span><span className="badge sev-med">M {count('medium')}</span></>}
        <span className="faint" style={{ fontSize: 12 }}>· 과제 보고서 생성 시 자동 규칙으로 갱신 · owner · 상태 · 의견은 여기서 기록 (다음 보고서에 반영)</span>
      </summary>
      {hidden > 0 && <button className="btn tb-mini" style={{ margin: '4px 0' }} onClick={() => setShowClosed(true)}>종료 · 수용 {hidden}건 보기</button>}
      {q.error && <div className="err">{q.error}</div>}
      {q.data && !q.data.length && <div className="empty">아직 risk가 없습니다. “과제 보고서 생성”을 실행하면 자동 규칙이 risk를 엽니다.</div>}
      {rows.length > 0 && <div className="table-x"><table className="tb-mini-table risk-table" style={{ width: '100%' }}>
        <thead><tr><th>ID</th><th>심각도</th><th>분류</th><th>내용 · 근거</th><th>영향</th><th>Owner</th><th>상태</th><th>의견</th><th>추세</th><th /></tr></thead>
        <tbody>{rows.map((r) => <Row key={`${r.id}:${r.updated_at}`} r={r} onSaved={() => setLocal((n) => n + 1)} />)}</tbody>
      </table></div>}
    </details>
  )
}
