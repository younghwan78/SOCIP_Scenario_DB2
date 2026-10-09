// S5 (예측 ↔ 실측): fit CPU / IP / BW power factors to the project's measurements and publish them as a new draft
// power_model_params version. Nothing is overwritten; the new version is opt-in (Timing Budget "power params",
// 예측 현황 재계산).
import { useEffect, useRef, useState } from 'react'
import { useAsync } from '../lib/route'
import { calibrationApi, type FitCat, type PowerFit, type PowerParamsCreated } from '../lib/calibration'
import { fmt } from '../lib/timingBudget'
import { useSimProfiles } from '../lib/simProfile'
import { ProfileSelect } from './ProfileSelect'
import { Card } from './TimingCharts'

const CATS: FitCat[] = ['cpu', 'ip', 'bw']
const CAT_LABEL: Record<FitCat, string> = { cpu: 'CPU (EM table · DSU · leakage)', ip: 'IP core (ip_power_scale *)', bw: 'BW (MIF · DRAM 계수)' }
const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`)
const cls = (v: number | null | undefined) => (v === null || v === undefined ? '' : Math.abs(v) <= 10 ? 'v-ok' : Math.abs(v) <= 25 ? 'v-warn' : 'v-fail')

/** Factors to publish: recommended ones by default; the user can tick others or untick. */
export function defaultPicks(fit: PowerFit): Record<FitCat, boolean> {
  return Object.fromEntries(CATS.map((c) => [c, !!fit.factors[c]?.recommended])) as Record<FitCat, boolean>
}

export function PowerFitCard({ project, cfgParam, onOpenTiming, onOpenPredictions }: {
  project: string; cfgParam?: string; onOpenTiming: (paramsRef: string) => void; onOpenPredictions: (paramsRef: string) => void
}) {
  const sp = useSimProfiles(project, cfgParam)
  const paramsQ = useAsync(() => calibrationApi.powerParams(), [])
  const [base, setBase] = useState('')
  const [profile, setProfile] = useState<string | null>(null)
  useEffect(() => setProfile(sp.ref), [sp.ref])
  const [synthetic, setSynthetic] = useState(false)
  const [statistic, setStatistic] = useState<'mean' | 'max'>('mean')
  const [measuredSw, setMeasuredSw] = useState(true)
  const [fit, setFit] = useState<PowerFit | null>(null)
  const [picks, setPicks] = useState<Record<FitCat, boolean>>({ cpu: false, ip: false, bw: false })
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [created, setCreated] = useState<PowerParamsCreated | null>(null)
  const [check, setCheck] = useState<PowerFit | null>(null)
  const [desc, setDesc] = useState('')
  const busyRef = useRef(false)
  useEffect(() => { setFit(null); setCreated(null); setCheck(null) }, [project, base, profile, synthetic, statistic, measuredSw])
  const run = async () => {
    if (busyRef.current) return
    busyRef.current = true
    setFit(null)
    setBusy('보정 계산 중…'); setErr(null); setCreated(null); setCheck(null)
    try {
      const f = await calibrationApi.powerFit({ project_ref: project, base_params_ref: base || undefined, config_profile_ref: profile, include_synthetic: synthetic, statistic, measured_sw: measuredSw })
      setFit(f); setPicks(defaultPicks(f))
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)) } finally { busyRef.current = false; setBusy(null) }
  }
  const publish = async () => {
    if (!fit || busyRef.current || created) return
    busyRef.current = true
    setBusy('새 params 버전 만드는 중…'); setErr(null)
    try {
      const c = await calibrationApi.createPowerParams(fit, Object.fromEntries(CATS.map((k) => [k, picks[k] ? fit.factors[k].k : null])), desc || undefined)
      setCreated(c)
      setBusy('새 params로 다시 계산해 검증 중…')
      setCheck(await calibrationApi.powerFit({ project_ref: project, base_params_ref: c.params_ref, config_profile_ref: profile, include_synthetic: synthetic, statistic, measured_sw: measuredSw }))
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)) } finally { busyRef.current = false; setBusy(null) }
  }
  const download = () => {
    if (!created) return
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([created.yaml], { type: 'text/yaml' }))
    a.download = `${created.id}.yaml`
    a.click()
    URL.revokeObjectURL(a.href)
  }
  const synthRows = fit?.rows.filter((r) => r.synthetic).length ?? 0
  return <Card id="cal-fit" title="계수 보정 (S5) — 실측으로 CPU · IP · BW 계수 맞추기" defaultWide
    note="각 측정을 같은 조건(Timing Budget · 실측 SW 입력)으로 예측해 구분별 배율 k를 최소제곱(원점 통과)으로 구하고, 새 draft params 버전으로 발행 — 기존 params는 바뀌지 않음">
    <fieldset disabled={!!busy} style={{ border: 0, padding: 0, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', fontSize: 12 }}>
      <ProfileSelect profiles={sp.profiles} value={profile} onChange={setProfile} />
      <label>기준 params <select value={base} onChange={(e) => setBase(e.target.value)} aria-label="기준 params">
        <option value="">profile 기본</option>{(paramsQ.data ?? []).map((p) => <option key={p.ref} value={p.ref}>{p.ref}{p.calibrated ? ' (보정)' : ''} · {p.status}</option>)}</select></label>
      <label title="측정과 같은 조건을 맞추려면 mean 권장">SW 통계 <select value={statistic} onChange={(e) => setStatistic(e.target.value as 'mean' | 'max')}><option value="mean">mean</option><option value="max">max</option></select></label>
      <label title="측정에 SW task timing이 있으면 SW 가정 대신 사용 — 남는 오차를 계수 쪽으로 좁힘"><input type="checkbox" checked={measuredSw} onChange={(e) => setMeasuredSw(e.target.checked)} /> 실측 SW 입력</label>
      <label title="합성 fixture는 흐름 검증용 — 실제 계수 근거 아님"><input type="checkbox" checked={synthetic} onChange={(e) => setSynthetic(e.target.checked)} /> 합성 포함</label>
      <button className="btn primary" disabled={!project || !!busy || !sp.ready} onClick={run}>보정 계산</button>
      {busy && <span className="faint">{busy}</span>}
    </fieldset>
    {err && <div className="err" style={{ marginTop: 6 }}>{err}</div>}
    {fit && <>
      <div className="faint" style={{ fontSize: 12, margin: '6px 0' }}>기준 {fit.base_params_ref} · 측정 {fit.rows.length}건{synthRows ? ` (합성 ${synthRows})` : ''} · SW {fit.statistic}{fit.errors.length ? ` · 계산 실패 ${fit.errors.length}` : ''}</div>
      {fit.warnings.map((w) => <div key={w} className="lib-note warn" style={{ fontSize: 12, margin: '2px 0' }}>{w}</div>)}
      <div className="table-x"><table className="tb-mini-table" style={{ fontSize: 12, marginTop: 4 }}>
        <thead><tr><th>적용</th><th>구분</th><th style={{ textAlign: 'right' }}>k</th><th style={{ textAlign: 'right' }}>n</th><th style={{ textAlign: 'right' }}>RMSE mW 전→후</th><th style={{ textAlign: 'right' }}>MAPE 전→후</th><th style={{ textAlign: 'right' }}>R² 후</th><th>판단</th></tr></thead>
        <tbody>{CATS.map((c) => { const f = fit.factors[c]; return <tr key={c}>
          <td><input type="checkbox" aria-label={`${c} 적용`} disabled={!f.k} checked={picks[c]} onChange={(e) => setPicks({ ...picks, [c]: e.target.checked })} /></td>
          <td>{CAT_LABEL[c]}</td><td className="mono" style={{ textAlign: 'right' }}><b>{f.k === null ? '—' : f.k.toFixed(3)}</b>{f.clamped ? ' (제한)' : ''}</td>
          <td className="mono" style={{ textAlign: 'right' }}>{f.n}</td>
          <td className="mono" style={{ textAlign: 'right' }}>{fmt(f.rmse_before_mw ?? null, 0)} → {fmt(f.rmse_after_mw ?? null, 0)}</td>
          <td className="mono" style={{ textAlign: 'right' }}>{fmt(f.mape_before_pct ?? null, 1)} → {fmt(f.mape_after_pct ?? null, 1)}%</td>
          <td className="mono" style={{ textAlign: 'right' }}>{f.r2_after ?? '—'}</td>
          <td>{f.recommended ? <span className="badge v-ok">권장</span> : f.k ? <span className="badge v-warn" title="단일 배율로 설명되지 않음 — 모델 구조 확인">비권장</span> : <span className="faint">데이터 없음</span>}</td>
        </tr> })}</tbody></table></div>
      <details style={{ marginTop: 6 }}><summary className="faint" style={{ fontSize: 12 }}>측정별 total 예측 vs 실측 (적용 전 → 후, 기타 rail 포함 total)</summary>
        <div className="table-x"><table className="tb-mini-table" style={{ fontSize: 11.5 }}>
          <thead><tr><th>Variant</th><th style={{ textAlign: 'right' }}>실측</th><th style={{ textAlign: 'right' }}>예측 전</th><th style={{ textAlign: 'right' }}>Δ 전</th><th style={{ textAlign: 'right' }}>예측 후</th><th style={{ textAlign: 'right' }}>Δ 후</th></tr></thead>
          <tbody>{fit.rows.map((r) => <tr key={r.measurement_ref} title={r.measurement_ref}>
            <td className="mono">{r.variant_id}{r.synthetic ? ' · 합성' : ''}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{fmt(r.measured.total ?? null, 0)}</td>
            <td className="mono" style={{ textAlign: 'right' }}>{fmt(r.predicted.total, 0)}</td>
            <td style={{ textAlign: 'right' }}><span className={`badge ${cls(r.delta_pct_before)}`}>{pct(r.delta_pct_before)}</span></td>
            <td className="mono" style={{ textAlign: 'right' }}>{fmt(r.after.total, 0)}</td>
            <td style={{ textAlign: 'right' }}><span className={`badge ${cls(r.delta_pct_after)}`}>{pct(r.delta_pct_after)}</span></td></tr>)}</tbody></table></div></details>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 8, flexWrap: 'wrap', fontSize: 12 }}>
        <input className="input" style={{ width: 320, padding: '3px 6px' }} placeholder="설명 (선택)" value={desc} onChange={(e) => setDesc(e.target.value)} aria-label="params 설명" />
        <button className="btn primary" disabled={!!busy || !!created || !CATS.some((c) => picks[c])} onClick={publish}
          title="체크한 배율을 기준 params에 곱해 새 draft 버전을 만들고, 같은 측정으로 다시 계산해 검증 (기존 params 불변)">새 params 버전 만들기 (draft)</button>
      </div>
    </>}
    {created && <div className="panel" style={{ marginTop: 8, padding: '6px 10px', fontSize: 12 }}>
      <b>{created.params_ref}</b> 생성 (draft) · 적용 {Object.entries(created.applied).map(([c, k]) => `${c} ×${k}`).join(' · ')}
      {check && <span className="faint"> · 검증: 새 params의 k = {CATS.map((c) => `${c} ${check.factors[c].k?.toFixed(3) ?? '—'}`).join(' · ')} (≈1이면 반영됨)</span>}
      <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
        <button className="btn tb-mini" onClick={download} title="DB에는 working copy로 들어감 — 유지하려면 authoring / db YAML에 커밋">YAML 내려받기</button>
        <button className="btn tb-mini" onClick={() => onOpenTiming(created.params_ref)}>Timing Budget에서 이 params로 →</button>
        <button className="btn tb-mini primary" onClick={() => onOpenPredictions(created.params_ref)}>예측 현황에서 재계산 →</button>
      </div>
    </div>}
  </Card>
}
