import type { Ctx } from '../App'
import type { CpuInputs } from '../lib/cpu'
import { projectText } from '../lib/projects'

type Profile = CpuInputs['profiles'][number]
export interface ProfileScope { key: string; project: string | null; scenario: string; variant: string; label: string; count: number }

const scopeKey = (scenario: string, variant: string) => `${scenario}\u0000${variant}`

/** Scenario · variant pairs that have a CPU profile (profiles without a scope are reachable only by profile). */
export function profileScopes(profiles: Profile[], catalog: Ctx['allCatalog'] = []): ProfileScope[] {
  const out = new Map<string, ProfileScope>()
  for (const p of profiles) {
    if (!p.scenario_ref || !p.variant_ref) continue
    const key = scopeKey(p.scenario_ref, p.variant_ref)
    const hit = out.get(key)
    if (hit) { hit.count += 1; continue }
    const name = catalog.find((c) => c.scenario_id === p.scenario_ref)?.scenario_name ?? p.scenario_ref
    out.set(key, { key, project: p.project_ref, scenario: p.scenario_ref, variant: p.variant_ref, label: `${name} › ${p.variant_ref}`, count: 1 })
  }
  return [...out.values()].sort((a, b) => (a.project ?? '').localeCompare(b.project ?? '') || a.label.localeCompare(b.label))
}

/**
 * The scenario · variant of the CPU what-if, as a menu of the variants that have a CPU profile. Choosing one
 * moves the app-wide selection (the page reopens on that variant's best profile); the current variant stays
 * listed even without a profile so the menu always shows where the page stands.
 */
export function CpuScopeSelect({ profiles, ctx }: { profiles: Profile[]; ctx: Ctx }) {
  const scopes = profileScopes(profiles, ctx.allCatalog)
  const current = ctx.scenario && ctx.variant ? scopeKey(ctx.scenario, ctx.variant) : ''
  const own = scopes.find((s) => s.key === current)
  const projects = [...new Set(scopes.map((s) => s.project))]
  const projectName = (id: string | null) => projectText(ctx.projects?.find((p) => p.id === id)) || id || '과제 미상'
  const pick = (key: string) => {
    const s = scopes.find((x) => x.key === key)
    if (s) ctx.navigate?.('cpu', { scenario: s.scenario, variant: s.variant })
  }
  if (!scopes.length) return null
  return (
    <label className="cpu-scope" title="CPU profile이 있는 scenario · variant (고르면 앱 전체의 선택이 바뀝니다)">
      <span className="faint">scenario</span>
      <select aria-label="scenario · variant" value={own ? current : current ? '__current' : ''} onChange={(e) => pick(e.target.value)}>
        {!own && <option value={current ? '__current' : ''} disabled>{current ? `${ctx.scenario} › ${ctx.variant} · CPU profile 없음` : '— 선택'}</option>}
        {projects.map((p) => <optgroup key={p ?? ''} label={projectName(p)}>
          {scopes.filter((s) => s.project === p).map((s) => <option key={s.key} value={s.key}>{s.label} ({s.count})</option>)}
        </optgroup>)}
      </select>
    </label>
  )
}
