import { FOLLOW_BASIS, NO_PROFILE, POWER_MODEL_LABEL, type SimProfile } from '../lib/simProfile'
import { basisShortLabel, OVERRIDE_LABEL, type ModelBasis } from '../lib/basis'
import { BasisInfoButton } from './BasisDetail'

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

/** Sim config profile picker; '코드 기본값' = no profile (built-in constants). Shows what the chosen profile is.
 * With the 과제's active 예측 기준 it becomes "기준 B<n>" vs "기준 외 (profile 직접)"; the B<n> badge opens the full detail. */
export function ProfileSelect({ profiles, value, onChange, basis, followsBasis, overrides }: { profiles: SimProfile[]; value: string | null; onChange: (v: string) => void
  /** the 과제's active 예측 기준; with it the picker becomes "기준 따르기" vs "기준 외" */
  basis?: ModelBasis | null; followsBasis?: boolean
  /** inputs the calculation set outside the basis (server ``basis_overrides``); default = profile choice only */
  overrides?: string[] }) {
  if (!profiles.length && !basis) return null
  if (basis) {
    const ov = overrides ?? (followsBasis ? [] : ['config_profile'])
    const code = ov.length ? `${basis.code}*` : basis.code
    const tip = `예측 기준 ${basis.code}${basis.title ? ` · ${basis.title}` : ''} · ${basis.components}\n` +
      (ov.length ? `기준 외 ${basis.code}*: ${ov.map((o) => OVERRIDE_LABEL[o] ?? o).join(', ')}을(를) 직접 바꿨습니다 → 등록하면 ${basis.code}*로 기록`
        : '이 화면의 계산 · 등록은 이 기준으로 기록됩니다.') + '\n클릭: 기준 상세'
    return (
      <span className="basis-sel">
        <span className="muted" style={{ fontSize: 13, whiteSpace: 'nowrap' }}>예측 기준</span>
        <select className="input" value={followsBasis ? FOLLOW_BASIS : (value ?? NO_PROFILE)} onChange={(e) => onChange(e.target.value)} aria-label="예측 기준"
          title={basisShortLabel(basis)}>
          <option value={FOLLOW_BASIS}>{basisShortLabel(basis)}</option>
          <optgroup label="기준 외 (설정 profile 직접)">
            {[...profiles].sort((a, b) => (b.version ?? 0) - (a.version ?? 0)).map((p) => <option key={p.id} value={p.id}>{p.id} (v{p.version ?? '?'}{p.status ? ` · ${p.status}` : ''})</option>)}
            <option value={NO_PROFILE}>코드 기본값 (profile 없음)</option>
          </optgroup>
        </select>
        <BasisInfoButton basisId={basis.id} label={code} overrides={ov} title={tip} />
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
