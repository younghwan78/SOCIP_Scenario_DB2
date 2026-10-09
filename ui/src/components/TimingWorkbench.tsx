// Timing Budget = prediction workbench: the condition (summary + actions), DVFS level override per domain and the
// ③ interval / latency spread under per-frame SW variance.
import { useState } from 'react'
import { BoxPlot } from './Charts'
import { boxStats } from '../lib/cadence'
import { fmt, dvfsDomains, type IntervalDistribution, type MeasuredCompare, type MeasuredInputOption, type MeasuredInputs, type TimingReport } from '../lib/timingBudget'
import { maText, type Battery } from '../lib/battery'

export interface Condition {
  statistic: string; scale: number; eis: string; cpuModel: string; throughput: string; margin: number
  profile: string | null; overrides: Record<string, number>
  measured?: MeasuredInputs | null
}

export function conditionChips(c: Condition): string[] {
  const ov = Object.entries(c.overrides)
  return [
    `SW ${c.statistic} ×${c.scale.toFixed(1)}`, `EIS ${c.eis}`, `CPU ${c.cpuModel === 'profile' ? '측정 profile' : '가정'}`,
    c.throughput === 'pipelined' ? 'pipeline (buffer)' : 'stage 1 frame', `margin ${Math.round(c.margin * 100)}%`,
    `profile ${c.profile ?? '없음'}`,
    ov.length ? `DVFS override ${ov.map(([d, l]) => `${d} L${l}`).join(' · ')}` : 'DVFS 자동(계산)',
    ...(c.measured ? [measuredChip(c.measured)] : []),
  ]
}

export function measuredChip(m: MeasuredInputs): string {
  const used = (['sw', 'clock', 'cpu'] as const).filter((k) => m[k]).map((k) => ({ sw: 'SW', clock: 'clock', cpu: 'CPU' })[k])
  return used.length ? `실측 입력 ${used.join('·')}` : '실측 비교만'
}

type Act = { status: 'idle' } | { status: 'busy' } | { status: 'done'; text: string; link?: { label: string; onClick: () => void } } | { status: 'error'; text: string }

/** Condition summary + "Sim evidence 저장" / "예측으로 등록". */
export function ConditionBar({ cond, verdict, onSaveEvidence, onRegister, onOpenPredictions }: {
  cond: Condition; verdict: string | null
  onSaveEvidence: () => Promise<string>; onRegister: (reason: string) => Promise<string>; onOpenPredictions: () => void
}) {
  const [reason, setReason] = useState('')
  const [asking, setAsking] = useState(false)
  const [act, setAct] = useState<Act>({ status: 'idle' })
  const run = async (f: () => Promise<string>, link?: { label: string; onClick: () => void }) => {
    setAct({ status: 'busy' })
    try { setAct({ status: 'done', text: await f(), link }) } catch (e) { setAct({ status: 'error', text: e instanceof Error ? e.message : String(e) }) }
  }
  const canRegister = verdict !== 'fail'
  return <div className="panel tb-cond" style={{ padding: '6px 10px', display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', fontSize: 12 }}>
    <b style={{ fontSize: 12 }}>예측 조건</b>
    {conditionChips(cond).map((c) => <span key={c} className="chip" style={{ fontSize: 11.5 }}>{c}</span>)}
    <span className="grow" />
    <button className="btn tb-mini" disabled={act.status === 'busy'} onClick={() => run(onSaveEvidence)}
      title="이 조건의 계산 결과(timeline 포함)를 simulation evidence로 저장 — Pipeline trace · Compare · 예측↔실측에서 사용. 같은 조건은 1건">Sim evidence 저장</button>
    {!asking ? <button className="btn tb-mini primary" disabled={act.status === 'busy' || !canRegister} onClick={() => setAsking(true)}
      title={canRegister ? '이 조건을 이 variant의 current 예측으로 등록 (예측 현황 · 보고서 숫자). 이전 등록은 superseded' : 'timing fail 조건은 등록할 수 없습니다 (fps drop 불가)'}>예측으로 등록…</button>
      : <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
        <input className="input" style={{ width: 220, padding: '3px 6px' }} placeholder="등록 사유 (필수)" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="등록 사유" autoFocus />
        <button className="btn tb-mini primary" disabled={!reason.trim() || act.status === 'busy'} onClick={() => { setAsking(false); run(() => onRegister(reason.trim()), { label: '예측 현황 →', onClick: onOpenPredictions }) }}>등록</button>
        <button className="btn tb-mini" onClick={() => setAsking(false)}>취소</button></span>}
    {act.status === 'busy' && <span className="faint">처리 중…</span>}
    {act.status === 'done' && <span className="faint">{act.text}{act.link && <> · <a href="#" onClick={(e) => { e.preventDefault(); act.link!.onClick() }}>{act.link.label}</a></>}</span>}
    {act.status === 'error' && <span className="err" style={{ margin: 0 }}>{act.text}</span>}
  </div>
}

/** ⑤ DVFS level per domain: calculated (lowest level meeting the IPs' required clock) or a pinned override. */
export function DvfsOverrideTable({ report, overrides, onChange }: { report: TimingReport; overrides: Record<string, number>; onChange: (o: Record<string, number>) => void }) {
  const rows = dvfsDomains(report)
  if (!rows.length) return <div className="faint" style={{ fontSize: 12 }}>DVFS table이 연결되지 않아 level override를 쓸 수 없습니다.</div>
  const set = (domain: string, v: string) => {
    const next = { ...overrides }
    if (v === '') delete next[domain]; else next[domain] = Number(v)
    onChange(next)
  }
  return <div className="table-x" style={{ marginTop: 8 }}>
    <table className="tb-mini-table" style={{ width: '100%', fontSize: 12 }}>
      <thead><tr><th>DVFS domain</th><th title="domain level을 정하는 IP (최고 필요 clock) · hover = 전체">결정 IP</th><th style={{ textAlign: 'right' }}>필요 max</th><th>계산 level</th><th>적용</th><th>판정</th></tr></thead>
      <tbody>{rows.map((d) => <tr key={d.domain}>
        <td><b>{d.domain}</b></td>
        <td style={{ fontSize: 11.5 }} title={d.ips.map((i) => `${i.node} ${fmt(i.required_clock_mhz, 0)} MHz`).join('\n')}>{(() => {
          const top = [...d.ips].sort((a, b) => b.required_clock_mhz - a.required_clock_mhz)[0]
          return top ? <><span className="mono">{top.node}</span> 최고{d.ips.length > 1 ? <span className="faint"> 외 {d.ips.length - 1}개</span> : null}</> : '—'
        })()}</td>
        <td className="mono" style={{ textAlign: 'right' }}>{fmt(d.required_mhz, 0)}</td>
        <td className="mono">{d.auto ? `L${d.auto.level} · ${fmt(d.auto.mhz, 0)} MHz` : '—'}</td>
        <td><select value={overrides[d.domain] ?? ''} onChange={(e) => set(d.domain, e.target.value)} aria-label={`${d.domain} level`}>
          <option value="">자동 (계산){d.applied && overrides[d.domain] === undefined ? ` · L${d.applied.level}` : ''}</option>
          {d.ladder.map((l) => <option key={l.level} value={l.level}>L{l.level} · {fmt(l.mhz, 0)} MHz{l.mv ? ` · ${fmt(l.mv, 0)} mV` : ''}{d.auto?.level === l.level ? ' (계산)' : ''}</option>)}
        </select></td>
        <td>{d.override === null ? <span className="badge v-ok">자동</span>
          : d.below ? <span className="badge v-fail" title="override clock이 IP 필요 clock보다 낮음 — 처리량 미달(fps drop) 위험">필요 clock 미달</span>
          : <span className="badge v-info" title="필요보다 높은 level로 고정 — 여유 증가, power ↑">override</span>}</td>
      </tr>)}</tbody>
    </table>
    <div className="faint" style={{ fontSize: 11, marginTop: 4 }}>계산 level = domain IP 중 최고 필요 clock을 만족하는 가장 낮은 level · override는 조건의 일부 (URL · Sim evidence · 등록에 함께 저장). domain 안 IP는 같은 level을 공유합니다.</div>
  </div>
}

/** ③ interval / latency box plot from the per-frame SW variance trials. */
export function IntervalBoxes({ data }: { data: IntervalDistribution }) {
  const P = data.period_ms
  const COLOR: Record<string, string> = { preview: '#2F6F68', video: '#4C5E8C' }
  const label = (s: IntervalDistribution['streams'][number]) => `${s.kind === 'preview' ? 'Preview' : 'Video'} · ${s.node}`
  return <div style={{ marginTop: 10 }}>
    <div style={{ fontSize: 12, fontWeight: 600 }}>SW 편차 반영 분포 <span className="faint" style={{ fontWeight: 400 }}>— SW task별 runtime을 frame마다 min~max에서 추출 (평균 유지) · {data.trials}회 × {data.frames} frame · 앞 {data.warmup_excluded}개 제외</span></div>
    <div className="faint" style={{ fontSize: 11.5, margin: '2px 0 4px' }}>출력 간격</div>
    <BoxPlot rows={data.streams.map((s) => ({ id: `iv-${s.node}`, label: label(s), box: boxStats(s.intervals), values: s.intervals, color: COLOR[s.kind], tipTitle: `${label(s)} · 출력 간격`,
      note: `drop ${s.drops}${s.off_cadence_pct !== null ? ` · 목표 이탈 ${fmt(s.off_cadence_pct, 0)}%` : ''}` }))} target={P} targetLabel={`목표 ${fmt(P, 2)} ms`} tolerance={data.tolerance} />
    <div className="faint" style={{ fontSize: 11.5, margin: '6px 0 4px' }}>Pipeline latency (frame 경계 → 출력 완료)</div>
    <BoxPlot rows={data.streams.map((s) => ({ id: `lat-${s.node}`, label: label(s), box: boxStats(s.latency), values: s.latency, color: COLOR[s.kind], tipTitle: `${label(s)} · latency` }))} />
    <div className="faint" style={{ fontSize: 11, marginTop: 4 }}>
      편차 반영 SW: {data.varied.length ? data.varied.join(', ') : '없음 (min/max 통계가 있는 SW task 없음)'}{data.fixed.length ? ` · 고정: ${data.fixed.join(', ')}` : ''}.
      clock은 현재 조건 그대로 · display vsync / encoder queue 완충은 미모델이라 간격 흔들림은 상한 쪽 추정 · 판정(합격/불합격)은 위 고정 통계 기준을 따릅니다.
    </div>
  </div>
}

const shortMeas = (o: MeasuredInputOption) => `${o.synthetic ? '합성 ' : ''}${(o.measured_at ?? '').slice(0, 10) || o.id.slice(0, 24)}${o.total_mw ? ` · ${fmt(o.total_mw, 0)} mW` : ''}`

/** S4: pick a measurement of this variant; each part (SW task timing / IP clocks / CPU profile) is used as input only
 * when ticked — with none ticked the measurement is the comparison reference only. */
export function MeasuredPicker({ options, value, onChange }: { options: MeasuredInputOption[]; value: MeasuredInputs | null; onChange: (m: MeasuredInputs | null) => void }) {
  if (!options.length) return <span className="faint" style={{ fontSize: 12 }} title="이 variant의 measurement evidence 없음 — Camera Profiling / import로 추가">실측 없음</span>
  const sel = options.find((o) => o.id === value?.measurement_ref) ?? null
  const flag = (k: 'sw' | 'clock' | 'cpu', ok: boolean, label: string, tip: string) => (
    <label className="faint" style={{ fontSize: 12, display: 'inline-flex', gap: 3, alignItems: 'center', opacity: ok ? 1 : 0.45 }} title={ok ? tip : `${tip} — 이 측정에 데이터 없음`}>
      <input type="checkbox" disabled={!ok || !value} checked={!!value?.[k]} onChange={(e) => value && onChange({ ...value, [k]: e.target.checked })} />{label}</label>)
  return <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
    <span className="muted" style={{ fontSize: 13 }}>실측</span>
    <select value={value?.measurement_ref ?? ''} onChange={(e) => onChange(e.target.value ? { measurement_ref: e.target.value } : null)} aria-label="measurement" style={{ maxWidth: 230 }}>
      <option value="">사용 안 함</option>
      {options.map((o) => <option key={o.id} value={o.id} title={o.id}>{shortMeas(o)}</option>)}
    </select>
    {value && <>
      {flag('sw', (sel?.sw_tasks.length ?? 0) > 0, 'SW', `측정 SW task runtime(min/mean/max)을 모델 대신 사용${sel?.sw_tasks.length ? ` — ${sel.sw_tasks.join(', ')}` : ''}`)}
      {flag('clock', (sel?.clock_ips ?? 0) > 0, 'clock', `측정 IP clock(clock ledger 측정 단계, residency V² blend)${sel?.clock_ips ? ` — IP ${sel.clock_ips}개` : ''}`)}
      {flag('cpu', !!sel?.cpu, 'CPU', '측정 per-frame CPU profile을 EAS + schedutil로 재현 (CPU 모델 = 측정 profile)')}
      {sel?.synthetic && <span className="badge v-warn" title="SYNTHETIC fixture — silicon 측정이 아님">합성</span>}
    </>}
  </div>
}

const CAT: Record<string, string> = { cpu: 'CPU', ip: 'IP core', bw: 'BW (MIF·DRAM)', other: '기타 (미모델)' }
const dCls = (p: number | null) => (p === null ? '' : Math.abs(p) <= 10 ? 'v-ok' : Math.abs(p) <= 25 ? 'v-warn' : 'v-fail')

/** S4: this condition vs the selected measurement — total and rail categories, with which inputs were measured. */
export function MeasuredCompareCard({ data, battery }: { data: MeasuredCompare; battery: Battery }) {
  const used = (['sw', 'clock', 'cpu'] as const).filter((k) => data.inputs[k])
  const t = data.total
  return <section className="panel" style={{ padding: '8px 12px' }} aria-label="실측 대비">
    <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
      <b style={{ fontSize: 13 }}>실측 대비</b>
      <span className="mono faint" style={{ fontSize: 11.5 }} title={data.measurement_ref}>{data.measurement_ref}</span>
      {data.synthetic && <span className="badge v-warn" title="SYNTHETIC fixture — silicon 측정 아님. 오차는 모델 검증 근거가 될 수 없음">합성</span>}
      <span className="faint" style={{ fontSize: 12 }}>{(data.measured_at ?? '').slice(0, 10)} · {data.context ? Object.values(data.context).filter(Boolean).join(' · ') : ''}</span>
      <span className="chip" style={{ fontSize: 11.5 }}>{used.length ? `실측 입력: ${used.map((k) => ({ sw: 'SW runtime', clock: 'IP clock', cpu: 'CPU profile' })[k]).join(' · ')}` : '실측은 비교 기준만 (입력은 모델)'}</span>
      <span className="grow" />
      <span className="mono" style={{ fontSize: 13 }}>예측 <b>{fmt(t.prediction_mw, 0)}</b> vs 실측 <b>{fmt(t.measurement_mw, 0)}</b> mW
        {t.delta_pct !== null && <span className={`badge ${dCls(t.delta_pct)}`} style={{ marginLeft: 6 }}>{t.delta_pct >= 0 ? '+' : ''}{fmt(t.delta_pct, 1)}%</span>}
        <span className="faint" style={{ fontSize: 11.5, marginLeft: 6 }}>{t.delta_mw !== null ? `Δ ${maText(t.delta_mw, battery, true)}` : ''}</span></span>
    </div>
    <div className="table-x"><table className="tb-mini-table" style={{ marginTop: 4, fontSize: 12 }}>
      <thead><tr><th>구분</th><th style={{ textAlign: 'right' }}>예측 mW</th><th style={{ textAlign: 'right' }}>실측 mW</th><th style={{ textAlign: 'right' }}>Δ mW</th><th style={{ textAlign: 'right' }}>Δ%</th></tr></thead>
      <tbody>{data.rows.map((r) => <tr key={r.category}><td>{CAT[r.category] ?? r.category}</td>
        <td className="mono" style={{ textAlign: 'right' }}>{r.prediction_mw === null ? <span className="faint">미모델</span> : fmt(r.prediction_mw, 0)}</td>
        <td className="mono" style={{ textAlign: 'right' }}>{fmt(r.measurement_mw, 0)}</td>
        <td className="mono" style={{ textAlign: 'right' }}>{r.delta_mw === null ? '—' : `${r.delta_mw >= 0 ? '+' : ''}${fmt(r.delta_mw, 0)}`}</td>
        <td style={{ textAlign: 'right' }}>{r.delta_pct === null ? '—' : <span className={`badge ${dCls(r.delta_pct)}`}>{r.delta_pct >= 0 ? '+' : ''}{fmt(r.delta_pct, 1)}%</span>}</td></tr>)}</tbody>
    </table></div>
    <div className="faint" style={{ fontSize: 11 }}>rail → 구분은 예측 ↔ 실측 페이지와 같은 규칙 · |Δ| ≤10% 녹색 · ≤25% 주황 · 기타 rail은 scenario power model 밖. 입력을 실측으로 바꾸면 남는 오차는 모델 계수(IP · BW · CPU) 쪽 — 계수 보정은 S5.</div>
  </section>
}
