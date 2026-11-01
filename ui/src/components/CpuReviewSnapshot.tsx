// CPU-11: “검토서에 포함” — record the current sweep (server-recomputed) for the next project report.
import { useState } from 'react'
import { Card } from './TimingCharts'
import { useAsync } from '../lib/route'
import { cpuSnapshotApi } from '../lib/reviewCpu'
import { fmt } from '../lib/timingBudget'

const gx = (g: number | null | undefined) => (g === null || g === undefined ? '—' : `×${(Math.round(g * 100) / 100).toFixed(Math.abs(g * 10 - Math.round(g * 10)) < 1e-6 ? 1 : 2)}`)

export function CpuReviewSnapshotCard({ projectRef, scenarioId, variantId, canRecord, onRecord }: {
  projectRef: string; scenarioId: string | null; variantId: string | null; canRecord: boolean
  /** returns the request the current sweep used (null = nothing computed yet) */
  onRecord: () => Promise<unknown>
}) {
  const [tick, setTick] = useState(0)
  const list = useAsync(() => cpuSnapshotApi.list(projectRef), [projectRef, tick])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const record = async () => {
    setBusy(true); setMsg(null)
    try { await onRecord(); setMsg('포함됨 — 과제 보고서를 재생성하면 CPU · SW 절에 반영'); setTick((t) => t + 1) } catch (e) { setMsg(String((e as Error).message ?? e)) } finally { setBusy(false) }
  }
  const withdraw = async (id: string) => {
    setBusy(true); setMsg(null)
    try { await cpuSnapshotApi.withdraw(id); setTick((t) => t + 1) }
    catch (e) { setMsg(String((e as Error).message ?? e)) }
    finally { setBusy(false) }
  }
  const rows = list.data ?? []
  const mine = rows.find((r) => r.scenario_id === scenarioId && r.variant_id === variantId)
  return (
    <Card id="cpu-review-snap" title="검토서 포함" minHeight={100}
      note="SW 증가 곡선 결과(허용치 · OPP 계단 · 최적 배분 · CPU 기인 BW)를 과제 보고서 CPU · SW 절에 snapshot으로 기록 · variant당 최신 1건"
      actions={<button className="btn tb-mini primary" disabled={!canRecord || busy} onClick={() => void record()} title={canRecord ? '서버가 같은 조건으로 sweep을 다시 계산해 저장' : 'SW 증가 곡선을 먼저 계산'}>
        {busy ? '저장 중…' : mine ? '갱신' : '검토서에 포함'}</button>}>
      {msg && <div className={/포함됨/.test(msg) ? 'lib-note' : 'err'} style={{ marginBottom: 6 }}>{msg}</div>}
      {list.error && <div className="err">{list.error}</div>}
      {rows.length ? <table className="tb-mini-table" style={{ width: '100%' }}>
        <thead><tr><th>variant</th><th>topology</th><th>허용치</th><th>제약</th><th>최적 재배치</th><th>기록</th><th /></tr></thead>
        <tbody>{rows.map((r) => <tr key={r.id} className={r.scenario_id === scenarioId && r.variant_id === variantId ? 'selected' : ''}>
          <td className="mono">{r.variant_id.replace(/^cam-rec-/, '')}{r.summary.profile_origin === 'synthetic' && <span className="badge v-warn" style={{ marginLeft: 4 }}>합성</span>}
            {r.calc_current === false && <span className="badge v-warn" style={{ marginLeft: 4 }} title={`기록 시 계산 ${r.calc_rev ?? '(기록 없음)'} — 현재 계산 방식(RT chain 포함 timing · 첫 OPP 계단)과 다름. 같은 조건으로 계산 후 “갱신”`}>이전 계산</span>}</td>
          <td className="mono faint">{r.power_params_ref}</td>
          <td className="mono"><b className={r.summary.tolerance !== null && r.summary.tolerance < 1.2 ? 'pm-up' : ''}>{r.summary.tolerance === null ? '범위 밖' : gx(r.summary.tolerance)}</b></td>
          <td>{r.summary.binding === 'timing' ? 'timing' : r.summary.binding === 'opp' ? 'OPP' : '—'}</td>
          <td className="mono">{fmt(r.summary.best_at_start.delta_mw, 1)} mW</td>
          <td className="faint">{r.created_at?.slice(0, 16).replace('T', ' ')} · {r.created_by ?? '—'}</td>
          <td><button className="btn tb-mini" disabled={busy} onClick={() => void withdraw(r.id)}>제외</button></td></tr>)}</tbody>
      </table> : <div className="empty">아직 포함된 CPU 결과가 없습니다.</div>}
    </Card>
  )
}
