import { fmt } from '../lib/timingBudget'
import { TimingVerdictBadge } from './TimingVerdictBadge'

/** One lever-axis combination: the variant with these levers changed, explored on its own (API ≥ 2026-11-13). */
export type DesignAxisResult = {
  key: string; labels: string[]; iq: 'neutral' | 'eval' | 'trade'; lever_notes?: string[]
  spec_ok: boolean; spec_reasons: string[]; verdict: string; fps: number
  total_mw: number | null; delta_mw: number | null; delta_pct: number | null
  bw_mbs: number | null; delta_bw_mbs: number | null
  raw_total_mw: number; raw_delta_mw: number; raw_delta_pct: number | null
  zero_power_ips?: string[]; power_coverage?: string
}
export type DesignAxes = {
  status: 'ok' | 'none' | 'failed'
  dimensions: { lever: string; label: string; selector: string | null; group: string; values: string[] }[]
  notes: string[]; sets: number; max_sets: number; cases: number
  results: DesignAxisResult[]; errors: { key: string; error: string }[]
}

const IQ_TEXT: Record<DesignAxisResult['iq'], string> = { neutral: '', eval: 'IQ 평가 필요', trade: '화질 trade' }
const signed = (v: number | null | undefined, digits = 1) => (v == null ? '—' : `${v > 0 ? '+' : ''}${fmt(v, digits)}`)

/** S-01: every combination of the lever axes as a changed variant, compared with the variant itself.
 * Ordered by power, but nothing is recommended: a combination changes the requirement (fps, size, sensor …). */
export function DesignAxesTable({ data, baseMw }: { data: DesignAxes; baseMw: number | null }) {
  const failed = data.errors.length
  return <div className="dax">
    <div className="faint" style={{ fontSize: 12 }}>
      {data.dimensions.map((d) => `${d.label}: ${d.values.join(' / ')}`).join(' · ')} · {data.sets} 조합
      {baseMw != null ? ` · 기준 = 이 variant의 추천 조합 ${fmt(baseMw, 1)} mW` : ' · 이 variant에 추천 조합이 없어 Δ는 압축 전 기준만 표시'}
    </div>
    {data.results.length > 0 && <table className="tb-mini-table" style={{ width: '100%' }}>
      <thead><tr><th>변경한 레버</th><th>판정</th><th className="n">fps</th><th className="n">total mW</th><th className="n">Δ mW</th>
        <th className="n">Δ BW MB/s</th><th className="n">압축 전 Δ mW</th><th>주의</th></tr></thead>
      <tbody>{data.results.map((r) => {
        const cautions = [IQ_TEXT[r.iq], r.power_coverage === 'partial' ? `전력 미모델 IP ${r.zero_power_ips?.length ?? 0}개` : '',
          ...(r.spec_ok ? [] : r.spec_reasons.slice(0, 2))].filter(Boolean)
        return <tr key={r.key}>
          <td>{r.labels.join(' + ')}{(r.lever_notes ?? []).length > 0 && <div className="faint" style={{ fontSize: 12 }}>{r.lever_notes!.join(' · ')}</div>}</td>
          <td><TimingVerdictBadge status={r.verdict === 'not_applicable' ? 'not_applicable' : r.spec_ok ? 'ok' : 'fail'} /></td>
          <td className="n">{fmt(r.fps, 0)}</td>
          <td className="n">{r.total_mw == null ? '—' : fmt(r.total_mw, 1)}</td>
          <td className="n">{signed(r.delta_mw)}{r.delta_pct != null && <span className="faint"> ({signed(r.delta_pct)}%)</span>}</td>
          <td className="n">{signed(r.delta_bw_mbs, 0)}</td>
          <td className="n">{signed(r.raw_delta_mw)}{r.raw_delta_pct != null && <span className="faint"> ({signed(r.raw_delta_pct)}%)</span>}</td>
          <td className={r.spec_ok ? 'faint' : 'err'} style={{ margin: 0 }}>{cautions.join(' · ') || '—'}</td>
        </tr>
      })}</tbody>
    </table>}
    {data.status === 'none' && <div className="empty">이 run에 레버 축 조합이 없습니다.</div>}
    {failed > 0 && <details className="faint" style={{ fontSize: 12 }}>
      <summary>이 variant에 적용하지 못한 조합 {failed}개</summary>
      <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{data.errors.map((e) => <li key={e.key}><span className="mono">{e.key}</span> — {e.error}</li>)}</ul>
    </details>}
    {data.notes.map((n) => <div key={n} className="faint" style={{ fontSize: 12 }}>{n}</div>)}
    <div className="faint" style={{ fontSize: 12 }}>
      조합마다 variant를 바꿔 다시 탐색한 결과입니다 (추천 SW 조건 · 자체 압축/DVFS 탐색). 요구 조건이 달라지는 변경이라 power 순으로만 정렬하고 추천하지 않으며, 여기서 예측으로 등록되지 않습니다.
    </div>
  </div>
}
