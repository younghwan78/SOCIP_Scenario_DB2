import { useEffect, useRef, useState } from 'react'
import { cancelExploreJob, clearExploreJob, isActive, resumeExploreJob, useExploreJob } from '../lib/exploreJob'
import { notify } from '../lib/status'

const STATUS: Record<string, string> = {
  queued: '대기 중', running: '진행 중', completed: '완료', cancelled: '취소됨', failed: '실패', interrupted: '중단됨',
}

/** Progress of the tracked exploration job: n / N variants, current variant, cancel / resume / open. */
export function ExploreJobPanel({ onOpen }: { onOpen: (runId: string) => void }) {
  const tracked = useExploreJob()
  const [busy, setBusy] = useState(false)
  const opened = useRef<string | null>(null)
  const job = tracked?.job
  // a job that finishes while this page is open opens its run once
  useEffect(() => {
    if (job?.status === 'completed' && job.run_id && opened.current !== job.id) {
      opened.current = job.id
      onOpen(job.run_id)
    }
  }, [job?.status, job?.run_id, job?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!tracked || !job) return null
  const active = isActive(job)
  const total = job.total_variants || 0
  const pct = total ? Math.round(100 * job.completed_variants / total) : 0
  const act = async (fn: () => Promise<void>) => {
    setBusy(true)
    try { await fn() } catch (e) { notify({ kind: 'error', text: e instanceof Error ? e.message : String(e) }) } finally { setBusy(false) }
  }
  return <section className="panel explore-job" aria-label="탐색 진행">
    <div className="explore-job-head">
      <b>{tracked.title}</b>
      <span className={`chip ${job.status === 'failed' ? 'mode-warn' : ''}`}>{STATUS[job.status] ?? job.status}{job.cancel_requested && active ? ' · 취소 요청됨' : ''}</span>
      <span className="grow" />
      {active && <button className="btn" disabled={busy || job.cancel_requested} onClick={() => act(cancelExploreJob)}>취소</button>}
      {!active && job.resumable && <button className="btn" disabled={busy} onClick={() => act(resumeExploreJob)}>다시 실행</button>}
      {job.status === 'completed' && job.run_id && <button className="btn primary" onClick={() => onOpen(job.run_id!)}>run 열기</button>}
      {!active && <button className="btn" onClick={clearExploreJob} aria-label="탐색 진행 닫기">닫기</button>}
    </div>
    <div className="explore-job-bar" role="progressbar" aria-label="탐색 variant 진행" aria-valuemin={0} aria-valuemax={total || 1}
      aria-valuenow={job.completed_variants} aria-valuetext={`${job.completed_variants} / ${total} variant`}>
      <span style={{ width: `${pct}%` }} />
    </div>
    <div className="explore-job-text">
      {total ? `${job.completed_variants} / ${total} variant` : '범위 확인 중…'}
      {active && job.current_variant ? ` · 최근 완료 ${job.current_variant}` : ''}
      {job.status === 'completed' && job.summary ? ` · spec 만족 ${job.summary.spec_ok ?? 0} · 실패 ${job.summary.errors ?? 0}` : ''}
      {job.error ? ` · ${job.error}` : ''}
    </div>
  </section>
}
