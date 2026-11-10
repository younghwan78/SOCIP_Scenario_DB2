import { dismissStatus, useStatusNotices } from '../lib/status'

const LABEL = { ok: '완료', error: '오류', info: '안내' }

export function StatusToast() {
  const notices = useStatusNotices()
  return <div className="status-toasts" role="status" aria-label="작업 알림" aria-live="polite" aria-atomic="false" aria-relevant="additions">
    {notices.map((notice) => <div key={notice.id} className={`status-toast status-toast-${notice.kind}`}
      role={notice.kind === 'error' ? 'alert' : undefined} aria-live={notice.kind === 'error' ? 'assertive' : undefined}>
      <div><b>{LABEL[notice.kind]}</b><span>{notice.text}</span></div>
      <button className="btn tb-mini" aria-label={`알림 닫기: ${notice.text}`} onClick={() => dismissStatus(notice.id)}>닫기</button>
    </div>)}
  </div>
}
