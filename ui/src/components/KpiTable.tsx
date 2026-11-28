import { KPI_CHIP, type FleetRow, type KpiResult, type KpiStatus } from '../lib/timingBudget'
import { Term } from './Term'

const LABEL: Record<KpiStatus, string> = { pass: '통과', fail: '미달', no_target: '목표 없음', no_input: '입력 없음', unmodeled: '모델 없음' }
const BADGE: Record<KpiStatus, string> = { pass: 'v-ok', fail: 'v-fail', no_target: 'v-info', no_input: 'v-na', unmodeled: 'v-na' }
const TARGET_SRC: Record<string, [string, string, string]> = {
  spec: ['v-info', 'spec 목표', '제품 spec에서 온 목표'],
  assumed: ['v-na', '가정 목표', 'E2600 가정 목표 (제품 요구 아님)'],
}
const INPUT_SRC: Record<string, [string, string]> = { measured: ['v-ok', '실측'], fitted: ['v-info', '보정'], spec: ['v-info', 'spec'], assumed: ['v-na', '가정'] }

const num = (v: number | null) => (v == null ? '—' : Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2))
const key = (r: KpiResult, i: number) => `${r.id ?? r.kpi}-${r.job ?? ''}-${r.milestone ?? ''}-${r.metric ?? ''}-${i}`

/** X-12: a row is a reference value when it has no target (event energy, peak power …); those go below. */
export function splitKpiRows(rows: KpiResult[]): { judged: KpiResult[]; reference: KpiResult[] } {
  return { judged: rows.filter((r) => r.target != null || r.status !== 'no_target'), reference: rows.filter((r) => r.target == null && r.status === 'no_target') }
}

function Name({ r }: { r: KpiResult }) {
  return <td className="mono">{r.id ?? r.kpi}{r.id && <span className="faint"> · {r.kpi}</span>}{r.metric && <span className="faint">.{r.metric}</span>}</td>
}
function Inputs({ r }: { r: KpiResult }) {
  if (!r.sources.length) return <span className="faint">—</span>
  return <span className="kpi-src">{r.sources.map((s) => { const [cls, label] = INPUT_SRC[s] ?? ['v-na', s]; return <span key={s} className={`badge ${cls}`}>{label}</span> })}</span>
}
function Note({ r }: { r: KpiResult }) {
  if (!r.basis) return <span className="faint">—</span>
  return <details className="faint"><summary>note</summary><span className="t-caption">{r.basis}</span></details>
}

/** M-10 KPI registry rows: each declared KPI with its value, the R-6 target and the status. X-12 splits the
 * evidence into target source · input source · note, and lists target-less KPIs as reference values. */
export function KpiTable({ rows }: { rows: KpiResult[] }) {
  const { judged, reference } = splitKpiRows(rows)
  return <>
    {judged.length > 0 && <div style={{ overflowX: 'auto' }}><table className="tb-mini-table" style={{ width: '100%' }}>
      <thead>
        <tr><th>KPI</th><th>대상</th><th style={{ textAlign: 'right' }}>값</th><th style={{ textAlign: 'right' }}>목표</th><th><Term id="kpi-verdict">판정</Term></th><th>목표 출처</th><th>입력 출처</th><th>note</th></tr>
      </thead>
      <tbody>
        {judged.map((r, i) => {
          const ts = r.target != null && r.value_source ? TARGET_SRC[r.value_source] : undefined
          return <tr key={key(r, i)} data-testid={`kpi-${r.status}`}>
            <Name r={r} />
            <td className="faint">{[r.job, r.milestone].filter(Boolean).join(' · ') || '—'}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{num(r.value)} {r.value != null && r.unit}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{r.target == null ? '—' : `${r.bound === 'min' ? '≥' : '≤'} ${num(r.target)} ${r.unit}`}</td>
            <td><span className={`badge ${BADGE[r.status]}`}>{LABEL[r.status]}</span></td>
            <td>{ts ? <span className={`badge ${ts[0]}`} title={ts[2]}>{ts[1]}</span> : r.value_source && r.target != null ? <span className="badge v-na">{r.value_source}</span> : <span className="faint">—</span>}</td>
            <td><Inputs r={r} /></td>
            <td><Note r={r} /></td>
          </tr>
        })}
      </tbody>
    </table></div>}
    {reference.length > 0 && <div data-testid="kpi-reference" style={{ marginTop: 8 }}>
      <div className="faint t-caption">참고 값 — 목표가 없는 KPI (판정 안 함)</div>
      <div style={{ overflowX: 'auto' }}><table className="tb-mini-table" style={{ width: '100%' }}>
        <tbody>{reference.map((r, i) => <tr key={key(r, i)} data-testid="kpi-no_target">
          <Name r={r} /><td className="faint">{[r.job, r.milestone].filter(Boolean).join(' · ') || '—'}</td>
          <td className="mono" style={{ textAlign: 'right' }}>{num(r.value)} {r.value != null && r.unit}</td>
          <td><Inputs r={r} /></td><td><Note r={r} /></td></tr>)}</tbody>
      </table></div>
    </div>}
  </>
}

/** M-12: the worst KPI status of a fleet row and how many targeted KPIs pass (absent = no KPI declared). */
export function KpiCell({ r }: { r: FleetRow }) {
  const s = r.verdict.kpis?.status
  if (!s) return <span className="faint">—</span>
  const [cls, label] = KPI_CHIP[s] ?? ['v-na', s]
  const n = (r.kpis ?? []).filter((x) => x.status === 'pass').length
  return <span data-testid={`fleet-kpi-${s}`}><span className={`badge ${cls}`}>{label}</span>{r.kpis?.length ? <span className="faint"> {n}/{r.kpis.length}</span> : null}</span>
}
