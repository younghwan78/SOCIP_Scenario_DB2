// Scenario page: why a registered prediction got OK / Clock↑ / Fail.
import { useEffect, useRef } from 'react'
import type { VerdictDetail } from '../lib/archExplore'
import { fmt, verdictChip } from '../lib/timingBudget'

export const VERDICT_HELP = 'OK = 모든 stage가 budget 안 · Clock↑ = 맞추려면 NRT clock을 25% rule보다 5% 넘게 올려야 함 · Fail = SW가 budget을 다 쓰거나 RT HW·출력 간격 위반. 등록 예측(simulation) 기준이며 실측 판정이 아닙니다.'

export function VerdictPopover({ d, at, onClose, onTiming }: { d: VerdictDetail; at: { x: number; y: number }; onClose: () => void; onTiming?: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    const click = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) onClose() }
    window.addEventListener('keydown', key)
    const t = setTimeout(() => window.addEventListener('mousedown', click), 0)
    return () => { window.removeEventListener('keydown', key); window.removeEventListener('mousedown', click); clearTimeout(t) }
  }, [onClose])
  const chip = verdictChip(d.status as 'ok' | 'clock_up' | 'fail')
  const left = Math.min(at.x, window.innerWidth - 440), top = Math.min(at.y + 8, window.innerHeight - 360)
  return (
    <div ref={ref} className="verdict-pop" role="dialog" aria-label="판정 상세" style={{ left: Math.max(8, left), top: Math.max(8, top) }}>
      <div className="vp-head"><span className={`badge ${chip.cls}`}>{chip.label}</span>
        <b>{d.status === 'ok' ? '모든 stage가 budget 안' : d.status === 'clock_up' ? 'NRT clock 상향 필요' : 'timing 위반'}</b>
        <span className="grow" /><button className="btn tb-mini" aria-label="닫기" onClick={onClose}>✕</button></div>
      {d.reasons.length > 0 && <ul className="vp-reasons">{d.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
      {d.nrt_clock_factor !== null && <div className="vp-kv"><span>NRT clock</span><span className="mono">25% rule 대비 ×{fmt(d.nrt_clock_factor, 2)}{d.nrt_clock_factor > 1.05 ? ' (상향)' : ''}</span></div>}
      {d.stages.length > 0 && <table className="tb-mini-table" style={{ width: '100%', marginTop: 6 }}>
        <thead><tr><th>stage</th><th style={{ textAlign: 'right' }}>SW</th><th style={{ textAlign: 'right' }}>HW</th><th style={{ textAlign: 'right' }}>budget</th><th style={{ textAlign: 'right' }}>margin</th><th style={{ textAlign: 'right' }}>점유</th></tr></thead>
        <tbody>{d.stages.map((s) => { const bad = s.feasible === false || (s.id === 'rt' && (s.hw_ms ?? 0) > (s.budget_ms ?? Infinity) * 1.0001)
          return <tr key={s.id} className={bad ? 'vp-bad' : ''}><td>{s.name ?? s.id}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{s.sw_ms === undefined ? '—' : fmt(s.sw_ms, 2)}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{s.hw_ms === undefined ? '—' : fmt(s.hw_ms, 2)}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{s.budget_ms === undefined ? '—' : fmt(s.budget_ms, 2)}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{s.margin === undefined ? '—' : `${fmt(100 * s.margin, 0)}%`}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{s.fill_pct === undefined ? '—' : `${fmt(s.fill_pct, 0)}%`}</td></tr> })}</tbody>
      </table>}
      {(Object.keys(d.intervals).length > 0 || d.latency) && <div className="vp-kv" style={{ marginTop: 6 }}><span>출력 간격 max</span>
        <span className="mono">{Object.entries(d.intervals).map(([k, v]) => `${k} ${fmt(v, 2)}`).join(' · ') || '—'}{d.period_ms ? ` ms (주기 ${fmt(d.period_ms, 2)})` : ''}</span></div>}
      {d.latency && <div className="vp-kv"><span>지연</span><span className="mono">{Object.entries(d.latency).filter(([k, v]) => v !== null && k.endsWith('_ms')).map(([k, v]) => `${k.replace('_ms', '')} ${fmt(v as number, 1)} ms`).join(' · ') || '—'}</span></div>}
      <div className="vp-kv"><span>조건</span><span className="mono">SW {d.statistic ?? '—'} · 증가 ×{d.runtime_scale ?? 1}</span></div>
      <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>{d.derived ? '이 예측은 사유가 저장되기 전에 등록되어 stage·간격으로 다시 계산한 사유입니다. ' : ''}{VERDICT_HELP}</div>
      {onTiming && <div style={{ marginTop: 6 }}><button className="btn tb-mini" onClick={onTiming}>Timing Budget에서 보기 →</button></div>}
    </div>
  )
}
