// Simulation preview → "결과 저장" controls (Pipeline Timing toolbar, Compare summary cards). Logic: lib/simRun.ts
import { saveLabel, type SimState } from '../lib/simRun'

/** Pipeline Timing toolbar: run a simulation preview, then "결과 저장" (stored as simulation evidence). */
export function SimRunControls({ sim, onRun, onSave, disabled }: { sim: SimState | undefined; onRun: () => void; onSave: () => void; disabled?: boolean }) {
  const label = saveLabel(sim)
  const canSave = sim?.status === 'done' && !sim.res.persisted && (!sim.save || sim.save.status === 'error')
  return <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 12 }}>
    {sim?.status === 'running' ? <span className="faint">simulation 계산 중…</span>
      : <button className="btn tb-mini" disabled={disabled || (sim?.status === 'done' && sim.save?.status === 'saving')} onClick={onRun} title="현재 variant를 과제 설정 profile로 simulation (미리보기 — 저장하지 않음)">Simulation 실행</button>}
    {sim?.status === 'done' && <span className="mono faint" title={sim.res.evidence_id}>{typeof sim.res.kpi?.total_power_mw === 'number' ? `${(sim.res.kpi.total_power_mw as number).toFixed(0)} mW` : ''}</span>}
    {canSave && <button className="btn tb-mini primary" onClick={onSave} title="이 결과를 simulation evidence로 저장 — Scenario의 sim 개수 · Compare · Calibration에서 사용 (같은 조건은 1건으로 합쳐짐)">결과 저장</button>}
    {label && <span className={sim?.status === 'done' && sim.save?.status === 'error' ? 'err' : 'faint'} style={{ margin: 0 }}>{label}</span>}
    {sim?.status === 'error' && <span className="err" style={{ margin: 0 }} title={sim.error}>simulation 실패</span>}
  </span>
}

/** Preview run status + "결과 저장" (Compare summary card). */
export function SimSaveLine({ st, onSave }: { st: Extract<SimState, { status: 'done' }>; onSave: () => void }) {
  const label = saveLabel(st)
  const canSave = !st.res.persisted && (!st.save || st.save.status === 'error')
  const id = st.save?.status === 'saved' ? st.save.evidence_id : st.res.persisted ? st.res.evidence_id : null
  return <div style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 11.5, flexWrap: 'wrap' }}>
    <span className="faint">{st.res.persisted || st.save?.status === 'saved' ? '저장된 sim' : '즉석 sim (미저장)'}</span>
    {canSave && <button className="btn tb-mini" onClick={onSave} title="이 결과를 simulation evidence로 저장 — 이후 Scenario의 sim 개수 · Pipeline · Calibration에서 사용">결과 저장</button>}
    {label && <span className={st.save?.status === 'error' ? 'err' : 'faint'} style={{ margin: 0 }} title={id ?? undefined}>{label}</span>}
  </div>
}
