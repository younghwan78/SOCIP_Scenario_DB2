// 예측 기준 (P1 registry + P2 promotion) on 예측 현황:
// active 기준 · draft 만들기 (profile / power params / DVFS) · 시험 계산 (등록 안 함, 하나씩 진행) · Δ 확인 · 승격 (일괄 등록 + active).
import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { useAsync } from '../lib/route'
import { basisApi, FIELD_LABEL, type ModelBasis, type Trial, type TrialItem } from '../lib/basis'
import { calibrationApi } from '../lib/calibration'
import { libraryApi } from '../lib/library'
import { fmt } from '../lib/timingBudget'

const STATUS: Record<ModelBasis['status'], string> = { active: 'v-ok', draft: 'v-warn', retired: '' }

export function BasisPanel({ project, socRef, onDone, onClose }: { project: string; socRef?: string | null; onDone: () => void; onClose: () => void }) {
  const [tick, setTick] = useState(0)
  const q = useAsync(() => basisApi.list(project), [project, tick])
  const profQ = useAsync(() => api.simConfigs(project).then((r) => r.items).catch(() => []), [project])
  const ppQ = useAsync(() => calibrationApi.powerParams(socRef ?? undefined).catch(() => []), [socRef])
  const dvfsQ = useAsync(() => libraryApi.dvfs().then((r) => r.items.filter((t) => !socRef || t.soc_ref === socRef)).catch(() => []), [socRef])
  const active = q.data?.active ?? null
  const [form, setForm] = useState<{ cfg: string; pp: string; dvfs: string; title: string } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [sel, setSel] = useState<string | null>(null)
  const draft = (q.data?.items ?? []).find((b) => b.id === sel) ?? (q.data?.items ?? []).find((b) => b.status === 'draft') ?? null
  const openForm = () => setForm({ cfg: active?.config_profile_ref ?? '', pp: active?.power_params_ref ?? '', dvfs: active?.dvfs_table_ref ?? '', title: '' })
  const create = async () => {
    if (!form) return
    setErr(null)
    try {
      const b = await basisApi.create({ project_ref: project, config_profile_ref: form.cfg || null, power_params_ref: form.pp || null,
        dvfs_table_ref: form.dvfs || null, title: form.title || undefined, parent_ref: active?.id ?? null })
      setForm(null); setSel(b.id); setTick((t) => t + 1)
      if (b.existed) setErr(`같은 구성의 기준 ${b.code}가 이미 있습니다 (${b.status}).`)
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)) }
  }
  const act = async (fn: () => Promise<unknown>) => { setErr(null); try { await fn(); setTick((t) => t + 1); onDone() } catch (e) { setErr(e instanceof Error ? e.message : String(e)) } }

  return <section className="panel" style={{ padding: '8px 12px' }} aria-label="예측 기준">
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <b>예측 기준</b>
      <span className="faint" style={{ fontSize: 12 }}>설정 profile · power params · DVFS · engine 묶음. Timing Budget · 조합 탐색 · Simulate는 active 기준을 기본으로 쓰고, 등록 예측에 기준 코드가 남습니다. SW timing과 variant 데이터는 기준에 포함되지 않습니다.</span>
      <span className="grow" />
      <button className="btn tb-mini" onClick={openForm}>새 기준 (draft)…</button>
      <button className="btn tb-mini" onClick={onClose}>닫기</button>
    </div>
    {err && <div className="err" style={{ margin: '6px 0' }}>{err}</div>}
    {q.error && <div className="err">{q.error}</div>}
    {form && <div className="lib-note" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
      <span className="faint">{active ? `${active.code}에서 바꿀 항목만 고르세요` : '첫 기준'}</span>
      <label>설정 profile <select className="input" value={form.cfg} onChange={(e) => setForm({ ...form, cfg: e.target.value })}>
        <option value="">코드 기본값</option>{(profQ.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.id} (v{p.version ?? '?'} · {p.status})</option>)}</select></label>
      <label>power params <select className="input" value={form.pp.split('@')[0]} onChange={(e) => setForm({ ...form, pp: e.target.value })}>
        <option value="">profile 값 / 내장</option>{(ppQ.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.id} (v{p.version} · {p.status}{p.calibrated ? ' · 보정' : ''})</option>)}</select></label>
      <label>DVFS <select className="input" value={form.dvfs} onChange={(e) => setForm({ ...form, dvfs: e.target.value })}>
        <option value="">과제 기본</option>{(dvfsQ.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.id}</option>)}</select></label>
      <input className="input" placeholder="이름 (예: pmp v3 보정)" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} style={{ width: 180 }} />
      <button className="btn" onClick={create}>만들기</button><button className="btn tb-mini" onClick={() => setForm(null)}>취소</button>
    </div>}
    <div className="table-x"><table className="tb-mini-table" style={{ fontSize: 12 }}>
      <thead><tr><th>기준</th><th>상태</th><th>구성</th><th>이름</th><th>만든 날</th><th>시험 계산</th><th /></tr></thead>
      <tbody>{(q.data?.items ?? []).map((b) => <tr key={b.id} className={draft?.id === b.id ? 'selected' : ''} onClick={() => setSel(b.id)} style={{ cursor: 'pointer' }}>
        <td className="mono"><b>{b.code}</b></td>
        <td><span className={`badge ${STATUS[b.status]}`}>{b.status}</span></td>
        <td className="mono">{b.components}</td>
        <td>{b.title ?? '—'}</td>
        <td className="mono faint">{b.created_at?.slice(0, 10)}</td>
        <td className="mono">{b.trial?.total ? `${b.trial.done}/${b.trial.total}${b.trial.delta_mw_sum != null ? ` · Σ ${b.trial.delta_mw_sum > 0 ? '+' : ''}${b.trial.delta_mw_sum} mW` : ''}` : '—'}</td>
        <td>{b.status === 'draft' && !active && <button className="btn tb-mini" onClick={(e) => { e.stopPropagation(); act(() => basisApi.activate(b.id)) }}
          title="첫 기준: 이후 계산 · 등록부터 적용 (기존 등록 예측은 그대로)">활성화</button>}
          {b.status === 'draft' && <button className="btn tb-mini" onClick={(e) => { e.stopPropagation(); act(() => basisApi.retire(b.id)) }}>폐기</button>}</td>
      </tr>)}
      {!q.loading && !(q.data?.items ?? []).length && <tr><td colSpan={7} className="faint">기준이 없습니다. “새 기준”으로 만들고 활성화하면 이후 계산 · 등록이 그 기준으로 기록됩니다.</td></tr>}</tbody>
    </table></div>
    {draft?.status === 'draft' && active && <TrialView key={draft.id} basis={draft} onPromoted={() => { setTick((t) => t + 1); onDone() }} />}
  </section>
}

function TrialView({ basis, onPromoted }: { basis: ModelBasis; onPromoted: () => void }) {
  const [trial, setTrial] = useState<Trial | null>(null)
  const [running, setRunning] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const stop = useRef(false)
  useEffect(() => { basisApi.trial(basis.id).then(setTrial).catch((e) => setErr(String(e))); return () => { stop.current = true } }, [basis.id])
  const runPending = async (t: Trial) => {
    setRunning(true); stop.current = false
    let items = t.items
    for (const it of t.items.filter((x) => x.status === 'pending' || x.status === 'error')) {
      if (stop.current) break
      let res: TrialItem
      try { res = await basisApi.tryOne(basis.id, it.prediction_id) } catch (e) { res = { ...it, status: 'error', reason: e instanceof Error ? e.message : String(e) } }
      items = items.map((x) => (x.prediction_id === it.prediction_id ? { ...x, ...res, prediction_id: x.prediction_id } : x))
      setTrial((cur) => (cur ? { ...cur, items } : cur))
    }
    setRunning(false)
    setTrial(await basisApi.trial(basis.id))
  }
  const start = async () => { setErr(null); try { const t = await basisApi.startTrial(basis.id); setTrial(t); await runPending(t) } catch (e) { setErr(e instanceof Error ? e.message : String(e)); setRunning(false) } }
  const promote = async () => {
    setErr(null)
    try { const r = await basisApi.promote(basis.id); setResult(`${r.basis.code} active · 재등록 ${r.promoted.length}건 · 유지 ${r.kept.length}건${r.kept.length ? ` (${r.kept.slice(0, 3).map((k) => `${k.variant_id}: ${k.reason}`).join('; ')}${r.kept.length > 3 ? ' …' : ''})` : ''}`); onPromoted() }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)) }
  }
  const items = trial?.items ?? []
  const ok = items.filter((x) => x.status === 'ok')
  const deltas = ok.map((x) => x.delta_mw ?? 0)
  return <div style={{ marginTop: 8 }}>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <b>{basis.code} 승격</b>
      {trial?.against && <span className="faint" style={{ fontSize: 12 }}>vs active {trial.against.code}: {trial.diff.length ? trial.diff.map((d) => `${FIELD_LABEL[d.field] ?? d.field} ${d.from ?? '기본'} → ${d.to ?? '기본'}`).join(' · ') : '구성 동일'}</span>}
      <span className="grow" />
      {!running && <button className="btn" onClick={start} title="과제의 현재 등록 예측을 이 기준으로 다시 계산 (run만 만들고 등록은 안 함)">{items.length ? '시험 계산 다시' : '시험 계산 시작'}</button>}
      {running && <button className="btn" onClick={() => { stop.current = true }}>중지</button>}
      {!running && items.some((x) => x.status === 'pending' || x.status === 'error') && items.length > 0 && <button className="btn tb-mini" onClick={() => trial && runPending(trial)}>남은 항목 계속</button>}
      <button className="btn primary" disabled={running || !ok.length} onClick={promote}
        title="시험 계산이 끝난 항목을 일괄 등록하고 이 기준을 active로 (이전 기준은 retired). 시험 후 다른 등록이 생긴 variant는 덮어쓰지 않음">승격 ({ok.length}건 재등록)</button>
    </div>
    {err && <div className="err">{err}</div>}
    {result && <div className="lib-note">{result}</div>}
    {items.length > 0 && <>
      <div className="faint" style={{ fontSize: 12, margin: '4px 0' }}>{ok.length}/{items.length} 완료 · 건너뜀 {items.filter((x) => x.status === 'skipped').length} · 실패 {items.filter((x) => x.status === 'error').length}
        {deltas.length > 0 && <> · Δ 합 <b className="mono">{fmt(deltas.reduce((a, b) => a + b, 0), 1)} mW</b> · 범위 {fmt(Math.min(...deltas), 1)} ~ {fmt(Math.max(...deltas), 1)} mW</>}</div>
      <div className="table-x" style={{ maxHeight: 280 }}><table className="tb-mini-table" style={{ fontSize: 11.5 }}>
        <thead><tr><th>Scenario</th><th>Variant</th><th>현재 mW</th><th>{basis.code} mW</th><th>Δ mW</th><th>상태</th></tr></thead>
        <tbody>{items.map((x) => <tr key={x.prediction_id}>
          <td className="mono faint">{x.scenario_id}</td><td className="mono">{x.variant_id}</td>
          <td className="mono">{x.old_total_mw != null ? fmt(x.old_total_mw, 0) : '—'}</td>
          <td className="mono">{x.new_total_mw != null ? fmt(x.new_total_mw, 0) : '—'}</td>
          <td className="mono" style={{ color: (x.delta_mw ?? 0) < 0 ? 'var(--primary-strong)' : (x.delta_mw ?? 0) > 0 ? 'var(--del-text)' : undefined }}>{x.delta_mw != null ? `${x.delta_mw > 0 ? '+' : ''}${fmt(x.delta_mw, 1)}` : '—'}</td>
          <td title={x.reason}>{x.status === 'ok' ? '✓' : x.status === 'pending' ? (running ? '…' : '대기') : `${x.status}${x.reason ? ` · ${x.reason.slice(0, 60)}` : ''}`}</td>
        </tr>)}</tbody>
      </table></div>
    </>}
  </div>
}
