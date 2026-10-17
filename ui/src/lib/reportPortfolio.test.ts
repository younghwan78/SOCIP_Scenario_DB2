import { describe, expect, it } from 'vitest'
import { latestProjectReports } from './reportPortfolio'
import { isOpen } from './reviewRisks'
import type { ReportMeta } from './archExplore'
import type { ProjectInfo } from './projects'

const rep = (id: string, project: string, at: string, scope: 'project' | 'run'): ReportMeta => ({
  id, title: id, status: 'draft', target_soc_ref: null, project_ref: project, scenario_type: 'x', run_ids: [], dvfs_table_ref: null,
  engine_rev: 'e', html_sha256: 'h', generated_by: null, generated_at: at, spec_ok: 1, explored: 1, scope,
})
const proj = (id: string): ProjectInfo => ({ id, soc: id, board: '', name: id, scenarios: 1, variants: 1 } as ProjectInfo)

describe('report portfolio', () => {
  it('picks the newest project-scope report per project', () => {
    const rows = latestProjectReports([rep('a', 'p1', '2026-10-01', 'project'), rep('b', 'p1', '2026-10-02', 'project'),
      rep('c', 'p1', '2026-10-03', 'run'), rep('d', 'p2', '2026-10-01', 'run')], [proj('p1'), proj('p2')])
    expect(rows.map((r) => r.report?.id ?? null)).toEqual(['b', null])
  })
  it('counts open risks like the API', () => {
    expect(isOpen({ status: 'open', auto_state: 'active' })).toBe(true)
    expect(isOpen({ status: 'accepted', auto_state: 'active' })).toBe(false)
    expect(isOpen({ status: 'open', auto_state: 'resolve_candidate' })).toBe(false)
  })
})
