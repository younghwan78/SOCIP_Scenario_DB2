// 실측 · 예측 power popover: the same depth as the 예측 기준 (B<n>) popover, opened before leaving for the
// Evidence (예측 ↔ 실측) page — Scenario 실측 column and the Pipeline toolbar power chip.
import { useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react'
import { CAT_LABEL, CONDITION_LABEL, calibrationApi, errClass, shortId, type Category, type Coverage, type MeasDetail, type PredictionCmp } from '../lib/calibration'
import { archApi, type BoardRow } from '../lib/archExplore'
import { batteryNote, maText, useBattery, type Battery } from '../lib/battery'
import { useAsync } from '../lib/route'
import { fmt, verdictChip } from '../lib/timingBudget'

const CATS: Category[] = ['cpu', 'ip', 'bw', 'other']
const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`)
const day = (s: string | null | undefined) => (s ? s.replace('T', ' ').slice(0, 16) : '—')

function usePopDismiss(ref: RefObject<HTMLDivElement | null>, onClose: () => void) {
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    const click = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) onClose() }
    window.addEventListener('keydown', key)
    const t = setTimeout(() => window.addEventListener('mousedown', click), 0)
    return () => { window.removeEventListener('keydown', key); window.removeEventListener('mousedown', click); clearTimeout(t) }
  }, [ref, onClose])
}
function Shell({ title, at, onClose, children, width = 560 }: { title: ReactNode; at: { x: number; y: number }; onClose: () => void; children: ReactNode; width?: number }) {
  const ref = useRef<HTMLDivElement>(null)
  usePopDismiss(ref, onClose)
  const w = Math.min(width, window.innerWidth - 16)
  const left = Math.max(8, Math.min(at.x, window.innerWidth - w - 8)), top = Math.max(8, Math.min(at.y + 6, window.innerHeight - 220))
  return <div ref={ref} className="verdict-pop basis-pop meas-pop" role="dialog" aria-label={typeof title === 'string' ? title : '전력 상세'} style={{ left, top, width: w, maxHeight: `calc(100vh - ${top + 12}px)` }}>
    <div className="vp-head"><b>{title}</b><span className="grow" /><button className="btn tb-mini" aria-label="닫기" onClick={onClose}>✕</button></div>
    {children}
  </div>
}
function Sec({ title, badge, children }: { title: string; badge?: ReactNode; children: ReactNode }) {
  return <section className="bd-sec"><h4>{title}{badge}</h4>{children}</section>
}
function KV({ k, children }: { k: string; children: ReactNode }) {
  return <div className="vp-kv"><span>{k}</span><span>{children}</span></div>
}
const predName = (p: PredictionCmp) => (p.kind === 'current' ? '등록 예측' : 'Sim 최신')

/** Measured CPU · IP · BW · 기타 vs the registered prediction / latest simulation, mW and mA. */
export function MeasureBody({ d, battery, compact }: { d: MeasDetail; battery: Battery; compact?: boolean }) {
  const cur = d.predictions.find((p) => p.kind === 'current')
  const sims = d.predictions.filter((p) => p.kind === 'simulation')
  const preds = [cur, sims[sims.length - 1]].filter((p): p is PredictionCmp => !!p && !!p.rows)
  const ctxKeys = Object.entries(d.context ?? {}).filter(([, v]) => v !== null && v !== '' && v !== undefined).slice(0, 6)
  const cond = cur?.conditions ?? preds[0]?.conditions
  const mismatch = cond?.items.filter((i) => i.status === 'mismatch') ?? []
  const unrecorded = cond?.items.filter((i) => i.status === 'unrecorded') ?? []
  const rails = [...d.measured.rails].sort((a, b) => b.power_mw - a.power_mw).slice(0, compact ? 4 : 6)
  const tasks = [...d.sw_tasks].sort((a, b) => (b.mean_ms ?? 0) - (a.mean_ms ?? 0)).slice(0, compact ? 3 : 5)
  return <>
    <Sec title="측정" badge={<span className={`badge ${d.synthetic ? 'v-warn' : 'v-ok'}`} style={{ marginLeft: 6 }}>{d.synthetic ? '합성 fixture' : d.origin === 'unknown' ? '출처 미기록' : '실측'}</span>}>
      <KV k="evidence"><span className="mono">{shortId(d.id, 8)}</span> · {day(d.measured_at)}</KV>
      {ctxKeys.length > 0 && <KV k="조건">{ctxKeys.map(([k, v]) => `${k} ${v}`).join(' · ')}</KV>}
      <KV k="total"><b className="mono">{fmt(d.total.mean, 1)} mW</b> <span className="mono faint">{maText(d.total.mean, battery)}{d.total.std ? ` · ±${fmt(d.total.std, 1)}` : ''} · n={d.total.n ?? '—'}{d.total.ci_95?.length === 2 ? ` · CI ${fmt(d.total.ci_95[0], 0)}–${fmt(d.total.ci_95[1], 0)}` : ''}</span></KV>
      <KV k="fps · latency"><span className="mono">{fmt(d.fps, 2)} fps{d.frame_latency ? ` · mean ${fmt(d.frame_latency.mean, 1)} / p95 ${fmt(d.frame_latency.p95, 1)} ms` : ''}</span></KV>
      <KV k="rail map"><span className="mono faint">{d.rail_domain_map_ref ?? '이름 규칙'}{d.rail_map_basis === 'latest' ? ' (최신 profile)' : ''} · 미귀속 {fmt(d.unexplained_mw, 1)} mW</span></KV>
      {d.synthetic && <div className="faint" style={{ marginTop: 2 }}>합성 fixture — silicon 측정이 아니라 예측 오차를 모델 검증 근거로 쓰지 않습니다.</div>}
    </Sec>
    <Sec title="CPU · IP · BW 예측 vs 실측">
      <table className="tb-mini-table bd-table"><thead><tr><th>구분</th><th>실측 mW</th>{preds.map((p) => <th key={p.id} title={p.id}>{predName(p)} mW (Δ)</th>)}</tr></thead>
        <tbody>{CATS.map((c) => <tr key={c}><td>{CAT_LABEL[c]}</td>
          <td className="mono">{fmt(d.measured.categories[c], 1)}{d.measured.category_std[c] ? <span className="faint"> ±{fmt(d.measured.category_std[c], 1)}</span> : null}</td>
          {preds.map((p) => { const r = p.rows?.find((x) => x.category === c)
            return <td key={p.id} className="mono">{r?.prediction_mw == null ? <span className="faint">미모델</span> : <>{fmt(r.prediction_mw, 1)} <span className={`badge ${errClass(r.delta_pct)}`}>{pct(r.delta_pct)}</span></>}</td> })}</tr>)}
          <tr><td><b>total</b></td><td className="mono"><b>{fmt(d.total.mean, 1)}</b></td>
            {preds.map((p) => <td key={p.id} className="mono"><b>{fmt(p.total_mw, 1)}</b> <span className={`badge ${errClass(p.delta_pct)}`}>{pct(p.delta_pct)}</span></td>)}</tr></tbody></table>
      {!preds.length && <div className="faint">비교할 예측 없음 — 조합 탐색에서 등록하면 여기에 Δ가 표시됩니다.</div>}
      {cond && <div style={{ marginTop: 2 }}><span className={`badge ${cond.overall === 'equivalent' ? 'v-ok' : 'v-warn'}`}>{CONDITION_LABEL[cond.overall]}</span>
        {mismatch.length > 0 && <span className="err-text"> {mismatch.map((i) => `${i.item}: 실측 ${String(i.measured ?? '—')} / 예측 ${String(i.predicted ?? '—')}`).join(' · ')}</span>}
        {unrecorded.length > 0 && <span className="faint" title={unrecorded.map((i) => `${i.item}: 실측 ${String(i.measured ?? '—')} / 예측 ${String(i.predicted ?? '—')}`).join('\n')}> · 예측 쪽 미기록 {unrecorded.length}개 ({unrecorded.map((i) => i.item).join(', ')})</span>}</div>}
    </Sec>
    {rails.length > 0 && <Sec title={`Rail 상위 ${rails.length}개 (전체 ${d.measured.rails.length})`}>
      <table className="tb-mini-table bd-table"><tbody>{rails.map((r) => <tr key={r.rail}><td className="mono" style={{ fontSize: 11 }}>{r.rail}</td><td className="faint">{CAT_LABEL[r.category]}</td><td className="mono">{fmt(r.power_mw, 1)} mW</td></tr>)}</tbody></table>
    </Sec>}
    {tasks.length > 0 && <Sec title="SW task 실측 (mean 상위)">
      <table className="tb-mini-table bd-table"><thead><tr><th>task</th><th>mean ms</th><th>p95 ms</th><th>cluster</th></tr></thead>
        <tbody>{tasks.map((t) => <tr key={t.task}><td className="mono">{t.task}</td><td className="mono">{fmt(t.mean_ms, 2)}</td><td className="mono">{fmt(t.p95_ms, 2)}</td><td className="faint">{t.cluster ?? '—'}</td></tr>)}</tbody></table>
    </Sec>}
    <div className="faint" style={{ fontSize: 11, marginTop: 4 }}>{batteryNote(battery)}</div>
  </>
}

function EvidenceLink({ onEvidence }: { onEvidence?: () => void }) {
  return onEvidence ? <div style={{ marginTop: 8, display: 'flex', justifyContent: 'flex-end' }}><button className="btn tb-mini" onClick={onEvidence}>예측 ↔ 실측 페이지에서 전체 보기 →</button></div> : null
}

/** Popover for one measurement evidence (Scenario 실측 column). */
export function MeasurePopover({ measId, at, project, onClose, onEvidence }: { measId: string; at: { x: number; y: number }; project?: string; onClose: () => void; onEvidence?: () => void }) {
  const q = useAsync(() => calibrationApi.detail(measId), [measId])
  const battery = useBattery(project)
  return <Shell title="실측 상세" at={at} onClose={onClose}>
    {q.loading ? <div className="faint">불러오는 중…</div> : q.error ? <div className="err-text">{q.error}</div> : q.data ? <MeasureBody d={q.data} battery={battery} /> : null}
    <EvidenceLink onEvidence={onEvidence} />
  </Shell>
}

/** Representative measurement of a variant: the coverage entry marked ``shown``, else the newest. */
export function representative(c: Coverage | undefined): { id: string; synthetic: boolean; total_mw?: number | null } | null {
  const ms = c?.measurements ?? []
  return ms.find((m) => m.shown) ?? ms[0] ?? null
}

function PredictionSec({ b, battery }: { b: BoardRow; battery: Battery }) {
  const v = b.verdict ? verdictChip(b.verdict as 'ok' | 'clock_up' | 'fail') : null
  const p = b.power
  return <Sec title="등록 예측" badge={v ? <span className={`badge ${v.cls}`} style={{ marginLeft: 6 }}>timing {v.label}</span> : undefined}>
    <KV k="total"><b className="mono">{fmt(p.total_mw, 1)} mW</b> <span className="mono faint">{maText(p.total_mw, battery)}</span>
      {b.previous ? <span className="mono faint"> · 이전 등록 대비 {b.previous.delta_mw >= 0 ? '+' : ''}{fmt(b.previous.delta_mw, 1)} mW</span> : null}</KV>
    <KV k="구성"><span className="mono">CPU {fmt(p.cpu_mw, 1)} · IP {fmt(p.hw_mw, 1)} · BW {fmt(p.bw_mw, 1)} mW{p.bw_cpu_mw != null ? ` (그중 CPU BW ${fmt(p.bw_cpu_mw, 1)})` : ''}</span></KV>
    <KV k="BW · fps"><span className="mono">{fmt(b.bw_mbs, 0)} MB/s · {fmt(b.fps, 2)} fps</span></KV>
    {b.compression?.length ? <KV k="압축"><span className="mono">{b.compression.join(', ')}</span></KV> : null}
    {Object.keys(b.dvfs ?? {}).length > 0 && <KV k="DVFS"><span className="mono">{Object.entries(b.dvfs).map(([k, l]) => `${k}:L${l}`).join(' · ')}</span></KV>}
    <KV k="등록">{day(b.created_at)} · {b.selection_rule}{b.selected_by ? ` (${b.selected_by})` : ''} · <span className="mono faint">{shortId(b.id)}</span></KV>
  </Sec>
}

/** Pipeline toolbar: predicted (registered) vs measured power of the open variant. */
export function PowerPopover({ scenarioId, variantId, project, at, onClose, onEvidence, board, measId }: {
  scenarioId: string; variantId: string; project?: string; at: { x: number; y: number }; onClose: () => void; onEvidence?: () => void
  board: BoardRow | null; measId: string | null }) {
  const q = useAsync(() => (measId ? calibrationApi.detail(measId) : Promise.resolve(null)), [measId])
  const battery = useBattery(project)
  return <Shell title={`전력 · ${variantId}`} at={at} onClose={onClose}>
    {board ? <PredictionSec b={board} battery={battery} /> : <Sec title="등록 예측"><div className="faint">등록 예측 없음 — 조합 탐색 / Timing Budget에서 등록</div></Sec>}
    {!measId ? <Sec title="실측"><div className="faint">이 variant의 측정 evidence 없음 ({scenarioId})</div></Sec>
      : q.loading ? <div className="faint">실측 불러오는 중…</div> : q.error ? <div className="err-text">{q.error}</div> : q.data ? <MeasureBody d={q.data} battery={battery} compact /> : null}
    <EvidenceLink onEvidence={onEvidence} />
  </Shell>
}

/** "⚡ 예측 812 · 실측 790 mW" chip that opens ``PowerPopover``. */
export function PowerChip({ scenarioId, variantId, project, onEvidence }: { scenarioId: string; variantId: string; project?: string; onEvidence?: () => void }) {
  const boardQ = useAsync(() => (scenarioId ? archApi.board(scenarioId).catch(() => null) : Promise.resolve(null)), [scenarioId])
  const covQ = useAsync(() => (scenarioId ? calibrationApi.coverage(scenarioId).catch(() => null) : Promise.resolve(null)), [scenarioId])
  const board = useMemo(() => boardQ.data?.rows.find((r) => r.variant_id === variantId) ?? null, [boardQ.data, variantId])
  const meas = representative(covQ.data?.[variantId])
  const [at, setAt] = useState<{ x: number; y: number } | null>(null)
  useEffect(() => setAt(null), [scenarioId, variantId])
  if (!variantId || (boardQ.loading && covQ.loading)) return null
  const pred = board?.power.total_mw, measured = meas?.total_mw
  const delta = pred != null && measured != null && measured ? ((pred - measured) / measured) * 100 : null
  const label = pred == null && measured == null ? '전력 · 예측/실측 없음'
    : `예측 ${pred != null ? fmt(pred, 0) : '—'} · ${meas?.synthetic ? '합성' : '실측'} ${measured != null ? fmt(measured, 0) : '—'} mW`
  return <>
    <button type="button" className={`chip chip-btn power-chip ${delta != null ? errClass(delta) : ''}`} aria-label="예측 · 실측 전력 상세"
      title={`클릭: 등록 예측 · 실측 power 상세 (CPU · IP · BW · rail · SW task)${delta != null ? `\n예측 − 실측 = ${pct(delta)}` : ''}`}
      onClick={(e) => { const r = (e.currentTarget as HTMLElement).getBoundingClientRect(); setAt(at ? null : { x: r.left, y: r.bottom }) }}>
      <span aria-hidden="true">⚡</span> {label}{delta != null ? <span className="mono" style={{ marginLeft: 4 }}>({pct(delta)})</span> : null}</button>
    {at && <PowerPopover scenarioId={scenarioId} variantId={variantId} project={project} at={at} onClose={() => setAt(null)}
      onEvidence={onEvidence ? () => { setAt(null); onEvidence() } : undefined} board={board} measId={meas?.id ?? null} />}
  </>
}
