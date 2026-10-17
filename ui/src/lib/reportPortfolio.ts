// RPT-07 Portfolio: the newest project-scope report per project (SoC/과제 rows).
import type { ReportMeta } from './archExplore'
import type { ProjectInfo } from './projects'

export function latestProjectReports(reports: ReportMeta[], projects: ProjectInfo[]): { project: ProjectInfo; report: ReportMeta | null }[] {
  const newest = new Map<string, ReportMeta>()
  for (const r of reports) {
    if (r.scope !== 'project' || !r.project_ref) continue
    const cur = newest.get(r.project_ref)
    if (!cur || (r.generated_at ?? '') > (cur.generated_at ?? '')) newest.set(r.project_ref, r)
  }
  return projects.map((p) => ({ project: p, report: newest.get(p.id) ?? null }))
}
