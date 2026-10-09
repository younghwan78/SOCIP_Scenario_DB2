// 예측 현황 · 발열 대응: scenarios where customers usually ask for power reduction (board thermal) — what each lever saves
// from the IQ/performance-keeping baseline, what it costs, and whether a 10 / 20 % ask is reachable without dropping fps.
import { fmt } from '../lib/timingBudget'
import { maText, type Battery } from '../lib/battery'
import { IQ_CLASS, IQ_LABEL, JUDGE_CLASS, JUDGE_LABEL, tradeText, type ReductionPlan, type ThermalWatch } from '../lib/review'

const KIND: Record<string, string> = { dvfs: 'IP clock', lossy: 'Compression', option: 'Power option' }
const planTag = (p: ReductionPlan) => (!p.iq_cost ? '· 무손실' : (p.iq_pending?.length ?? 1) === 0 ? '· IQ 승인됨' : '· IQ 평가')

export function ThermalWatchView({ data, battery, onOpen }: { data: ThermalWatch; battery: Battery; onOpen?: (scenario: string, variant: string) => void }) {
  if (!data.items.length) return <div className="empty">project review_policy에 thermal_watch가 없습니다.</div>
  return <div style={{ display: 'grid', gap: 14 }}>
    {data.items.map((it) => {
      const base = it.current_mw
      return <section key={`${it.scenario_id}|${it.variant_id}`} className="tw-item">
        <div className="tw-head">
          <b>{it.label}</b> <span className="mono faint" style={{ fontSize: 11 }}>{it.variant_id}</span>
          {it.note && <span className="faint" style={{ fontSize: 11.5 }}>· {it.note}</span>}
          <span className="grow" />
          {base !== null && <span className="mono"><b>{fmt(base, 0)}</b> mW <span className="faint">({maText(base, battery)})</span></span>}
          <span className="chip" title="기준 = lossy 압축·IQ option 없이 fps를 만족하는 최저 power (조합 탐색 tier A)">{it.baseline === 'iq_keep' ? '기준: 화질 유지 최적' : '기준: 등록 예측'}</span>
          {it.reference && <span className={`badge ${JUDGE_CLASS[it.reference.status]}`} title={`전과제 ${fmt(it.reference.reference_mw, 0)} mW (${it.reference.source})`}>
            전과제 {JUDGE_LABEL[it.reference.status]} {it.reference.delta_mw >= 0 ? '+' : ''}{fmt(it.reference.delta_mw, 0)} mW</span>}
          {onOpen && <button className="btn tb-mini" onClick={() => onOpen(it.scenario_id, it.variant_id)}>Timing Budget →</button>}
        </div>
        {it.menu.length > 0 && <table className="tb-mini-table" style={{ width: '100%' }}>
          <thead><tr><th>Lever</th><th>항목</th><th style={{ textAlign: 'right' }}>Δ mW</th><th style={{ textAlign: 'right' }}>Δ mA@Vbat</th><th style={{ textAlign: 'right' }}>기준 대비</th><th>희생 · 조건</th>
            {it.plans.map((p) => <th key={p.ask_pct} style={{ textAlign: 'center' }}>−{fmt(p.ask_pct, 0)}% 안</th>)}</tr></thead>
          <tbody>{it.menu.map((m) => <tr key={m.key} className={m.feasible ? '' : 'row-off'}>
            <td className="faint" style={{ fontSize: 11.5 }}>{KIND[m.kind]}</td>
            <td>{m.label}{m.always_beneficial && <span className="badge v-info" style={{ marginLeft: 4 }}>항상 이득</span>}
              {m.iq_status && <span className={`badge ${IQ_CLASS[m.iq_status]}`} style={{ marginLeft: 4 }} title={m.review?.note ? `${m.review.note}${m.review.updated_by ? ` — ${m.review.updated_by}` : ''}` : '조합 탐색 · power option 검토에서 상태 변경'}>{IQ_LABEL[m.iq_status]}</span>}</td>
            <td className="mono" style={{ textAlign: 'right', color: m.feasible ? 'var(--primary-strong)' : undefined }}>{fmt(m.delta_mw, 1)}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{maText(m.delta_mw, battery, true)}</td>
            <td className="mono faint" style={{ textAlign: 'right' }}>{base ? `${fmt((100 * m.delta_mw) / base, 1)}%` : '—'}</td>
            <td style={{ fontSize: 11.5, color: m.feasible ? undefined : 'var(--del-text)' }}>{m.cost}</td>
            {it.plans.map((p) => <td key={p.ask_pct} style={{ textAlign: 'center' }}>{p.picked.includes(m.key) ? '●' : ''}</td>)}
          </tr>)}</tbody>
          <tfoot><tr><td colSpan={6} className="faint" style={{ fontSize: 11.5 }}>합계 (위 ● 조합, 항목 효과 합 — 근사)</td>
            {it.plans.map((p) => <td key={p.ask_pct} style={{ textAlign: 'center' }}>
              <span className={`badge ${p.achieved ? (p.iq_cost ? 'v-warn' : 'v-ok') : 'v-fail'}`} title={`필요 ${fmt(p.need_mw, 0)} mW`}>
                {fmt(p.saving_mw, 0)} mW {p.achieved ? planTag(p) : '· 부족'}</span></td>)}</tr>
            {(it.approved_plans?.length ?? 0) > 0 && <tr><td colSpan={6} className="faint" style={{ fontSize: 11.5 }}>IP clock + IQ 승인 항목 절감 추정 (조합 검증 필요)</td>
              {it.approved_plans!.map((p) => <td key={p.ask_pct} style={{ textAlign: 'center' }}>
                <span className={`badge ${p.achieved ? 'v-ok' : 'v-fail'}`} title={p.picked.join(', ') || '적용 가능 항목 없음'}>{fmt(p.saving_mw, 0)} mW {p.achieved ? '· 가능' : '· 부족'}</span></td>)}</tr>}
          </tfoot>
        </table>}
        {(it.trades?.length ?? 0) > 0 && <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 12, fontWeight: 600 }}>성능 trade 후보 <span className="faint" style={{ fontWeight: 400 }}>— 같은 camera에서 fps · 해상도를 낮춘 variant의 등록 예측 (고객 협의 필요)</span></div>
          <table className="tb-mini-table" style={{ width: '100%' }}>
            <thead><tr><th>변경</th><th>Variant</th><th style={{ textAlign: 'right' }}>Power mW</th><th style={{ textAlign: 'right' }}>Δ mW</th><th style={{ textAlign: 'right' }}>Δ mA@Vbat</th><th style={{ textAlign: 'right' }}>기준 대비</th></tr></thead>
            <tbody>{it.trades!.map((t) => <tr key={t.variant_id}>
              <td style={{ fontSize: 12 }}>{t.changes.map(tradeText).join(' · ')}</td>
              <td className="mono" style={{ fontSize: 11 }} title={t.also?.length ? `같은 변경: ${t.also.join(', ')}` : undefined}>{t.variant_id}{t.also?.length ? ` +${t.also.length}` : ''}</td>
              <td className="mono" style={{ textAlign: 'right' }}>{fmt(t.total_mw, 0)}</td>
              <td className="mono" style={{ textAlign: 'right', color: 'var(--primary-strong)' }}>{fmt(t.delta_mw, 0)}</td>
              <td className="mono" style={{ textAlign: 'right' }}>{maText(t.delta_mw, battery, true)}</td>
              <td className="mono faint" style={{ textAlign: 'right' }}>{t.delta_pct !== null ? `${fmt(t.delta_pct, 1)}%` : '—'}</td>
            </tr>)}</tbody>
          </table>
        </div>}
        {it.notes.length > 0 && <ul className="faint" style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 12 }}>{it.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
      </section>
    })}
    <div className="faint" style={{ fontSize: 11.5 }}>
      순서 = 비용 낮은 lever 먼저 (IP clock ↓: fps 유지 시에만 · IQ 승인 option · compression lossy · 미평가 option), 같은 종류는 절감 큰 순 · 회색 = fps drop 또는 IQ 반려라 제외.
      fps는 절대 낮추지 않으며, IQ 항목은 화질 평가 후 채택합니다. 해상도·fps·EIS 변경은 다른 variant로 Compare에서 비교합니다.
    </div>
  </div>
}

