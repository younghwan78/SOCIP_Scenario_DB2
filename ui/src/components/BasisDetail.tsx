// 기준 상세: everything a viewer needs to judge an 예측 기준 (B<n>) — opened from a small "상세" button next to the
// basis label (Timing Budget · 조합 탐색 · Fleet · Scenario 예측 기준 column). A click popover rather than a tooltip:
// the content is long (profile run_config, power params, DVFS domains), scrolls, and stays open to copy from.
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { basisApi, OVERRIDE_LABEL, type BasisDetail } from '../lib/basis'
import { useAsync } from '../lib/route'
import { POWER_MODEL_LABEL } from '../lib/simProfile'
import { fmt } from '../lib/timingBudget'

const STATUS: Record<string, [string, string]> = { active: ['v-ok', 'active · 과제 기본'], draft: ['v-warn', 'draft'], retired: ['', 'retired'] }
const RUN_CONFIG_LABEL: [string, string, (v: unknown) => string][] = [
  ['power_model', 'power model', (v) => POWER_MODEL_LABEL[String(v)] ?? String(v)],
  ['power_params_ref', 'power params (profile)', String],
  ['include_cpu_power', 'CPU 전력', (v) => (v ? '포함 (선택한 모델과 입력으로 계산)' : '제외')],
  ['memory_rail', 'memory rail', String],
  ['bw_power_coeff', 'BW 계수 (v1)', (v) => `${v} mW per GB/s`],
  ['asv_group', 'ASV group', String],
  ['sw_margin', 'SW margin', (v) => `${Math.round(Number(v) * 100)}%`],
  ['h_blank_margin', 'H-blank margin', (v) => `${Math.round(Number(v) * 100)}%`],
  ['vbat', 'mA 환산', (v) => `${v} V`],
  ['pmic_efficiency', 'PMIC 효율', (v) => `${Math.round(Number(v) * 100)}%`],
]
const dt = (s: string | null | undefined) => (s ? s.replace('T', ' ').slice(0, 16) : '—')
const num = (v: number | null | undefined, d = 0) => (v === null || v === undefined ? '—' : fmt(v, d))

function Sec({ title, badge, children }: { title: string; badge?: ReactNode; children: ReactNode }) {
  return <section className="bd-sec"><h4>{title}{badge}</h4>{children}</section>
}
function KV({ k, children }: { k: string; children: ReactNode }) {
  return <div className="vp-kv"><span>{k}</span><span>{children}</span></div>
}
const Syn = ({ on, text = 'SYNTHETIC' }: { on?: boolean; text?: string }) => (on ? <span className="badge v-warn" style={{ marginLeft: 6 }}>{text}</span> : null)

export function BasisDetailBody({ d, overrides }: { d: BasisDetail; overrides?: string[] }) {
  const b = d.basis
  const [cls, label] = STATUS[b.status] ?? ['', b.status]
  const t = b.trial
  const pp = d.power_params, pr = d.profile, dv = d.dvfs
  return <>
    <Sec title="기준">
      <KV k="코드"><b className="mono">{b.code}</b> <span className={`badge ${cls}`}>{label}</span>{b.title ? <> · {b.title}</> : null}</KV>
      <KV k="구성"><span className="mono">{b.components}</span></KV>
      <KV k="입력 상태">{d.inputs.current
        ? <span className="v-ok-text">✓ 만들 때와 같은 입력 (profile · params · DVFS · engine)</span>
        : <span className="err-text">⚠ 입력이 바뀜: {d.inputs.changed.join(', ')} — 이 기준으로는 계산 · 승격 불가, 새 기준 필요</span>}</KV>
      {!d.inputs.current && <div className="faint">아래 구성 상세는 현재 DB 값입니다. 생성 당시 입력과 다를 수 있습니다.</div>}
      <KV k="승격">{b.activated_at ? `${dt(b.activated_at)}${b.activated_by ? ` · ${b.activated_by}` : ''}` : '—'}</KV>
      <KV k="생성">{dt(b.created_at)}{b.created_by ? ` · ${b.created_by}` : ''}{d.parent ? <> · 이전 기준 <span className="mono">{d.parent.code}</span> ({d.parent.status})</> : null}</KV>
      {b.notes && <KV k="메모">{b.notes}</KV>}
      <KV k="content hash"><span className="mono faint">{b.content_hash.slice(0, 16)}</span></KV>
    </Sec>
    {overrides !== undefined && <Sec title="이 화면의 계산">
      {overrides.length === 0
        ? <div className="v-ok-text">기준 {b.code} 그대로 — 등록하면 {b.code}로 기록</div>
        : <div className="err-text">기준 외 {b.code}* — 직접 바꾼 입력: {overrides.map((o) => OVERRIDE_LABEL[o] ?? o).join(', ')}. 등록하면 {b.code}*(기준 외 조건)로 기록</div>}
    </Sec>}
    <Sec title="등록 예측 · 시험 계산">
      <KV k="current 예측">{d.predictions.current}건 · scenario {d.predictions.scenarios}개{d.predictions.ad_hoc ? <span className="err-text"> · 그중 기준 외 {d.predictions.ad_hoc}건</span> : null}</KV>
      {t && t.total > 0 ? <>
        <KV k="시험 계산">{t.done}/{t.total} 성공{t.skipped ? ` · 건너뜀 ${t.skipped}` : ''}{t.failed ? ` · 실패 ${t.failed}` : ''} · 시작 {dt(t.started_at)}</KV>
        <KV k="Δ power (이전 대비)"><span className="mono">합 {num(t.delta_mw_sum)} mW · 범위 {num(t.delta_mw_min)} ~ {num(t.delta_mw_max)} mW</span></KV>
        <KV k="승격 반영">{t.promoted_at ? dt(t.promoted_at) : '아직 안 함'}</KV>
      </> : <KV k="시험 계산">없음 (첫 기준이거나 바로 활성화)</KV>}
    </Sec>
    <Sec title="설정 profile" badge={pr && !pr.missing ? <><span className={`badge ${pr.status === 'approved' ? 'v-ok' : 'v-warn'}`} style={{ marginLeft: 6 }}>{pr.status}</span><Syn on={pr.synthetic} /></> : null}>
      {!pr ? <div className="faint">없음 — 코드 기본값</div> : pr.missing ? <div className="err-text">{pr.id} — DB에 없음</div> : <>
        <KV k="id"><span className="mono">{pr.id}</span> · v{pr.version}{pr.approved_by ? ` · 승인 ${pr.approved_by}` : ''}</KV>
        {pr.description && <KV k="설명">{pr.description}</KV>}
        {RUN_CONFIG_LABEL.filter(([k]) => pr.run_config?.[k] !== undefined && pr.run_config?.[k] !== null)
          .map(([k, l, f]) => <KV key={k} k={l}><span className="mono">{f(pr.run_config![k])}</span></KV>)}
        {!!pr.rail_domains?.length && <KV k="rail map">{pr.rail_domains.join(' · ')}</KV>}
        {b.status !== 'retired' && pr.status !== 'approved' && <div className="faint" style={{ marginTop: 2 }}>profile 자체는 draft — 기준 {b.code}로 고정된 것이지 profile이 합의(approved)된 것은 아님</div>}
      </>}
    </Sec>
    <Sec title="Power params" badge={pp && !pp.missing ? <><span className={`badge ${pp.status === 'approved' ? 'v-ok' : 'v-warn'}`} style={{ marginLeft: 6 }}>{pp.status}</span><Syn on={pp.synthetic} />{pp.calibration?.fit ? <span className="badge v-ok" style={{ marginLeft: 6 }}>보정</span> : null}</> : null}>
      {!pp ? <div className="faint">없음 — profile / 코드 기본 계수</div> : pp.missing ? <div className="err-text">{pp.ref} — DB에 없음</div> : <>
        <KV k="ref"><span className="mono">{pp.ref}</span>{pp.soc_ref ? ` · ${pp.soc_ref}` : ''}</KV>
        {pp.description && <KV k="설명">{pp.description}</KV>}
        <KV k="IP 모델"><span className="mono">{pp.model?.ip_model ?? '—'} · V_ref {num(pp.model?.ref_voltage_mv)} mV · fps_ref {num(pp.model?.ref_fps)}{pp.model?.ip_clock_power_fraction != null ? ` · clock 항 ${Math.round(pp.model.ip_clock_power_fraction * 100)}%` : ''}</span></KV>
        <KV k="BW 모델"><span className="mono">{pp.model?.bw_model ?? '—'} · read {num(pp.bw?.read_mw_per_gbps ?? pp.bw?.mw_per_gbps)} / write {num(pp.bw?.write_mw_per_gbps ?? pp.bw?.mw_per_gbps)} mW per GB/s
          {pp.bw?.llc_hit_scale != null ? ` · LLC hit ×${pp.bw.llc_hit_scale}` : ''}{pp.bw?.governor_util != null ? ` · governor util ${pp.bw.governor_util}` : ''}</span></KV>
        {!!pp.bw?.mif_opps.length && <table className="tb-mini-table bd-table"><thead><tr><th>MIF OPP</th><th>base mW</th><th>capacity MB/s</th></tr></thead>
          <tbody>{pp.bw.mif_opps.map((o, i) => <tr key={i}><td className="mono">{num(o.mhz)} MHz</td><td className="mono">{num(o.base_mw)}</td><td className="mono">{num(o.capacity_mbs)}</td></tr>)}</tbody></table>}
        {!!pp.cpu?.clusters.length && <table className="tb-mini-table bd-table"><thead><tr><th>CPU cluster</th><th>core</th><th>OPP</th><th>max</th><th>mW/core@max</th><th>leak mW/core</th></tr></thead>
          <tbody>{pp.cpu.clusters.map((c) => <tr key={c.name}><td className="mono">{c.name}</td><td className="mono">{c.core_type ?? ''} ×{c.cores ?? '?'}</td><td className="mono">{c.opps}</td>
            <td className="mono">{num(c.max_mhz)} MHz · {num(c.max_mv)} mV</td><td className="mono">{num(c.max_mw_per_core)}</td><td className="mono">{num(c.leak_mw_per_core, 1)}</td></tr>)}</tbody></table>}
        {pp.cpu?.source && <div className="faint">CPU: {pp.cpu.source}</div>}
        <KV k="보정">{pp.calibration?.fit ? `fit · IP ${pp.calibration.ips}개 · evidence ${pp.calibration.evidence}건` : '없음 (원 계수)'}</KV>
        {pp.notes && <KV k="notes"><span className="faint">{pp.notes}</span></KV>}
      </>}
    </Sec>
    <Sec title="DVFS table" badge={dv && !dv.missing ? <Syn on={dv.synthetic} text={dv.evt_hint || 'SAMPLE'} /> : null}>
      {!dv ? <div className="faint">없음 — SoC 기본 table</div> : dv.missing ? <div className="err-text">{dv.id} — DB에 없음</div> : <>
        <KV k="id"><span className="mono">{dv.id}</span> · v{dv.version} · {dv.scope}{dv.source_revision ? ` · ${dv.source_revision}` : ''}</KV>
        {dv.note && <KV k="출처"><span className="faint">{dv.note}</span></KV>}
        {!!dv.domains?.length && <table className="tb-mini-table bd-table"><thead><tr><th>domain</th><th>level</th><th>MHz 범위</th></tr></thead>
          <tbody>{dv.domains.map((x) => <tr key={x.name}><td className="mono">{x.name}</td><td className="mono">{x.levels}</td><td className="mono">{num(x.min_mhz)} ~ {num(x.max_mhz)}</td></tr>)}</tbody></table>}
      </>}
    </Sec>
    <Sec title="Engine">
      <KV k="기준 / 현재"><span className="mono">{b.engine_rev} / {d.inputs.engine_now}</span>{b.engine_rev !== d.inputs.engine_now ? <span className="err-text"> — 코드가 바뀜</span> : null}</KV>
    </Sec>
    <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>SW timing과 variant 데이터는 기준에 포함되지 않습니다 (SW는 버전 · 실측/정의값별로 따로 비교).</div>
  </>
}

/** Popover anchored at a point; closes on Esc / outside click. */
export function BasisPopover({ basisId, at, overrides, onClose }: { basisId: string; at: { x: number; y: number }; overrides?: string[]; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const q = useAsync(() => basisApi.detail(basisId), [basisId])
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    const click = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) onClose() }
    window.addEventListener('keydown', key)
    const t = setTimeout(() => window.addEventListener('mousedown', click), 0)
    return () => { window.removeEventListener('keydown', key); window.removeEventListener('mousedown', click); clearTimeout(t) }
  }, [onClose])
  const w = Math.min(600, window.innerWidth - 16)
  const left = Math.max(8, Math.min(at.x, window.innerWidth - w - 8)), top = Math.max(8, Math.min(at.y + 6, window.innerHeight - 200))
  return (
    <div ref={ref} className="verdict-pop basis-pop" role="dialog" aria-label="예측 기준 상세" style={{ left, top, width: w, maxHeight: `calc(100vh - ${top + 12}px)` }}>
      <div className="vp-head"><b>예측 기준 상세</b><span className="grow" /><button className="btn tb-mini" aria-label="닫기" onClick={onClose}>✕</button></div>
      {q.loading ? <div className="faint">불러오는 중…</div> : q.error ? <div className="err-text">{q.error}</div> : q.data ? <BasisDetailBody d={q.data} overrides={overrides} /> : null}
    </div>
  )
}

/** "B2" badge trigger: a button that opens the popover. */
export function BasisInfoButton({ basisId, label, overrides, title, warn }: { basisId: string; label: ReactNode
  /** this screen's inputs set outside the basis (shows the "이 화면의 계산" section); omit where it does not apply */
  overrides?: string[]; title?: string; warn?: boolean }) {
  const [at, setAt] = useState<{ x: number; y: number } | null>(null)
  return <>
    <button type="button" className={`badge badge-btn basis-btn ${warn ?? !!overrides?.length ? 'v-warn' : 'v-ok'}`} aria-label="예측 기준 상세 보기" title={title ?? '클릭: 기준 상세 (profile · power params · DVFS · 시험 계산)'}
      onClick={(e) => { e.stopPropagation(); const r = (e.currentTarget as HTMLElement).getBoundingClientRect(); setAt(at ? null : { x: r.left, y: r.bottom }) }}>
      {label}</button>
    {at && <BasisPopover basisId={basisId} at={at} overrides={overrides} onClose={() => setAt(null)} />}
  </>
}

