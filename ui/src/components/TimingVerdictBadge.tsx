import { verdictChip } from '../lib/timingBudget'

/** The unsupported verdict always carries a visible explanation, including in tables. */
export function TimingVerdictBadge({ status, reasons = [] }: { status: string; reasons?: string[] }) {
  const chip = verdictChip(status)
  return <span style={chip.explanation ? { whiteSpace: 'normal' } : undefined}>
    <span className={`badge ${chip.cls}`} title={reasons.join('\n')}>{chip.label}</span>
    {chip.explanation && <span className="faint" style={{ display: 'block', fontSize: 12 }}>{chip.explanation}</span>}
  </span>
}
