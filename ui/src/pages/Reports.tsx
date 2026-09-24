import { useState } from 'react'
import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { archApi, type ReportMeta } from '../lib/archExplore'

export function ReportsPage({ ctx }: { ctx: Ctx }) {
  const [tick, setTick] = useState(0)
  const list = useAsync(() => archApi.reports(), [tick])
  const id = ctx.params.report ?? list.data?.[0]?.id
  const cur = list.data?.find((r) => r.id === id)
  const stale = useAsync(() => (id ? archApi.reportStale(id) : Promise.resolve(null)), [id, tick])
  const [msg, setMsg] = useState<string>()
  const regenerate = async (r: ReportMeta) => {
    try { const n = await archApi.createReport(r.run_ids[0], r.title); setTick((t) => t + 1); ctx.navigate(undefined, { report: n.id }, true) } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }
  const publish = async (r: ReportMeta) => {
    try { await archApi.setReportStatus(r.id, r.status === 'draft' ? 'published' : 'draft'); setTick((t) => t + 1) } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }
  return (
    <div className="page tb-page">
      <div className="toolbar" style={{ gap: 12, flexWrap: 'wrap' }}>
        <span className="muted" style={{ fontSize: 13 }}>보고서</span>
        <select className="input" value={id ?? ''} onChange={(e) => ctx.navigate(undefined, { report: e.target.value }, true)} style={{ minWidth: 420 }} aria-label="보고서 선택">
          {(list.data ?? []).map((r) => <option key={r.id} value={r.id}>[{r.status}] {r.title} · {r.generated_at?.slice(0, 16).replace('T', ' ')} · spec {r.spec_ok}/{r.explored}</option>)}
        </select>
        {cur && <>
          <span className={`badge ${cur.status === 'published' ? 'v-ok' : 'v-warn'}`}>{cur.status}</span>
          {stale.data?.stale && <span className="badge v-warn" title={stale.data.changed.map((c) => c.variant_id).join(', ')}>현재 예측과 다름 ({stale.data.changed.length})</span>}
          <span className="grow" />
          {msg && <span className="err" style={{ margin: 0 }}>{msg}</span>}
          <button className="btn" onClick={() => publish(cur)}>{cur.status === 'draft' ? '게시 (published)' : 'draft로'}</button>
          <button className="btn" onClick={() => regenerate(cur)} title="같은 run + 현재 등록 예측으로 새 snapshot 생성">재생성</button>
          <a className="btn primary" href={archApi.reportHtmlUrl(cur.id)} target="_blank" rel="noreferrer">HTML 열기 / 저장</a>
        </>}
      </div>
      {list.error && <div className="err">{list.error}</div>}
      {list.data && !list.data.length && <div className="empty">보고서가 없습니다. 조합 탐색 run에서 “검토 보고서 생성”을 실행하세요.</div>}
      {cur && <div className="faint" style={{ fontSize: 12 }}>{cur.id} · run {cur.run_ids.join(', ')} · DVFS {cur.dvfs_table_ref ?? '—'} · {cur.engine_rev} · sha256 {cur.html_sha256.slice(0, 12)} · snapshot 고정 (예측이 바뀌어도 보고서 수치 불변)</div>}
      {cur && <section className="panel" style={{ padding: 0 }}><iframe key={cur.id} className="rpt-frame" title={cur.title} src={archApi.reportHtmlUrl(cur.id)} /></section>}
    </div>
  )
}
