import { fmt } from '../lib/timingBudget'

/** S-02: what the objective order chose, the lowest-power case, and the power ↔ SW growth front (API ≥ 2026-11-14). */
export type ObjectivePoint = {
  key: string; total_mw: number; growth_fixed: number; bw_mbs: number; iq_risk: number; dvfs_raise: number
  delta_mw: number; growth_at_least?: number
}
export type Objectives = {
  order: ('power' | 'growth' | 'iq' | 'bw')[]; growth_target: number | null; target_met: boolean | null
  recommended: ObjectivePoint | null; min_power: ObjectivePoint | null; front: ObjectivePoint[]
}

export const OBJECTIVE_LABEL: Record<Objectives['order'][number], string> = {
  power: '최저 power', growth: 'SW 증가 여유', iq: 'IQ 유지', bw: '최저 BW',
}
const IQ_RISK = ['압축 없음', 'lossless', '가정 ratio', 'lossy']
const growthText = (g: number) => (g > 0 ? `×${fmt(g, 2).replace(/0$/, '')}` : '여유 없음')

/** The recommendation rule in words, then the cheapest case per SW growth level its own DVFS levels absorb. */
export function ObjectiveFront({ data }: { data: Objectives }) {
  const rec = data.recommended, low = data.min_power
  if (!rec || !low) return <div className="empty">등록 가능한 조합이 없어 추천 기준을 적용하지 못했습니다.</div>
  const same = rec.key === low.key
  return <div className="obj-front">
    <div>
      <b>추천 기준</b> {data.order.map((o) => OBJECTIVE_LABEL[o]).join(' → ')}
      {data.growth_target != null && <> · 목표 SW 증가 {growthText(data.growth_target)}
        <span className={`badge ${data.target_met ? 'v-ok' : 'v-fail'}`} style={{ marginLeft: 6 }}>{data.target_met ? '목표 충족' : '목표 미달'}</span></>}
    </div>
    <div className="faint" style={{ fontSize: 13 }}>
      {same
        ? `추천 조합이 최저 power 조합과 같습니다 (${fmt(rec.total_mw, 1)} mW · SW 증가 여유 ${growthText(rec.growth_fixed)}).`
        : `추천 ${fmt(rec.total_mw, 1)} mW · SW 증가 여유 ${growthText(rec.growth_fixed)} — 최저 power 조합(${fmt(low.total_mw, 1)} mW · ${growthText(low.growth_fixed)})보다 +${fmt(rec.delta_mw, 1)} mW`}
    </div>
    <table className="tb-mini-table" style={{ width: '100%' }}>
      <thead><tr><th>SW 증가 여유 (DVFS 고정)</th><th className="n">total mW</th><th className="n">최저 power 대비</th><th className="n">DVFS 상향</th>
        <th className="n">BW MB/s</th><th>압축</th><th></th></tr></thead>
      <tbody>{data.front.map((p) => <tr key={p.key}>
        <td>{growthText(p.growth_at_least ?? p.growth_fixed)} 까지</td>
        <td className="n">{fmt(p.total_mw, 1)}</td>
        <td className="n">{p.delta_mw > 0 ? `+${fmt(p.delta_mw, 1)}` : '—'}</td>
        <td className="n">{p.dvfs_raise ? `${p.dvfs_raise} domain` : '—'}</td>
        <td className="n">{fmt(p.bw_mbs, 0)}</td>
        <td className={p.iq_risk >= 3 ? 'err' : 'faint'} style={{ margin: 0 }}>{IQ_RISK[p.iq_risk] ?? '—'}</td>
        <td>{p.key === rec.key && <span className="badge v-ok">추천</span>}{p.key === low.key && <span className="badge">최저 power</span>}</td>
      </tr>)}</tbody>
    </table>
    <div className="faint" style={{ fontSize: 12 }}>
      SW 증가 여유 = 그 조합의 DVFS level을 그대로 둔 채 흡수하는 SW runtime 증가 (탐색한 증가 배율 단위). 행 = 그 여유를 내는 가장 싼 조합.
      {rec.key !== low.key && !data.front.some((p) => p.key === rec.key) ? ' 추천 조합은 다른 기준(IQ · BW)이 앞서 이 표의 행과 다를 수 있습니다.' : ''}
      {same ? '' : ' 일괄 등록은 최저 power 조합(또는 과제 정책의 IQ 유지 조합)을 등록합니다 — 추천 조합은 조합을 골라 등록 (규칙 auto:objective).'}
    </div>
  </div>
}
