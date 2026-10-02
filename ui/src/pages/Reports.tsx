import { useRef, useState } from 'react'
import type { Ctx } from '../App'
import { useAsync } from '../lib/route'
import { archApi, type ReportMeta } from '../lib/archExplore'
import { reportsForProject } from '../lib/provenance'

export function ReportsPage({ ctx }: { ctx: Ctx }) {
  const [tick, setTick] = useState(0)
  const list = useAsync(() => archApi.reports(), [tick])
  // U7: only the selected 과제's reports open by default; others stay selectable under their own group.
  const { mine, others } = reportsForProject(list.data ?? [], ctx.project)
  const id = ctx.params.report ?? mine[0]?.id
  const cur = list.data?.find((r) => r.id === id)
  const label = (r: ReportMeta) => `[${r.status}] ${r.title} · ${r.generated_at?.slice(0, 16).replace('T', ' ')} · spec ${r.spec_ok}/${r.explored}`
  const stale = useAsync(() => (id ? archApi.reportStale(id) : Promise.resolve(null)), [id, tick])
  const [msg, setMsg] = useState<string>()
  const regenerate = async (r: ReportMeta) => {
    try { const n = await archApi.createReport(r.run_ids[0], r.title); setTick((t) => t + 1); ctx.navigate(undefined, { report: n.id }, true) } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }
  // U16/R14: publishing records who reviewed it and why; going back to draft is one click
  const [review, setReview] = useState<{ reviewer: string; note: string } | null>(null)
  const frame = useRef<HTMLIFrameElement>(null)
  const publish = async (r: ReportMeta) => {
    if (r.status === 'draft' && !review) { setReview({ reviewer: '', note: '' }); return }
    try {
      await archApi.setReportStatus(r.id, r.status === 'draft' ? 'published' : 'draft', r.status === 'draft' ? review ?? undefined : undefined)
      setReview(null); setMsg(undefined); setTick((t) => t + 1)
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }
  const printPdf = () => { const w = frame.current?.contentWindow; if (w) { w.focus(); w.print() } }
  return (
    <div className="page tb-page">
      <div className="toolbar" style={{ gap: 12, flexWrap: 'wrap' }}>
        <span className="muted" style={{ fontSize: 13 }}>보고서</span>
        <select className="input" value={id ?? ''} onChange={(e) => ctx.navigate(undefined, { report: e.target.value }, true)} style={{ minWidth: 420 }} aria-label="보고서 선택">
          {!cur && <option value="">{mine.length ? '보고서 선택' : '이 과제의 보고서 없음'}</option>}
          {mine.length > 0 && <optgroup label="현재 과제">{mine.map((r) => <option key={r.id} value={r.id}>{label(r)}</option>)}</optgroup>}
          {others.length > 0 && <optgroup label="다른 과제">{others.map((r) => <option key={r.id} value={r.id}>{r.project_ref ?? '과제 미정'} · {label(r)}</option>)}</optgroup>}
        </select>
        {cur && <>
          <span className={`badge ${cur.status === 'published' ? 'v-ok' : 'v-warn'}`}>{cur.status}</span>
          {stale.data?.stale && <span className="badge v-warn" title={stale.data.changed.map((c) => c.variant_id).join(', ')}>현재 예측과 다름 ({stale.data.changed.length})</span>}
          <span className="grow" />
          {msg && <span className="err" style={{ margin: 0 }}>{msg}</span>}
          {!review && <button className="btn" onClick={() => publish(cur)}>{cur.status === 'draft' ? '게시 (검토 기록)…' : 'draft로'}</button>}
          <button className="btn" onClick={() => regenerate(cur)} title="같은 run + 현재 등록 예측으로 새 snapshot 생성">재생성</button>
          <a className="btn" href={archApi.reportXlsxUrl(cur.id)} title="보고서 표를 sheet별로 (수치 원본)">XLSX</a>
          <button className="btn" onClick={printPdf} title="인쇄 대화상자에서 'PDF로 저장' 선택 · A4 가로">PDF</button>
          <a className="btn primary" href={archApi.reportHtmlUrl(cur.id)} target="_blank" rel="noreferrer">HTML 열기 / 저장</a>
        </>}
      </div>
      {cur && review && <div className="panel" style={{ padding: '10px 12px', display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <b style={{ fontSize: 13 }}>게시 검토 기록</b>
        <input className="input" placeholder="검토자" value={review.reviewer} onChange={(e) => setReview({ ...review, reviewer: e.target.value })} style={{ width: 140 }} aria-label="검토자" />
        <input className="input" placeholder="검토 의견 (예: spec · 실측 대조 확인, IQ 평가 대기 2건)" value={review.note} onChange={(e) => setReview({ ...review, note: e.target.value })} style={{ flexGrow: 1, minWidth: 260 }} aria-label="검토 의견" />
        <button className="btn primary" disabled={!review.reviewer.trim() || !review.note.trim()} onClick={() => publish(cur)}>게시</button>
        <button className="btn" onClick={() => setReview(null)}>취소</button>
      </div>}
      {cur?.review && <div className="faint" style={{ fontSize: 12 }}>최근 검토: {cur.review.status} · {cur.review.reviewer ?? cur.review.by ?? '—'} · {cur.review.at.slice(0, 16).replace('T', ' ')}{cur.review.note ? ` — ${cur.review.note}` : ''}{(cur.review_count ?? 0) > 1 ? ` (이력 ${cur.review_count}건)` : ''}</div>}
      {list.error && <div className="err">{list.error}</div>}
      {list.data && !list.data.length && <div className="empty">보고서가 없습니다. 조합 탐색 run에서 “검토 보고서 생성”을 실행하세요.</div>}
      {list.data && list.data.length > 0 && !cur && <div className="empty">이 과제의 보고서가 없습니다{others.length ? ` (다른 과제 ${others.length}건은 목록의 “다른 과제”에서 열 수 있음)` : ''}. 조합 탐색 run에서 “검토 보고서 생성”을 실행하세요.</div>}
      {cur && cur.project_ref !== ctx.project && <div className="lib-note warn">선택한 보고서는 다른 과제({cur.project_ref ?? '미정'})의 보고서입니다.</div>}
      {cur && <div className="faint" style={{ fontSize: 12 }}>{cur.id} · run {cur.run_ids.join(', ')} · DVFS {cur.dvfs_table_ref ?? '—'} · {cur.engine_rev} · sha256 {cur.html_sha256.slice(0, 12)} · snapshot 고정 (예측이 바뀌어도 보고서 수치 불변)</div>}
      {cur && <section className="panel" style={{ padding: 0 }}><iframe ref={frame} key={cur.id} className="rpt-frame" title={cur.title} src={archApi.reportHtmlUrl(cur.id)} /></section>}
    </div>
  )
}
