import type { KpiResult, KpiStatus } from '../lib/timingBudget'

const LABEL: Record<KpiStatus, string> = { pass: '통과', fail: '미달', no_target: '목표 없음', no_input: '입력 없음', unmodeled: '모델 없음' }
const BADGE: Record<KpiStatus, string> = { pass: 'v-ok', fail: 'v-fail', no_target: 'v-info', no_input: 'v-na', unmodeled: 'v-na' }

const num = (v: number | null) => (v == null ? '—' : Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2))

/** M-10 KPI registry rows: each declared KPI with its value, the R-6 target and the status. */
export function KpiTable({ rows }: { rows: KpiResult[] }) {
  return (
    <table className="tb-mini-table" style={{ width: '100%' }}>
      <thead>
        <tr><th>KPI</th><th>대상</th><th style={{ textAlign: 'right' }}>값</th><th style={{ textAlign: 'right' }}>목표</th><th>판정</th><th>근거</th></tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.id ?? r.kpi}-${r.job ?? ''}-${r.milestone ?? ''}-${r.metric ?? ''}-${i}`} data-testid={`kpi-${r.status}`}>
            <td className="mono">{r.id ?? r.kpi}{r.id && <span className="faint"> · {r.kpi}</span>}{r.metric && <span className="faint">.{r.metric}</span>}</td>
            <td className="faint">{[r.job, r.milestone].filter(Boolean).join(' · ') || '—'}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{num(r.value)} {r.value != null && r.unit}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{r.target == null ? '—' : `${r.bound === 'min' ? '≥' : '≤'} ${num(r.target)} ${r.unit}`}</td>
            <td><span className={`badge ${BADGE[r.status]}`}>{LABEL[r.status]}</span></td>
            <td className="faint">
              {[
                r.value_source === 'assumed' && r.target != null ? <span key="a" title="E2600 가정 목표 (제품 요구 아님)">가정 목표</span> : null,
                r.value_source === 'spec' ? <span key="s">spec</span> : null,
                r.basis ? <span key="b">{r.basis}</span> : null,
                r.sources.length > 0 ? <span key="i">입력 {r.sources.join(' / ')}</span> : null,
              ].filter(Boolean).flatMap((el, k) => (k ? [<span key={`sep${k}`}> · </span>, el] : [el]))}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
