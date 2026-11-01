import { useEffect, useState } from 'react'
import { STAGE_LABEL, type CpuDone, type CpuProgress } from '../lib/cpuAnalysis'

const seconds = (ms: number) => (ms < 1000 ? `${Math.max(0, Math.round(ms))} ms` : `${(ms / 1000).toFixed(1)} s`)
const clock = (at: number) => new Date(at).toLocaleTimeString('ko-KR', { hour12: false })

/**
 * What the CPU what-if is doing: the running stage (i/n) with its elapsed time and a stop button, or the
 * last calculation (time, duration, outcome) and whether the displayed result still matches the inputs.
 * One run button for the page, so the state is visible wherever the result cards are scrolled to.
 */
export function CpuRunStatus({ progress, done, busy, stale, staleNote, hasResult, canRun, onRun, onStop }: {
  progress: CpuProgress | null; done: CpuDone | null; busy: boolean
  /** the displayed result was computed from other inputs than the current ones; `staleNote` says which */
  stale: boolean; staleNote?: string; hasResult: boolean; canRun: boolean
  onRun: () => void; onStop: () => void
}) {
  const [, tick] = useState(0)
  useEffect(() => {
    if (!progress) return
    const t = setInterval(() => tick((n) => n + 1), 200)
    return () => clearInterval(t)
  }, [progress])
  const stage = progress ? progress.stages[progress.index] : undefined
  return (
    <div className="cpu-run" role="status" aria-live="polite" aria-label="계산 상태">
      {progress && stage ? <>
        <span className="spinner" aria-hidden />
        <span>계산 중 · <b>{STAGE_LABEL[stage]}</b>{progress.stages.length > 1 ? ` (${progress.index + 1}/${progress.stages.length})` : ''}</span>
        <span className="mono faint">{seconds(Date.now() - progress.startedAt)}</span>
        {progress.stages.length > 1 && <span className="faint cpu-run-steps">{progress.stages.map((s, i) =>
          <span key={s} className={i < progress.index ? 'done' : i === progress.index ? 'now' : ''}>{STAGE_LABEL[s]}</span>)}</span>}
      </> : busy ? <><span className="spinner" aria-hidden /><span>계산 중…</span></>
        : done ? <span>
          마지막 계산 <span className="mono">{clock(done.at)}</span> · <span className="mono">{seconds(done.ms)}</span>
          {done.outcome === 'error' && <span className="badge v-fail" style={{ marginLeft: 6 }}>실패</span>}
          {done.outcome === 'partial' && <span className="badge v-warn" style={{ marginLeft: 6 }} title={`실패한 단계: ${(done.failed ?? []).map((s) => STAGE_LABEL[s]).join(', ')} — 아래 해당 카드의 오류 참고`}>일부 실패 · {(done.failed ?? []).map((s) => STAGE_LABEL[s]).join(', ')}</span>}
          {done.outcome === 'cancelled' && <span className="badge" style={{ marginLeft: 6 }}>취소됨</span>}
        </span> : <span className="faint">{hasResult ? '' : '아직 계산하지 않았습니다'}</span>}
      {!progress && hasResult && (stale
        ? <span className="badge v-warn" title="조건을 바꾼 뒤 아직 계산하지 않았습니다. 아래 결과는 바꾸기 전 조건의 결과입니다.">{staleNote ?? '조건 변경됨 · 아래 결과는 이전 조건'}</span>
        : (done?.outcome === 'ok' || done?.outcome === 'partial') && <span className="badge v-ok" title="아래 결과는 지금 조건으로 계산한 결과입니다. 같은 조건으로 다시 계산해도 결과는 같습니다.">결과 = 현재 조건</span>)}
      <span className="grow" />
      {progress || busy
        ? <button className="btn" onClick={onStop} title="진행 중인 계산을 멈춥니다 (화면의 결과는 그대로 둡니다)">취소</button>
        : <button className={`btn ${stale || !hasResult ? 'primary' : ''}`} disabled={!canRun} onClick={onRun}
          title={stale ? '바뀐 조건으로 계산' : hasResult ? '조건이 같으므로 결과는 같습니다' : '계산'}>
          {stale ? '변경 반영 계산' : hasResult ? '다시 계산' : '계산'}</button>}
    </div>
  )
}
