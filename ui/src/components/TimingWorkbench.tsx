// Timing Budget = prediction workbench: the condition (summary + actions), DVFS level override per domain and the
// ③ interval / latency spread under per-frame SW variance.
import { useState } from 'react'
import { BoxPlot } from './Charts'
import { boxStats } from '../lib/cadence'
import { fmt, dvfsDomains, type IntervalDistribution, type TimingReport } from '../lib/timingBudget'

export interface Condition {
  statistic: string; scale: number; eis: string; cpuModel: string; throughput: string; margin: number
  profile: string | null; overrides: Record<string, number>
}

export function conditionChips(c: Condition): string[] {
  const ov = Object.entries(c.overrides)
  return [
    `SW ${c.statistic} ×${c.scale.toFixed(1)}`, `EIS ${c.eis}`, `CPU ${c.cpuModel === 'profile' ? '측정 profile' : '가정'}`,
    c.throughput === 'pipelined' ? 'pipeline (buffer)' : 'stage 1 frame', `margin ${Math.round(c.margin * 100)}%`,
    `profile ${c.profile ?? '없음'}`,
    ov.length ? `DVFS override ${ov.map(([d, l]) => `${d} L${l}`).join(' · ')}` : 'DVFS 자동(계산)',
  ]
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
      <thead><tr><th>DVFS domain</th><th>IP (필요 MHz)</th><th style={{ textAlign: 'right' }}>필요 max</th><th>계산 level</th><th>적용</th><th>판정</th></tr></thead>
      <tbody>{rows.map((d) => <tr key={d.domain}>
        <td><b>{d.domain}</b></td>
        <td className="mono" style={{ fontSize: 11 }}>{d.ips.map((i) => `${i.node} ${fmt(i.required_clock_mhz, 0)}`).join(' · ')}</td>
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
