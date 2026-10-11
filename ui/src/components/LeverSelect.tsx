// Lever 선택 → 예측 등록 (2026-10-11)
//   기본 = 화질 무손실 최적 milestone. 사용자가 buffer별 압축(off · lossless · lossy)과 IQ 평가 option을 바꿔 가며
//   평가된 설계점을 바로 조회한다 (재계산 없음). 등록 규칙:
//     · 무손실만      → 바로 current 예측 (lever:iq-keep)
//     · lossy 포함    → 사유 필수 (lever:trade)
//     · IQ option 포함 → ① 후보로 등록 (review = IQ 평가 중) ② 화질 평가 결과(채택/기각 + 근거)를 넣고 등록
//                        (채택만 있으면 option을 적용해 서버가 다시 탐색 · lever:iq-adopted, 기각이 있으면 등록 안 함)
import { useEffect, useMemo, useState } from 'react'
import { fmt } from '../lib/timingBudget'
import { archApi, IQ_COLOR, IQ_LABEL, REVIEW, type IqClass, type LeverAnalysis, type LeverPoint, type OptionReview, type ReviewStatus } from '../lib/archExplore'
import { maText, type Battery } from '../lib/battery'

export interface Selection { options: string[]; comp: Record<string, string> }

const s1 = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${fmt(v, d)}`)
const isLossy = (m: string) => m.toUpperCase().endsWith('LOSSY')
const setKey = (keys: string[]) => [...keys].sort().join('|')

/** Selection of a milestone (options as item keys, compression as stored). */
export function milestoneSelection(la: LeverAnalysis, phase: IqClass): Selection {
  const ms = la.milestones?.[phase]
  const keyOf = new Map((la.levers ?? []).filter((l) => l.kind === 'option').map((l) => [l.label, l.key]))
  return { options: (ms?.options ?? []).map((o) => keyOf.get(o) ?? o).sort(), comp: { ...(ms?.compression ?? {}) } }
}

/** Evaluated design point of a selection; buffers that the option set removes are dropped (reported as moot). */
export function lookupPoint(points: LeverPoint[], sel: Selection): { point: LeverPoint | null; moot: string[] } {
  const k = setKey(sel.options)
  const same = points.filter((p) => setKey(p.option_keys ?? []) === k)
  const avail = new Set(same.flatMap((p) => Object.keys(p.comp)))
  const kept = Object.fromEntries(Object.entries(sel.comp).filter(([b]) => avail.has(b)))
  const moot = Object.keys(sel.comp).filter((b) => !avail.has(b))
  const want = JSON.stringify(Object.entries(kept).sort())
  const point = same.find((p) => JSON.stringify(Object.entries(p.comp).sort()) === want) ?? null
  return { point, moot }
}

export function LeverSelect({ la, battery, runId, scenarioId, variantId, projectRef, readOnly, sel, setSel }: {
  la: LeverAnalysis; battery: Battery; runId: string; scenarioId: string; variantId: string; projectRef?: string | null
  readOnly: boolean; sel: Selection; setSel: (s: Selection) => void
}) {
  const points = la.points ?? []
  const base = la.baseline!
  const keep = la.milestones?.neutral
  const levers = la.levers ?? []
  const options = levers.filter((l) => l.kind === 'option')
  // buffer -> modes that appear in the design points
  const bufModes = useMemo(() => {
    const m = new Map<string, Set<string>>()
    for (const p of points) for (const [b, mode] of Object.entries(p.comp)) m.set(b, (m.get(b) ?? new Set()).add(mode))
    return [...m.entries()].map(([b, modes]) => ({ buffer: b, modes: [...modes].sort((a, c) => Number(isLossy(a)) - Number(isLossy(c))) }))
  }, [points])
  const { point, moot } = lookupPoint(points, sel)
  const iq: IqClass = sel.options.length ? 'eval' : Object.values(sel.comp).some(isLossy) ? 'trade' : 'neutral'
  const lossy = Object.entries(sel.comp).some(([b, m]) => isLossy(m) && !moot.includes(b))
  const [reviews, setReviews] = useState<OptionReview[] | null>(null)
  const loadReviews = () => archApi.optionReviews(scenarioId).then(setReviews).catch(() => setReviews([]))
  useEffect(() => { void loadReviews() }, [scenarioId]) // eslint-disable-line react-hooks/exhaustive-deps
  const reviewOf = (key: string): ReviewStatus | null => {
    const rs = (reviews ?? []).filter((r) => r.option_key === key && (r.variant_id === variantId || r.variant_id === '*'))
    return (rs.find((r) => r.variant_id === variantId) ?? rs[0])?.status ?? null
  }
  const [iqIn, setIqIn] = useState<Record<string, { status: 'adopted' | 'rejected' | ''; note: string }>>({})
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ text: string; tone: 'ok' | 'err' } | null>(null)
  const preset = (phase: IqClass) => setSel(milestoneSelection(la, phase))
  const toggleOpt = (key: string) => {
    const dim = key.split('=')[0]
    const has = sel.options.includes(key)
    setSel({ ...sel, options: (has ? sel.options.filter((o) => o !== key) : [...sel.options.filter((o) => o.split('=')[0] !== dim), key]).sort() })
  }
  const setComp = (b: string, mode: string | null) => {
    const comp = { ...sel.comp }
    if (mode) comp[b] = mode; else delete comp[b]
    setSel({ ...sel, comp })
  }
  const candidate = async () => {
    setBusy(true); setMsg(null)
    try {
      for (const o of sel.options) {
        await archApi.setOptionReview({ scenario_id: scenarioId, variant_id: variantId, option_key: o, status: 'iq_eval',
          note: `Lever 선택 후보 · 예상 ${point ? `${fmt(point.total_mw, 1)} mW (baseline ${s1(point.total_mw - base.total_mw)} mW)` : ''}` })
      }
      await loadReviews()
      setMsg({ text: `${sel.options.length}개 option을 후보(IQ 평가 중)로 등록했습니다 — 예측 현황에서 추적됩니다. 평가 결과를 넣으면 등록할 수 있습니다.`, tone: 'ok' })
    } catch (e) { setMsg({ text: e instanceof Error ? e.message : String(e), tone: 'err' }) } finally { setBusy(false) }
  }
  const register = async () => {
    setBusy(true); setMsg(null)
    try {
      const comp = Object.fromEntries(Object.entries(sel.comp).filter(([b]) => !moot.includes(b)))
      const r = await archApi.registerLever({
        run_id: runId, scenario_id: scenarioId, variant_id: variantId, compression: comp, options: sel.options,
        iq_results: sel.options.map((o) => ({ option_key: o, status: (iqIn[o]?.status || 'adopted') as 'adopted' | 'rejected', note: iqIn[o]?.note ?? '' })),
        reason: reason || undefined, expected_project_ref: projectRef ?? undefined,
      })
      await loadReviews()
      if (r.status === 'rejected') setMsg({ text: `등록 안 함 — 기각: ${(r.rejected ?? []).join(', ')} (review에 기록됨)`, tone: 'err' })
      else setMsg({ text: `등록: ${r.promoted[0]?.id ?? ''} · ${fmt(r.promoted[0]?.total_mw, 1)} mW · ${r.rule}${r.run_id !== runId ? ` · option 적용 재탐색 run ${r.run_id}` : ''}`, tone: 'ok' })
    } catch (e) { setMsg({ text: e instanceof Error ? e.message : String(e), tone: 'err' }) } finally { setBusy(false) }
  }
  const iqReady = sel.options.every((o) => iqIn[o]?.status && (iqIn[o]?.note ?? '').trim())
  const canRegister = !readOnly && !!point && !busy && (!lossy || !!reason.trim()) && (!sel.options.length || iqReady)
  return (
    <div className="lever-select">
      <div className="lever-select-head">
        <h4>조합 선택 → 예측 등록</h4>
        <div className="seg" role="group" aria-label="시작점">
          <button className={sel.options.length === 0 && !Object.values(sel.comp).some(isLossy) ? 'on' : ''} onClick={() => preset('neutral')}>무손실 최적 (기본)</button>
          {la.milestones?.eval && <button onClick={() => preset('eval')}>+ IQ 평가 lever</button>}
          {la.milestones?.trade && <button onClick={() => preset('trade')}>+ lossy</button>}
        </div>
      </div>
      <div className="lever-select-grid">
        <section>
          <div className="faint" style={{ fontSize: 11.5, marginBottom: 4 }}>Compression (buffer별)</div>
          <table className="tb-mini-table"><tbody>{bufModes.map(({ buffer, modes }) => (
            <tr key={buffer} className={moot.includes(buffer) ? 'faint' : ''}><td className="mono" style={{ fontSize: 12 }}>{buffer}{moot.includes(buffer) && <span className="badge v-info" style={{ marginLeft: 4 }} title="선택한 option이 이 buffer를 없앰">무효</span>}</td>
              <td><div className="seg seg-sm">
                <button className={!sel.comp[buffer] ? 'on' : ''} onClick={() => setComp(buffer, null)}>off</button>
                {modes.map((m) => <button key={m} className={sel.comp[buffer] === m ? 'on' : ''} onClick={() => setComp(buffer, m)}
                  style={sel.comp[buffer] === m ? { color: isLossy(m) ? IQ_COLOR.trade : IQ_COLOR.neutral } : undefined}>{isLossy(m) ? 'lossy' : 'lossless'}</button>)}
              </div></td></tr>))}</tbody></table>
          {options.length > 0 && <>
            <div className="faint" style={{ fontSize: 11.5, margin: '8px 0 4px' }}>IQ 평가 필요 option</div>
            {options.map((o) => { const st = reviewOf(o.key); return (
              <label key={o.key} className="ax-check" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input type="checkbox" checked={sel.options.includes(o.key)} onChange={() => toggleOpt(o.key)} />
                <span>{o.label}</span><span className="faint mono" style={{ fontSize: 11 }}>{s1(o.alone?.total_mw)} mW</span>
                {st && <span className={`badge ${REVIEW[st].cls}`}>{REVIEW[st].label}</span>}
              </label>) })}
          </>}
        </section>
        <section className="lever-select-result" style={{ borderLeftColor: IQ_COLOR[iq] }}>
          {point ? <>
            <div><span className="mono lever-tile-v">{fmt(point.total_mw, 1)}</span> mW <span className="faint">{maText(point.total_mw, battery)}</span>
              <span className="badge" style={{ marginLeft: 6, background: IQ_COLOR[iq], color: '#fff' }}>{IQ_LABEL[iq]}</span></div>
            <div className="mono" style={{ fontSize: 12 }}>baseline {s1(point.total_mw - base.total_mw)} mW · 무손실 최적 {keep ? s1(point.total_mw - keep.total_mw) : '—'} mW · {fmt(point.bw_mbs / 1000, 2)} GB/s</div>
            <div className="mono faint" style={{ fontSize: 11.5 }}>CPU {fmt(point.cpu_mw, 0)} · IP {fmt(point.hw_mw, 0)} · BW {fmt(point.bw_mw, 0)} mW · SW {la.basis?.statistic} ×{la.basis?.runtime_scale} · DVFS 해석 level</div>
            {moot.length > 0 && <div className="faint" style={{ fontSize: 11.5 }}>{moot.join(', ')} 압축은 선택한 option 때문에 무효 — 등록 시 제외</div>}
          </> : <div className="err" style={{ fontSize: 12 }}>이 조합은 평가되지 않았습니다 (같은 dimension의 option 두 개 등) — 다른 조합을 고르세요.</div>}

          {sel.options.length > 0 && <div className="lever-iq">
            <div style={{ fontSize: 12, fontWeight: 600 }}>화질 평가 결과 (등록 조건)</div>
            {sel.options.map((o) => { const l = options.find((x) => x.key === o); const cur = iqIn[o] ?? { status: '', note: '' }; return (
              <div key={o} className="lever-iq-row">
                <span style={{ minWidth: 150 }}>{l?.label ?? o}</span>
                <div className="seg seg-sm">
                  <button className={cur.status === 'adopted' ? 'on' : ''} onClick={() => setIqIn({ ...iqIn, [o]: { ...cur, status: 'adopted' } })}>채택</button>
                  <button className={cur.status === 'rejected' ? 'on' : ''} onClick={() => setIqIn({ ...iqIn, [o]: { ...cur, status: 'rejected' } })}>기각</button>
                </div>
                <input className="input" style={{ flex: 1, minWidth: 160 }} placeholder="근거 (평가 ID · 결과 요약)" value={cur.note} onChange={(e) => setIqIn({ ...iqIn, [o]: { ...cur, note: e.target.value } })} />
              </div>) })}
          </div>}
          {lossy && <input className="input" style={{ width: '100%' }} placeholder="lossy 선택 사유 (필수)" value={reason} onChange={(e) => setReason(e.target.value)} />}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            {sel.options.length > 0 && <button className="btn" disabled={readOnly || busy || !point} onClick={candidate}
              title="option을 예측 현황의 후보(IQ 평가 중)로 등록 — 예측은 바뀌지 않음">후보로 등록 (IQ 평가 요청)</button>}
            <button className="btn primary" disabled={!canRegister} onClick={register}
              title={sel.options.length ? '모든 option에 평가 결과(채택/기각 + 근거)를 넣어야 등록 · 기각이 있으면 등록 안 함' : lossy ? 'lossy는 사유 필요' : '화질 무손실 조합을 current 예측으로 등록'}>
              {busy ? '처리 중…' : sel.options.length ? '평가 결과 반영해 예측 등록' : '예측으로 등록'}</button>
            {msg && <span style={{ fontSize: 12, color: msg.tone === 'err' ? 'var(--del-text)' : 'var(--primary-strong)' }}>{msg.text}</span>}
          </div>
        </section>
      </div>
    </div>
  )
}
