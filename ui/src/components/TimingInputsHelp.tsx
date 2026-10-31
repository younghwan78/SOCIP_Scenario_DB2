// Timing Budget "입력 영향": what the SW statistic, 설정 profile, 실측 and power params choices change in the
// result, with the current selection. A click popover (BasisPopover pattern) so the toolbar stays one row.
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { DEFAULT_POWER_MODEL, POWER_MODEL_LABEL, type SimProfile } from '../lib/simProfile'
import type { MeasuredInputOption, MeasuredInputs, Statistic } from '../lib/timingBudget'
import { isSyntheticProfile, profileSummary } from './ProfileSelect'

export interface TimingInputs {
  statistic: Statistic; throughput: 'stage' | 'pipelined'; margin: number
  profile: SimProfile | undefined; basisCode?: string | null
  measured: MeasuredInputs | null; measuredOption?: MeasuredInputOption | null
  /** power params chosen on this screen; '' = the profile's (or basis') own */
  powerParams: string; defaultPowerParams: string | null
}

const pct = (x: number) => `${Math.round(x * 100)}%`

const KV = ({ k, children }: { k: string; children: ReactNode }) => <div className="vp-kv"><span>{k}</span><span>{children}</span></div>

function Current({ x }: { x: TimingInputs }) {
  const p = x.profile
  const rc = p?.run_config ?? {}
  const profMargin = rc.sw_margin != null ? Number(rc.sw_margin) : null
  const used = x.measured ? (['sw', 'clock', 'cpu'] as const).filter((k) => x.measured?.[k]) : []
  return <section className="bd-sec">
    <h4>현재 선택</h4>
    <KV k="SW 통계"><b>{x.statistic}</b>{x.statistic === 'mean' ? ' (기본)' : ''}</KV>
    <KV k="설정 profile">
      {p ? <><span className="mono">{p.id}</span> v{p.version ?? '?'} · {p.status ?? 'draft'}{x.basisCode ? ` · 기준 ${x.basisCode}` : ''}
        {isSyntheticProfile(p) && <> <span className="badge v-warn">SYNTHETIC</span></>}</> : '코드 기본값 (profile 없음)'}
      {p?.description && <div className="faint" style={{ fontSize: 11.5 }}>{p.description}</div>}
      <ul className="tih-list">{profileSummary(p).map((s) => <li key={s}>{s}</li>)}</ul>
      {profMargin !== null && Math.abs(profMargin - x.margin) > 1e-9 && <div className="faint" style={{ fontSize: 11.5 }}>
        profile의 SW margin {pct(profMargin)}는 이 화면에서 쓰지 않습니다 — 툴바 SW margin {pct(x.margin)} 사용</div>}
    </KV>
    <KV k="실측">{x.measured ? <><span className="mono">{x.measured.measurement_ref}</span>{x.measuredOption?.synthetic && <> <span className="badge v-warn">합성</span></>}
      <div>{used.length ? `입력으로 사용: ${used.map((k) => ({ sw: 'SW runtime', clock: 'IP clock', cpu: 'CPU profile' })[k]).join(' · ')}` : '비교 기준만 (계산 입력은 모델)'}</div></> : '사용 안 함'}</KV>
    <KV k="power params"><span className="mono">{x.powerParams || x.defaultPowerParams || '없음 (power model 내장 계수)'}</span>{!x.powerParams && x.defaultPowerParams ? ' (profile 기본)' : ''}
      <span className="faint"> · power model {POWER_MODEL_LABEL[String(rc.power_model ?? DEFAULT_POWER_MODEL)] ?? rc.power_model ?? DEFAULT_POWER_MODEL}</span></KV>
  </section>
}

function Effects({ x }: { x: TimingInputs }) {
  const rows: [ReactNode, ReactNode, ReactNode][] = [
    [<><b>SW 통계</b><div className="faint">mean (기본) = task별 평균 runtime: 평균 전력 · 실측 비교와 같은 조건.<br />max = 정의 SW timing의 최대값: 최악 frame으로 deadline을 보수 판정.</div></>,
      <>SW ms · SW 여유 · CPU mW{x.throughput === 'stage' ? ' · NRT 필요 clock · DVFS level · 판정' : <>. <span className="faint">처리량 기준이 stage 1 frame이면 NRT 필요 clock · 판정도</span></>}</>,
      'HW ms · BW GB/s'],
    [<b>설정 profile</b>,
      <>Power 카드: power model · 계수 · CPU 전력 방식 · ASV(전압) · mA 환산 (Vbat · PMIC).<div className="faint">profile에 h-blank · DVFS 고정 · configured clock이 있으면 RT 예산과 clock도</div></>,
      <>SW · HW ms, fps 판정 (E2600 v1 ↔ v2는 power 항목만 다름). SW margin은 툴바 값</>],
    [<><b>실측</b> 고르기만</>, '실측 대비 카드 (예측 vs 실측 mW, rail 분류별 Δ)', '계산 전부'],
    [<><b>실측</b> SW ✓</>, '측정 task runtime으로 교체 (SW 통계 선택 그대로) → SW ms · 여유 · CPU mW', 'HW · clock'],
    [<><b>실측</b> clock ✓</>, '측정 IP clock (clock ledger) → HW ms · clock · HW mW', 'SW'],
    [<><b>실측</b> CPU ✓</>, '측정 CPU profile을 EAS + schedutil로 재현 → CPU mW · CPU BW. 조건 실험으로는 넘길 수 없음', 'SW · HW timing'],
    [<b>power params</b>, '계수만 교체 → IP · CPU · BW mW. profile의 power model과 짝이 맞는 version만 선택 가능', 'timing 결과 전부'],
  ]
  return <section className="bd-sec">
    <h4>무엇이 바뀌나</h4>
    <table className="tb-mini-table tih-table"><thead><tr><th>입력</th><th>바뀌는 결과</th><th>그대로</th></tr></thead>
      <tbody>{rows.map(([a, b, c], i) => <tr key={i}><td>{a}</td><td>{b}</td><td className="faint">{c}</td></tr>)}</tbody></table>
  </section>
}

/** "?" trigger next to the model-input controls. */
export function TimingInputsHelp({ inputs }: { inputs: TimingInputs }) {
  const [at, setAt] = useState<{ x: number; y: number } | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!at) return
    const close = () => setAt(null)
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    const click = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) close() }
    window.addEventListener('keydown', key)
    const t = setTimeout(() => window.addEventListener('mousedown', click), 0)
    return () => { window.removeEventListener('keydown', key); window.removeEventListener('mousedown', click); clearTimeout(t) }
  }, [at])
  const w = Math.min(640, window.innerWidth - 16)
  const left = at ? Math.max(8, Math.min(at.x - w / 2, window.innerWidth - w - 8)) : 0
  const top = at ? Math.max(8, Math.min(at.y + 6, window.innerHeight - 240)) : 0
  return <>
    <button type="button" className={`help-q ${at ? 'on' : ''}`} aria-label="입력 영향" aria-expanded={!!at} title="SW 통계 · 설정 profile · 실측 · power params가 결과의 무엇을 바꾸는지"
      onClick={(e) => { e.stopPropagation(); const r = (e.currentTarget as HTMLElement).getBoundingClientRect(); setAt(at ? null : { x: r.left + r.width / 2, y: r.bottom }) }}>?</button>
    {at && <div ref={ref} className="verdict-pop basis-pop" role="dialog" aria-label="입력 영향" style={{ left, top, width: w, maxHeight: `calc(100vh - ${top + 12}px)` }}>
      <div className="vp-head"><b>계산 입력이 바꾸는 것</b><span className="grow" /><button className="btn tb-mini" aria-label="닫기" onClick={() => setAt(null)}>✕</button></div>
      <TimingInputsBody inputs={inputs} />
    </div>}
  </>
}

export function TimingInputsBody({ inputs }: { inputs: TimingInputs }) {
  return <><Current x={inputs} /><Effects x={inputs} /></>
}
