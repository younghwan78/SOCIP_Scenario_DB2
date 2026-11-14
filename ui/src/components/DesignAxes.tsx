import { fmt } from '../lib/timingBudget'
import { TimingVerdictBadge } from './TimingVerdictBadge'
import { SpecBadge } from './SpecBadge'

/** One lever-axis combination: the variant with these levers changed, explored on its own (API ≥ 2026-11-13). */
export type DesignAxisResult = {
  key: string; labels: string[]; lever_notes?: string[]
  /** iq = worst of the levers' own class (`lever_iq`) and the combination's compression pick (`lossy` = trade) */
  iq: 'neutral' | 'eval' | 'trade'; lever_iq?: 'neutral' | 'eval' | 'trade'; lossy?: boolean
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
  /** API ≥ 2026-11-14: combinations not explored because the case budget ran out */
  skipped?: number
  results: DesignAxisResult[]; errors: { key: string; error: string }[]
  /** API ≥ 2026-11-13: exhaustive = every combination; screened = each value alone, then the top levers combined */
  search?: DesignSearch
}
export type DesignSearch = {
  mode: 'exhaustive' | 'screened'; full_factorial: number; one_at_a_time: number; combined: number
  ranking?: { lever: string; label: string; impact_mw: number | null; impact_pct: number | null; combined: boolean }[]
}

/** How much of the lever space the rows cover — a screened search must never read as the full one. */
export function SearchCoverage({ search, evaluated, skipped = 0 }: { search: DesignSearch; evaluated: number; skipped?: number }) {
  const budget = skipped > 0 ? ` case 예산 소진으로 ${skipped}개 조합은 탐색하지 못했습니다 (max_cases_per_variant).` : ''
  if (search.mode === 'exhaustive') {
    return skipped > 0
      ? <div className="dax-search"><span className="badge v-warn">부분 탐색</span> 레버 조합 {search.full_factorial}개 중 {evaluated}개 탐색 —{budget} 탐색하지 않은 조합에 더 낮은 전력이 있을 수 있습니다.</div>
      : <div className="dax-search"><span className="badge v-ok">전수 탐색</span> 레버 조합 {search.full_factorial}개를 모두 탐색</div>
  }
  const ranking = search.ranking ?? []
  const ranked = ranking.some((r) => r.impact_mw != null)
  return <div className="dax-search">
    <div><span className="badge v-warn">부분 탐색</span> 전체 {search.full_factorial} 조합 중 {evaluated}개 탐색 — 값 하나씩 {search.one_at_a_time}개
      {search.combined ? ` + 영향이 큰 레버끼리 조합 ${search.combined}개` : ' (조합은 탐색하지 않음)'}.{budget} 탐색하지 않은 조합에 더 낮은 전력이 있을 수 있습니다.</div>
    {ranked
      ? <ol className="dax-rank">{ranking.map((r, i) => <li key={i}>
        <b>{r.label}</b> {r.impact_mw == null ? '단독 결과 없음' : `단독 영향 최대 ±${fmt(r.impact_mw, 1)} mW${r.impact_pct != null ? ` (${fmt(r.impact_pct, 1)}%)` : ''}`}
        <span className={r.combined ? 'badge v-ok' : 'badge'}>{r.combined ? '조합 포함' : '단독만'}</span></li>)}</ol>
      : <div className="faint">단독으로 탐색된 레버 값이 없어 순위를 매기지 못했습니다 (이 variant에 적용할 수 없거나 case 예산 소진 — 아래 사유 참고).</div>}
  </div>
}

const IQ_TEXT: Record<DesignAxisResult['iq'], string> = { neutral: '', eval: 'IQ 평가 필요', trade: '화질 trade' }
/** what to check about image quality: the levers' own need, and a lossy pick of the combination's compression search */
function iqCautions(r: DesignAxisResult): string[] {
  const lever = r.lever_iq ?? r.iq
  return [IQ_TEXT[lever] && `레버 ${IQ_TEXT[lever]}`, r.lossy ? 'lossy 압축 선택 (화질 trade) — 표시 전력은 손실 압축 기준' : '']
    .filter((t): t is string => !!t)
}
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
    {data.search && <SearchCoverage search={data.search} evaluated={data.results.length + data.errors.length} skipped={data.skipped ?? 0} />}
    {data.results.length > 0 && <table className="tb-mini-table" style={{ width: '100%' }}>
      <thead><tr><th>변경한 레버</th><th>판정</th><th className="n">fps</th><th className="n">total mW</th><th className="n">Δ mW</th>
        <th className="n">Δ BW MB/s</th><th className="n">압축 전 Δ mW</th><th>주의</th></tr></thead>
      <tbody>{data.results.map((r) => {
        const cautions = [...iqCautions(r), r.power_coverage === 'partial' ? `전력 미모델 IP ${r.zero_power_ips?.length ?? 0}개` : '',
          ...(r.spec_ok ? [] : r.spec_reasons.slice(0, 2))].filter(Boolean)
        return <tr key={r.key}>
          <td>{r.labels.join(' + ')}{(r.lever_notes ?? []).length > 0 && <div className="faint" style={{ fontSize: 12 }}>{r.lever_notes!.join(' · ')}</div>}</td>
          <td>{r.verdict === 'not_applicable' ? <TimingVerdictBadge status="not_applicable" /> : <SpecBadge ok={r.spec_ok} />}</td>
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
