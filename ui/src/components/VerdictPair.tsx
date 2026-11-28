import { KPI_CHIP, verdictChip, type KpiResult, type KpiStatus, type Verdict } from '../lib/timingBudget'
import { scopeText } from '../lib/verdictNotes'
import { kpiLabel } from '../lib/timingTiles'
import { Hint } from './Hint'
import { Term } from './Term'

const ORDER: KpiStatus[] = ['fail', 'no_input', 'unmodeled', 'pass', 'no_target']

/** "KPI 통과 2" / "KPI 미달 1 (heap) · 통과 3" / "KPI 통과 4 · 목표 없음 2" / null when no KPI is declared.
 * Every status with a count is listed (a reference-only "목표 없음" must not hide the passes); the colour is
 * the worst judged status — a target-less KPI alone never colours the cell. */
export function kpiPairText(k: Verdict['kpis'], rows?: KpiResult[] | null): { cls: string; text: string; status: KpiStatus } | null {
  if (!k?.status) return null
  const count = (s: KpiStatus) => k[s] ?? (rows ?? []).filter((r) => r.status === s).length
  const present = ORDER.filter((s) => count(s) > 0)
  const lead = present.find((s) => s !== 'no_target') ?? present[0] ?? k.status
  const names = (rows ?? []).filter((r) => r.status === 'fail').map(kpiLabel)
  const more = names.length > 2 ? ` 외 ${names.length - 2}` : ''
  const parts = (present.length ? present : [k.status]).map((s) => {
    const label = KPI_CHIP[s]?.[1] ?? s
    const n = count(s)
    return `${label}${n ? ` ${n}` : ''}${s === 'fail' && names.length ? ` (${names.slice(0, 2).join(', ')}${more})` : ''}`
  })
  return { cls: KPI_CHIP[lead]?.[0] ?? 'v-na', status: lead, text: `KPI ${parts.join(' · ')}` }
}

/** X-04: the verdict has two axes — timing and KPI — so the badge has two cells. The timing cell keeps the
 * TimingVerdictBadge words; the scope explanation (why timing does not apply) sits in a Hint next to it. */
export function VerdictPair({ verdict, kpis, fpsSource, compact = false }: { verdict: Verdict; kpis?: KpiResult[] | null; fpsSource?: string | null; compact?: boolean }) {
  const chip = verdictChip(verdict.status)
  const t = { ...chip, label: chip.label.replace(/^timing /, '') }
  const k = kpiPairText(verdict.kpis, kpis)
  const scope = scopeText(verdict.notes, fpsSource)
  return <span className="verdict-pair" data-testid="verdict-pair">
    <span className="verdict-cell">
      {!compact && <span className="faint t-caption"><Term id="timing-verdict">Timing</Term></span>}
      <span className={`badge ${t.cls}`} title={verdict.reasons.join('\n') || undefined} data-testid="verdict-timing">{compact ? `Timing ${t.label}` : t.label}</span>
      {scope && !compact && <Hint label="판정 범위" text={scope} />}
    </span>
    {k && <span className="verdict-cell">
      {!compact && <span className="faint t-caption"><Term id="kpi-verdict">KPI</Term></span>}
      <span className={`badge ${k.cls}`} data-testid={`verdict-kpi-${k.status}`}>{compact ? k.text : k.text.replace(/^KPI /, '')}</span>
    </span>}
  </span>
}
