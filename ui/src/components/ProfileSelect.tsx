import { NO_PROFILE, type SimProfile } from '../lib/simProfile'

/** Sim config profile picker; '코드 기본값' = no profile (built-in constants). */
export function ProfileSelect({ profiles, value, onChange }: { profiles: SimProfile[]; value: string | null; onChange: (v: string) => void }) {
  if (!profiles.length) return null
  return (
    <label className="cpu-f" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }} title="과제 합의 run config (power model · power params · BW model). 결과 출처에 기록됩니다.">
      <span className="muted" style={{ fontSize: 13 }}>설정 profile</span>
      <select className="input" value={value ?? NO_PROFILE} onChange={(e) => onChange(e.target.value)} aria-label="설정 profile">
        {[...profiles].sort((a, b) => (b.version ?? 0) - (a.version ?? 0)).map((p) => <option key={p.id} value={p.id}>{p.id} (v{p.version ?? '?'}{p.status ? ` · ${p.status}` : ''})</option>)}
        <option value={NO_PROFILE}>코드 기본값 (profile 없음)</option>
      </select>
    </label>
  )
}
