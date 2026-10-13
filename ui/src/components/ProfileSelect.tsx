import { FOLLOW_BASIS, NO_PROFILE, POWER_MODEL_LABEL, type SimProfile } from '../lib/simProfile'
import type { ModelBasis } from '../lib/basis'

/** One-line summary of what a profile changes in the simulation. */
export function profileSummary(p: SimProfile | undefined): string[] {
  if (!p) return ['코드 내장 기본값: v1-vfps IP 모델 · ASV 4 · BW 80 mW per GB/s · CPU 전력 가정값(flat) — 과제 합의값이 아님']
  const r = p.run_config ?? {}
  const out: string[] = []
  if (r.power_model) out.push(`Power model ${POWER_MODEL_LABEL[String(r.power_model)] ?? r.power_model}`)
  if (r.power_params_ref) out.push(`계수 ${r.power_params_ref}`)
  if (r.include_cpu_power) out.push('CPU 전력: cluster topology (OPP · DSU · leakage)')
  if (r.asv_group != null) out.push(`ASV ${r.asv_group}`)
  if (r.sw_margin != null) out.push(`SW margin ${Math.round(Number(r.sw_margin) * 100)}%`)
  if (r.bw_power_coeff != null && !r.power_params_ref) out.push(`BW ${r.bw_power_coeff} mW per GB/s`)
  if (r.vbat != null) out.push(`mA 환산 ${r.vbat} V / ${r.pmic_efficiency ?? 0.85}`)
  return out
}

/** Sim config profile picker; '코드 기본값' = no profile (built-in constants). Shows what the chosen profile is. */
export function ProfileSelect({ profiles, value, onChange, basis, followsBasis }: { profiles: SimProfile[]; value: string | null; onChange: (v: string) => void
  /** the 과제's active 예측 기준; with it the picker becomes "기준 따르기" vs "기준 외" */
  basis?: ModelBasis | null; followsBasis?: boolean }) {
  if (!profiles.length && !basis) return null
  if (basis) {
    const tip = `예측 기준 ${basis.code}${basis.title ? ` · ${basis.title}` : ''}\n${basis.components}\n` +
      (followsBasis ? '이 화면의 계산 · 등록은 이 기준으로 기록됩니다.' : `기준 외: 설정을 직접 바꿨습니다 → 등록하면 ${basis.code}* (기준 외 조건)으로 기록됩니다.`)
    return (
      <span className="profile-sel" title={tip}>
        <label className="cpu-f" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
          <span className="muted" style={{ fontSize: 13 }}>예측 기준</span>
          <select className="input" value={followsBasis ? FOLLOW_BASIS : (value ?? NO_PROFILE)} onChange={(e) => onChange(e.target.value)} aria-label="예측 기준">
            <option value={FOLLOW_BASIS}>{basis.code} · {basis.components}</option>
            <optgroup label="기준 외 (설정 profile 직접)">
              {[...profiles].sort((a, b) => (b.version ?? 0) - (a.version ?? 0)).map((p) => <option key={p.id} value={p.id}>{p.id} (v{p.version ?? '?'}{p.status ? ` · ${p.status}` : ''})</option>)}
              <option value={NO_PROFILE}>코드 기본값 (profile 없음)</option>
            </optgroup>
          </select>
        </label>
        <span className="faint profile-desc">
          {followsBasis ? <span className="badge v-ok">기준 {basis.code}</span> : <span className="badge v-warn">기준 외 · {basis.code}*</span>}
        </span>
      </span>
    )
  }
  const cur = profiles.find((p) => p.id === value)
  const synthetic = !!cur && /synthetic/i.test(`${cur.description ?? ''} ${cur.run_config?.power_params_ref ?? ''}`)
  const tip = [cur ? `${cur.id} v${cur.version ?? '?'} · ${cur.status ?? ''}${cur.approved_by ? ` · 승인 ${cur.approved_by}` : ''}` : '코드 기본값',
    cur?.description ?? '', ...profileSummary(cur)].filter(Boolean).join('\n')
  return (
    <span className="profile-sel">
      <label className="cpu-f" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }} title={tip}>
        <span className="muted" style={{ fontSize: 13 }}>설정 profile</span>
        <select className="input" value={value ?? NO_PROFILE} onChange={(e) => onChange(e.target.value)} aria-label="설정 profile">
          {[...profiles].sort((a, b) => (b.version ?? 0) - (a.version ?? 0)).map((p) => <option key={p.id} value={p.id}>{p.id} (v{p.version ?? '?'}{p.status ? ` · ${p.status}` : ''}){p.run_config?.power_model ? ` · ${p.run_config.power_model}` : ''}</option>)}
          <option value={NO_PROFILE}>코드 기본값 (profile 없음)</option>
        </select>
      </label>
      <span className="faint profile-desc" title={tip}>
        {cur?.status === 'approved' ? <span className="badge v-ok">합의</span> : cur ? <span className="badge v-warn">draft</span> : <span className="badge">기본값</span>}
        {synthetic && <span className="badge v-warn">SYNTHETIC 계수</span>}
        {' '}{cur?.description ?? profileSummary(undefined)[0]}
      </span>
    </span>
  )
}
