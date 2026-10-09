// Global pill while a request waits for a simulation slot (other users' / tabs' runs are in progress).
import { useEffect, useState } from 'react'
import { useAdmissionWait } from '../lib/admission'

export function AdmissionWaitPill() {
  const w = useAdmissionWait()
  const [, tick] = useState(0)
  useEffect(() => { if (!w.waiting) return; const t = setInterval(() => tick((n) => n + 1), 1000); return () => clearInterval(t) }, [w.waiting])
  if (!w.waiting) return null
  const sec = w.since ? Math.round((Date.now() - w.since) / 1000) : 0
  return <div className="admission-wait" role="status" aria-live="polite"
    title="서버는 simulation을 동시에 몇 개만 실행합니다 (다른 사용자·탭의 계산 포함). 자리가 나면 자동으로 이어서 실행하며, 2분이 지나면 오류로 표시됩니다.">
    <span className="spinner" aria-hidden /> 계산 대기 중 · {w.waiting}건 · {sec}s — 다른 simulation이 끝나면 자동 실행
  </div>
}
