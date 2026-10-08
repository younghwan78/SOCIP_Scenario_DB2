// 조합 탐색: two answers per variant, shown side by side (UX 2026-10-09)
//   A. 화질·성능 유지 — lowest power without lossy / assumed-ratio compression or IQ options, plus the window of
//      conditions within a few % of it (DVFS level range, compression) the project can choose from freely.
//   B. Power 우선 — what giving up IQ buys, lever by lever: lossy compression and each power option with its
//      *own* effect (conditional on the others), so an option that wins everywhere (e.g. L0 skip) no longer hides the rest.
import { fmt } from '../lib/timingBudget'
import type { VariantResult } from '../lib/archExplore'
import { maText, type Battery } from '../lib/battery'
import { signed } from './PowerOptions'

interface Lever { key: string; label: string; cost: string; mean: number; min: number; max: number; always: boolean; varies: boolean; contexts: number }

export function levers(v: VariantResult): Lever[] {
  const out: Lever[] = []
  const g = v.tiers?.trade_gain
  if (g && g.delta_mw < -0.05) {
    const bufs = v.tiers?.trade?.best.compression ?? []
    out.push({ key: 'lossy', label: `lossy compression (${bufs.join(', ') || 'buffer'})`, cost: g.iq_risk >= 3 ? 'IQ (lossy)' : 'IQ (가정 ratio)', mean: g.delta_mw, min: g.delta_mw, max: g.delta_mw, always: true, varies: false, contexts: 1 })
  }
  for (const m of v.power_options?.marginal ?? []) {
    const r = v.power_options?.results.find((x) => x.items.length === 1 && x.items[0] === m.key)
    out.push({ key: m.key, label: m.label, cost: r?.kinds.includes('ip_mode') ? 'IQ (IP mode)' : 'IQ (arch knob)', mean: m.mean_mw, min: m.min_mw, max: m.max_mw, always: m.always_beneficial, varies: m.sign_varies, contexts: m.contexts })
  }
  return out.sort((a, b) => a.mean - b.mean)
}

export function TiersView({ v, battery }: { v: VariantResult; battery: Battery }) {
  const t = v.tiers
  if (!t) return <div className="empty">이 run은 tier 정보가 없습니다 (API 갱신 후 다시 실행).</div>
  const keep = t.keep, trade = t.trade
  const lv = levers(v)
  let cum = 0
  const bestSet = v.power_options?.results.find((r) => r.key === v.power_options?.best)
  return (
    <div className="tiers">
      <section className="tier tier-keep">
        <h3>A · 화질·성능 유지 — 최적 조건 범위</h3>
        {!keep ? <div className="empty">lossless / 무압축으로 timing을 만족하는 조합이 없습니다.</div> : <>
          <div className="tier-big"><span className="mono">{fmt(keep.best.total_mw, 1)}</span> mW <span className="faint">({maText(keep.best.total_mw, battery)}) · {fmt(keep.best.bw_mbs / 1000, 2)} GB/s</span></div>
          <table className="tb-mini-table" style={{ width: '100%' }}><tbody>
            <tr><td>최적 ±{fmt(keep.near_pct, 0)}% 범위</td><td className="mono">{keep.near_cases}개 조합 · {fmt(keep.near_mw[0], 1)}–{fmt(keep.near_mw[1], 1)} mW · {fmt(keep.near_bw_mbs[0] / 1000, 2)}–{fmt(keep.near_bw_mbs[1] / 1000, 2)} GB/s</td></tr>
            <tr><td>DVFS level 범위</td><td className="mono">{Object.entries(keep.dvfs_range).map(([d, [a, b]]) => `${d} L${a}${a !== b ? `–L${b}` : ''}`).join(' · ') || '—'}</td></tr>
            <tr><td>Compression (lossless)</td><td className="mono" style={{ fontSize: 11.5 }}>{keep.compression_always.length ? `항상 ${keep.compression_always.join(', ')}` : '필수 없음'}{keep.compression_optional.length ? ` · 선택 ${keep.compression_optional.join(', ')}` : ''}</td></tr>
            <tr><td>SW 기준</td><td className="mono">{keep.best.statistic} ×{keep.best.runtime_scale} · 판정 {keep.best.verdict}</td></tr>
          </tbody></table>
          <div className="faint" style={{ fontSize: 11.5 }}>이 범위 안의 조건(위 DVFS level · compression)은 power 차이 ≤{fmt(keep.near_pct, 0)}% — 과제에서 조건이 바뀌어도 이 안이면 다시 예측할 필요가 없습니다.</div>
        </>}
      </section>
      <section className="tier tier-trade">
        <h3>B · Power 우선 — 화질 희생 메뉴</h3>
        {!lv.length ? <div className="empty">화질을 희생해 줄일 수 있는 항목이 없습니다 (lossy compression 불가 · power option 미선언).</div> : <>
          <table className="tb-mini-table" style={{ width: '100%' }}>
            <thead><tr><th>항목</th><th>희생</th><th style={{ textAlign: 'right' }} title="다른 option 조합과 관계없이 이 항목만 추가했을 때의 평균 Δ">단독 효과 mW</th><th style={{ textAlign: 'right' }} title="다른 option 유무에 따른 최소–최대">조합 영향</th><th style={{ textAlign: 'right' }} title="A(화질 유지 최적) 대비 효과 큰 순 누적 — option 효과는 lossy 추천 조합 기준이라 합은 근사">누적 (A 대비)</th></tr></thead>
            <tbody>{lv.map((l) => { cum += l.mean; return (
              <tr key={l.key}>
                <td>{l.label}{l.always && l.contexts > 1 && <span className="badge v-info" style={{ marginLeft: 4 }} title="모든 조합에서 이득 — 조합 순위 대신 단독 효과로 비교">항상 이득</span>}{l.varies && <span className="badge v-warn" style={{ marginLeft: 4 }} title="다른 option에 따라 이득/손해가 바뀜">조합 의존</span>}</td>
                <td className="faint" style={{ fontSize: 11.5 }}>{l.cost}</td>
                <td className="mono" style={{ textAlign: 'right', color: l.mean < 0 ? 'var(--primary-strong)' : 'var(--del-text)' }}><b>{signed(l.mean)}</b> <span className="faint" style={{ fontSize: 10.5 }}>{maText(l.mean, battery, true)}</span></td>
                <td className="mono faint" style={{ textAlign: 'right' }}>{l.contexts > 1 ? `${signed(l.min)} ~ ${signed(l.max)}` : '—'}</td>
                <td className="mono" style={{ textAlign: 'right' }}>{signed(cum)}</td>
              </tr>) })}</tbody>
          </table>
          {trade && keep && <div className="faint" style={{ fontSize: 11.5 }}>A 대비: lossy 최적 {fmt(trade.best.total_mw, 1)} mW{bestSet?.delta_mw != null ? ` · option 최적 조합(${bestSet.labels.join(' + ')}) ${signed(bestSet.delta_mw)} mW (추천 조합 대비)` : ''}. 각 항목은 IQ 평가 후 채택 — 예측 현황에서 평가 상태 관리.</div>}
        </>}
        <div className="faint" style={{ fontSize: 11 }}>성능 희생(fps · 해상도 · EIS off)은 다른 variant이므로 Compare / 예측 현황에서 variant끼리 비교합니다.</div>
      </section>
    </div>
  )
}
