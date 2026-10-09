// S5 (예측 현황): re-run current predictions under their stored condition — stale ones after an input change, or all
// of the filtered rows with a new power params version — one at a time with progress.
import { useEffect, useRef, useState } from 'react'
import { archApi, type BoardRow, type RecomputeResult } from '../lib/archExplore'
import type { PowerParamsVersion } from '../lib/calibration'
import { fmt } from '../lib/timingBudget'

type Item = RecomputeResult & { error?: string }

export function RecomputePanel({ rows, staleIds, params, initialParams, onDone, onClose }: {
  rows: BoardRow[]; staleIds: Set<string>; params: PowerParamsVersion[]; initialParams?: string
  onDone: () => void; onClose: () => void
}) {
  const stale = rows.filter((r) => staleIds.has(r.id))
  const [scope, setScope] = useState<'stale' | 'all'>(stale.length ? 'stale' : 'all')
  const [pp, setPp] = useState(initialParams ?? '')
  const [reason, setReason] = useState('')
  const [items, setItems] = useState<Item[]>([])
  const [running, setRunning] = useState(false)
  const [stop, setStop] = useState(false)
  const targets = scope === 'stale' ? stale : rows
  const stopRef = useStopRef(stop)
  const start = async () => {
    setRunning(true); setStop(false); setItems([])
    const out: Item[] = []
    for (const r of targets) {
      if (stopRef.current) break
      try { out.push(await archApi.recompute(r.id, pp || null, reason || undefined)) } catch (e) {
        out.push({ prediction_id: r.id, variant_id: r.variant_id, status: 'skipped', error: e instanceof Error ? e.message : String(e) })
      }
      setItems([...out])
    }
    setRunning(false); stopRef.current = false
    onDone()
  }
  const done = items.filter((x) => x.status === 'recomputed')
  return <section className="panel" style={{ padding: '8px 12px' }} aria-label="재계산">
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 12 }}>
      <b style={{ fontSize: 13 }}>재계산</b>
      <div className="seg sm" role="group" aria-label="대상">
        <button className={scope === 'stale' ? 'on' : ''} disabled={!stale.length} onClick={() => setScope('stale')}>입력 변경(stale) {stale.length}</button>
        <button className={scope === 'all' ? 'on' : ''} onClick={() => setScope('all')}>표시된 전체 {rows.length}</button>
      </div>
      <label>power params <select value={pp} onChange={(e) => setPp(e.target.value)} aria-label="재계산 power params">
        <option value="">등록 조건 그대로</option>{params.map((p) => <option key={p.ref} value={p.ref}>{p.ref}{p.calibrated ? ' · 보정' : ''}{p.status === 'draft' ? ' · draft' : ''}</option>)}</select></label>
      <input className="input" style={{ width: 220, padding: '3px 6px' }} placeholder="사유 (기본: 재계산 · params …)" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="재계산 사유" />
      {!running ? <button className="btn primary" disabled={!targets.length} onClick={start}
        title="각 예측을 등록 당시 조건(Timing Budget 조건 또는 조합 탐색 spec)으로 다시 계산해 새 버전으로 등록 — 이전 버전은 superseded, 변경 원인은 이력에서 비교">{targets.length}건 재계산</button>
        : <button className="btn" onClick={() => setStop(true)}>중지</button>}
      <span className="grow" /><button className="btn tb-mini" onClick={onClose} disabled={running}>닫기</button>
    </div>
    <div className="faint" style={{ fontSize: 11.5, marginTop: 4 }}>사람이 고른 조합(user:…)은 자동 재현할 수 없어 건너뜁니다 · 조합 탐색 등록은 탐색을 다시 실행하므로 시간이 걸립니다 · params의 power model(v1/v2)이 run과 다르면 오류로 표시</div>
    {items.length > 0 && <>
      <div style={{ fontSize: 12, margin: '6px 0' }}>{running ? `진행 ${items.length}/${targets.length}` : `완료 ${items.length}건`} · 재등록 {done.length} · 건너뜀 {items.length - done.length}
        {done.length > 0 && <> · 합계 Δ <b className="mono">{fmt(done.reduce((s, x) => s + (x.delta_mw ?? 0), 0), 0)}</b> mW</>}</div>
      <div className="table-x"><table className="tb-mini-table" style={{ fontSize: 11.5 }}>
        <thead><tr><th>Variant</th><th>결과</th><th style={{ textAlign: 'right' }}>이전 mW</th><th style={{ textAlign: 'right' }}>새 mW</th><th style={{ textAlign: 'right' }}>Δ</th><th>비고</th></tr></thead>
        <tbody>{items.map((x) => <tr key={x.prediction_id}>
          <td className="mono">{x.variant_id}</td><td>{x.status === 'recomputed' ? <span className="badge v-ok">재등록</span> : <span className="badge v-warn">건너뜀</span>}</td>
          <td className="mono" style={{ textAlign: 'right' }}>{fmt(x.old_total_mw ?? null, 0)}</td><td className="mono" style={{ textAlign: 'right' }}>{fmt(x.new_total_mw ?? null, 0)}</td>
          <td className="mono" style={{ textAlign: 'right' }}>{x.delta_mw === null || x.delta_mw === undefined ? '—' : `${x.delta_mw >= 0 ? '+' : ''}${fmt(x.delta_mw, 0)}`}</td>
          <td className="faint" title={x.error ?? x.reason}>{(x.error ?? x.reason ?? '').slice(0, 90)}</td></tr>)}</tbody></table></div>
    </>}
  </section>
}

function useStopRef(stop: boolean) {
  const ref = useRef(false)
  useEffect(() => { ref.current = stop }, [stop])
  return ref
}
