import { useEffect, useRef, useState } from 'react'
import type { Ctx } from '../App'
import { CandidateReview } from '../components/CandidateReview'
import { useAsync } from '../lib/route'
import { archApi, type ReportMeta } from '../lib/archExplore'
import { reportsForProject } from '../lib/provenance'
import { RiskRegisterCard } from '../components/RiskRegister'
import { latestProjectReports } from '../lib/reportPortfolio'

export function ReportsPage({ ctx }: { ctx: Ctx }) {
  const [tick, setTick] = useState(0)
  const list = useAsync(() => archApi.reports(), [tick])
  // AUTO-04: reports created elsewhere (another tab, API, automatic regeneration) appear when the page regains focus
  useEffect(() => {
    const refresh = () => { if (document.visibilityState === 'visible') setTick((t) => t + 1) }
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => { window.removeEventListener('focus', refresh); document.removeEventListener('visibilitychange', refresh) }
  }, [])
  // U7: only the selected 과제's reports open by default; others stay selectable under their own group.
  const { mine, others } = reportsForProject(list.data ?? [], ctx.project)
  // RPT-01: the project report (current predictions across runs) opens first; run snapshots stay selectable
  const id = ctx.params.report ?? (mine.find((r) => r.scope === 'project') ?? mine[0])?.id
  const cur = list.data?.find((r) => r.id === id)
  const label = (r: ReportMeta) => `[${r.status}] ${r.scope === 'project' ? '과제 · ' : 'run · '}${r.title} · ${r.generated_at?.slice(0, 16).replace('T', ' ')} · spec ${r.spec_ok}/${r.explored}`
  const stale = useAsync(() => (id ? archApi.reportStale(id) : Promise.resolve(null)), [id, tick])
  const [msg, setMsg] = useState<string>()
  const [busy, setBusy] = useState(false)
  const created = async (p: Promise<ReportMeta>) => {
    setBusy(true); setMsg(undefined)
    try { const n = await p; setTick((t) => t + 1); ctx.navigate(undefined, { report: n.id }, true) } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  const regenerate = (r: ReportMeta) => created(r.scope === 'project' && r.project_ref ? archApi.createProjectReport(r.project_ref) : archApi.createReport(r.run_ids[0], r.title))
  // U16/R14: publishing records who reviewed it and why; going back to draft is one click
  const [review, setReview] = useState<{ reviewer: string; note: string; acknowledge_gaps?: boolean } | null>(null)
  const [showStale, setShowStale] = useState(false)
  const frame = useRef<HTMLIFrameElement>(null)
  useEffect(() => { setReview(null); setMsg(undefined); setShowStale(false) }, [id]) // a review draft belongs to one report
  const publish = async (r: ReportMeta) => {
    if (r.status === 'draft' && !review) { setReview({ reviewer: '', note: '' }); return }
    try {
      await archApi.setReportStatus(r.id, r.status === 'draft' ? 'published' : 'draft', r.status === 'draft' ? review ?? undefined : undefined)
      setReview(null); setMsg(undefined); setTick((t) => t + 1)
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }
  const printPdf = () => { const w = frame.current?.contentWindow; if (w) { w.focus(); w.print() } }
  const portfolio = latestProjectReports(list.data ?? [], ctx.projects)
  return (
    <div className="page tb-page">
      <CandidateReview scope={{ project_ref: ctx.project, scenario_id: ctx.scenario, variant_id: ctx.variant }} exportable />
      {portfolio.length > 0 && <section className="panel" style={{ padding: '10px 12px' }} aria-label="과제 현황">
        <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', marginBottom: 6, flexWrap: 'wrap' }}>
          <b>과제 현황</b><span className="faint" style={{ fontSize: 12 }}>과제별 최신 과제 보고서 · 고객 기준 3항목 · 열린 risk · 예측 신뢰도 · 행 클릭 = 그 보고서</span>
        </div>
        <div className="table-x"><table className="tb-mini-table pf-table" style={{ width: '100%' }}>
          <thead><tr><th>SoC · 과제</th><th>최근 과제 보고서</th><th>① fps</th><th>② 전과제 대비 (이하 · 유사 · 조건부 · 초과 · 불가)</th><th>③ 발열 −10%</th><th>열린 risk (C · H · M)</th><th>신뢰도</th><th>등록 예측 mW</th></tr></thead>
          <tbody>{portfolio.map(({ project, report: r }) => {
            const s = r?.summary
            const fpsCls = s ? (s.fps.ok < s.fps.total ? 'fail' : 'ok') : ''
            const pwCls = s ? (s.power.over || s.power.flip ? 'fail' : s.power.missing || s.power.similar || s.power.conditional ? 'warn' : 'ok') : ''
            const thCls = s ? (s.thermal.items && s.thermal.reach10 < s.thermal.items ? 'fail' : 'ok') : ''
            return <tr key={project.id} className={r && r.id === id ? 'selected' : ''} onClick={() => (r ? ctx.navigate(undefined, { report: r.id, project: project.id }, true) : ctx.setProject(project.id))}>
              <td><b>{project.soc}</b> <span className="faint">{project.board || project.id}</span></td>
              <td className="faint">{r ? `${r.generated_at?.slice(0, 10)} · ${r.status}` : '과제 보고서 없음'}</td>
              <td className={`pf-cell ${fpsCls}`}>{s ? `${s.fps.ok} / ${s.fps.total}` : '—'}</td>
              <td className={`pf-cell ${pwCls}`} title={s?.power.flip ? `예측 ↔ 실측 반대 ${s.power.flip}건` : undefined}>{s ? `${s.power.ok} · ${s.power.similar} · ${s.power.conditional ?? 0} · ${s.power.over} · ${s.power.missing} / ${s.power.total}${s.power.flip ? ` (반대 ${s.power.flip})` : ''}` : '—'}</td>
              <td className={`pf-cell ${thCls}`}>{s ? (s.thermal.items ? `${s.thermal.reach10} / ${s.thermal.items}` : '대상 없음') : '—'}</td>
              <td>{s ? <><span className="badge v-fail">{s.risks.critical}</span> <span className="badge v-warn">{s.risks.high}</span> <span className="badge sev-med">{s.risks.medium}</span></> : '—'}</td>
              <td>{s?.confidence ? <span className={`badge ${s.confidence === 'A' ? 'v-ok' : s.confidence === 'B' ? 'v-warn' : 'v-fail'}`}>{s.confidence}</span> : '—'}</td>
              <td className="mono">{s?.power_range_mw ? `${s.power_range_mw[0].toFixed(0)}–${s.power_range_mw[1].toFixed(0)}` : '—'}</td>
            </tr>
          })}</tbody>
        </table></div>
      </section>}
      <div className="toolbar" style={{ gap: 12, flexWrap: 'wrap' }}>
        <span className="muted" style={{ fontSize: 13 }}>보고서</span>
        <select className="input" value={id ?? ''} onChange={(e) => ctx.navigate(undefined, { report: e.target.value }, true)} style={{ minWidth: 420 }} aria-label="보고서 선택">
          {!cur && <option value="">{mine.length ? '보고서 선택' : '이 과제의 보고서 없음'}</option>}
          {mine.length > 0 && <optgroup label="현재 과제">{mine.map((r) => <option key={r.id} value={r.id}>{label(r)}</option>)}</optgroup>}
          {others.length > 0 && <optgroup label="다른 과제">{others.map((r) => <option key={r.id} value={r.id}>{r.project_ref ?? '과제 미정'} · {label(r)}</option>)}</optgroup>}
        </select>
        {ctx.project && <button className="btn primary" disabled={busy} onClick={() => created(archApi.createProjectReport(ctx.project))}
          title="과제의 현재 등록 예측 전체(여러 run) + 실측 · 전과제 기준 · 발열 대응 · 모델 신뢰도로 보고서 생성, risk register 갱신">{busy ? '생성 중…' : '과제 보고서 생성'}</button>}
        {cur && <>
          <span className={`badge ${cur.status === 'published' ? 'v-ok' : 'v-warn'}`}>{cur.status}</span>
          <span className="badge">{cur.scope === 'project' ? '과제 범위' : 'run 범위'}</span>
          {stale.data?.stale && <button className="badge v-warn badge-btn" onClick={() => setShowStale((v) => !v)} title="클릭 = 달라진 variant">현재 예측과 다름 ({stale.data.changed.length})</button>}
          {(stale.data?.old_engine?.length ?? 0) > 0 && <button className="badge v-warn badge-btn" onClick={() => setShowStale((v) => !v)}
            title={`현재 engine ${stale.data?.engine_rev ?? ''}과 다른 engine으로 계산된 예측 — 재탐색 · 재등록 후 재생성`}>이전 engine ({stale.data?.old_engine?.length})</button>}
          <span className="grow" />
          {msg && <span className="err" style={{ margin: 0 }}>{msg}</span>}
          {!review && <button className="btn" onClick={() => publish(cur)}>{cur.status === 'draft' ? '게시 (검토 기록)…' : 'draft로'}</button>}
          <button className="btn" disabled={busy} onClick={() => regenerate(cur)} title={cur.scope === 'project' ? '과제의 현재 예측으로 새 snapshot 생성 (risk register 갱신)' : '같은 run과 해당 run에서 등록한 현재 예측으로 새 snapshot 생성'}>재생성</button>
          <a className="btn" href={archApi.reportXlsxUrl(cur.id)} title="보고서 표를 sheet별로 (수치 원본)">XLSX</a>
          <a className="btn" href={archApi.reportPackageUrl(cur.id)} title="고정 본문 + cover(검토 상태·검토자·이력) + manifest(입력 hash·measurement ID·생략 건수) — 오프라인 보관용">검토본 ZIP</a>
          <button className="btn" onClick={printPdf} title="인쇄 대화상자에서 'PDF로 저장' 선택 · A4 가로">PDF</button>
          <a className="btn primary" href={archApi.reportHtmlUrl(cur.id)} target="_blank" rel="noreferrer">HTML 열기 / 저장</a>
        </>}
      </div>
      {cur && showStale && stale.data && (stale.data.stale || (stale.data.old_engine?.length ?? 0) > 0) && <div className="lib-note warn">
        {stale.data.changed.length > 0 && <div>보고서 이후 바뀐 예측: {stale.data.changed.slice(0, 12).map((c) => `${c.variant_id.replace(/^cam-rec-/, '')}${c.snapshot ? '' : ' (신규 등록)'}${c.current ? '' : ' (등록 해제)'}`).join(', ')}{stale.data.changed.length > 12 ? ` 외 ${stale.data.changed.length - 12}` : ''} — “재생성”으로 새 snapshot을 만드세요.</div>}
        {(stale.data.old_engine?.length ?? 0) > 0 && <div>이전 engine 예측 {stale.data.old_engine!.length}건 ({[...new Set(stale.data.old_engine!.map((o) => o.engine_rev))].join(', ')} → {stale.data.engine_rev}) — 조합 탐색 · 재등록 후 재생성해야 현재 계산 방식이 반영됩니다.</div>}
      </div>}
      {cur && review && <div className="panel" style={{ padding: '10px 12px', display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <b style={{ fontSize: 13 }}>게시 검토 기록</b>
        <input className="input" placeholder="검토자" value={review.reviewer} onChange={(e) => setReview({ ...review, reviewer: e.target.value })} style={{ width: 140 }} aria-label="검토자" />
        <input className="input" placeholder="검토 의견 (예: spec · 실측 대조 확인, IQ 평가 대기 2건)" value={review.note} onChange={(e) => setReview({ ...review, note: e.target.value })} style={{ flexGrow: 1, minWidth: 260 }} aria-label="검토 의견" />
        {(cur.summary?.blockers ?? 0) > 0 && <label className="faint" style={{ fontSize: 12, display: 'flex', gap: 4, alignItems: 'center' }}
          title="KPI 미탐색 등 게시 전 확인 항목 — 사유를 검토 의견에 남기세요">
          <input type="checkbox" checked={!!review.acknowledge_gaps} onChange={(e) => setReview({ ...review, acknowledge_gaps: e.target.checked })} />
          확인 필요 {cur.summary?.blockers}건을 확인함</label>}
        <button className="btn primary" disabled={!review.reviewer.trim() || !review.note.trim() || ((cur.summary?.blockers ?? 0) > 0 && !review.acknowledge_gaps)}
          onClick={() => publish(cur)}>게시</button>
        <button className="btn" onClick={() => setReview(null)}>취소</button>
      </div>}
      {cur?.review && <div className="faint" style={{ fontSize: 12 }}>최근 검토: {cur.review.status} · {cur.review.reviewer ?? cur.review.by ?? '—'} · {cur.review.at.slice(0, 16).replace('T', ' ')}{cur.review.note ? ` — ${cur.review.note}` : ''}{(cur.review_count ?? 0) > 1 ? ` (이력 ${cur.review_count}건)` : ''}</div>}
      {list.error && <div className="err">{list.error}</div>}
      {list.data && !list.data.length && <div className="empty">보고서가 없습니다. “과제 보고서 생성”을 누르거나 조합 탐색 run에서 “검토 보고서 생성”을 실행하세요.</div>}
      {list.data && list.data.length > 0 && !cur && <div className="empty">이 과제의 보고서가 없습니다{others.length ? ` (다른 과제 ${others.length}건은 목록의 “다른 과제”에서 열 수 있음)` : ''}. “과제 보고서 생성”을 누르세요.</div>}
      {ctx.project && <RiskRegisterCard projectRef={ctx.project} tick={tick} />}
      {cur && cur.project_ref !== ctx.project && <div className="lib-note warn">선택한 보고서는 다른 과제({cur.project_ref ?? '미정'})의 보고서입니다.</div>}
      {cur && <div className="faint" style={{ fontSize: 12 }}>{cur.id} · <span title={cur.run_ids.join('\n')}>run {cur.run_ids.length > 1 ? `${cur.run_ids.length}개` : cur.run_ids[0]}</span> · DVFS {cur.dvfs_table_ref ?? '—'} · {cur.engine_rev} · sha256 {cur.html_sha256.slice(0, 12)} · snapshot 고정 (예측이 바뀌어도 보고서 수치 불변)</div>}
      {cur && <section className="panel" style={{ padding: 0 }}><iframe ref={frame} key={cur.id} className="rpt-frame" title={cur.title} src={archApi.reportHtmlUrl(cur.id)} /></section>}
    </div>
  )
}
