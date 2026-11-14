import type { ReactNode } from 'react'
import { TimingVerdictBadge } from './TimingVerdictBadge'
import type { Conclusion } from '../lib/conclusion'
import { fmt } from '../lib/timingBudget'

const signed = (v: number, d = 1) => `${v > 0 ? '+' : ''}${fmt(v, d)}`

/** A decision at the top of a result: what would be registered, its verdict, the change against the
 * reference, at most three cautions and the action. The evidence stays in the cards below (U-03).
 * Generic so other result screens (CPU what-if) can use the same layout. */
export function DecisionCard({ title, verdict, reasons = [], target, delta, cautions, more = 0, action, extra }: {
  title: string
  verdict: 'ok' | 'fail' | 'not_applicable'
  reasons?: string[]
  /** one line: what is registered */
  target: ReactNode
  /** one line: the change against the reference */
  delta?: ReactNode
  cautions: string[]
  more?: number
  action?: ReactNode
  extra?: ReactNode
}) {
  return <section className="decision" aria-label={title}>
    <div className="decision-head">
      <b>{title}</b>
      <TimingVerdictBadge status={verdict === 'not_applicable' ? 'not_applicable' : verdict === 'ok' ? 'ok' : 'fail'} />
    </div>
    <dl className="decision-facts">
      <dt>등록 대상</dt><dd>{target}</dd>
      {delta && <><dt>baseline 대비</dt><dd>{delta}</dd></>}
      {reasons.length > 0 && <><dt>판정 사유</dt><dd className="err">{reasons.slice(0, 2).join(' · ')}</dd></>}
    </dl>
    {cautions.length > 0
      ? <ul className="decision-cautions">{cautions.map((c) => <li key={c}>{c}</li>)}
        {more > 0 && <li className="faint">외 {more}건 — 아래 근거 tab</li>}</ul>
      : <div className="faint decision-cautions">주의 사항 없음 (전력 모델 완전 · 무손실 · catalog ratio)</div>}
    {extra}
    {action && <div className="decision-action">{action}</div>}
  </section>
}

/** The exploration conclusion of one variant as a decision card. */
export function ExplorationDecision({ c, action }: { c: Conclusion; action?: ReactNode }) {
  const t = c.target
  return <DecisionCard title="결론" verdict={c.verdict} reasons={c.reasons} cautions={c.cautions} more={c.more} action={action}
    target={t ? <><span className="mono"><b>{fmt(t.total_mw, 1)}</b> mW</span> · {c.targetLabel} <span className="faint mono">({c.rule})</span>
      <div className="faint mono" style={{ fontSize: 12 }}>{t.statistic} ×{t.runtime_scale} · {t.compression.length ? `${t.compression.length} buffer 압축` : '무압축'} · DVFS {Object.entries(t.dvfs).map(([d, l]) => `${d}:${l}`).join(' ') || '—'}</div></>
      : <span className="err">등록할 eligible 조합 없음</span>}
    delta={c.delta ? <span className="mono">{signed(c.delta.total_mw)} mW{c.delta.total_pct != null ? ` (${signed(c.delta.total_pct)}%)` : ''} · BW {signed(c.delta.bw_mbs, 0)} MB/s</span> : undefined} />
}
