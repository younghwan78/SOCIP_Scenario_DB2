import { getJson } from '../lib/api'
import { useExperimentContext } from '../lib/experimentContext'
import { useAsync, type Page } from '../lib/route'
import './ExperimentWorkspace.css'

/** U-02: the three ways to change a condition are one workspace — the same variant, the same lever
 * catalog, one tab bar. The pages keep their own routes (links stay valid). */
export type ExperimentPage = 'whatif' | 'explore' | 'cpu'
export const EXPERIMENT_TABS: { page: ExperimentPage; label: string; tool: string; question: string }[] = [
  { page: 'whatif', label: '한 조건 바꿔보기', tool: 'What-if', question: '이 조건 하나(크기 · fps · 센서 · IP mode · LLC …)를 바꾸면 판정 · power가 어떻게 되나' },
  { page: 'explore', label: '범위 탐색', tool: '조합 탐색', question: 'SW · 압축 · DVFS (+ 레버 축) 조합 중 spec을 만족하는 최저 power는 무엇인가 — 예측 등록' },
  { page: 'cpu', label: 'CPU 배치', tool: 'CPU what-if', question: '측정 CPU profile의 task를 다른 cluster · 주파수에 배치하면 CPU power가 어떻게 되나' },
]
export const isExperimentPage = (page: Page): page is ExperimentPage => EXPERIMENT_TABS.some((t) => t.page === page)

const TAB_KEY = 'scenariodb.experiment.tab'
/** The workspace tab the nav item opens: the current one while in the workspace (remembered), else the last one used. */
export function experimentTab(current: Page): ExperimentPage {
  try {
    if (isExperimentPage(current)) { localStorage.setItem(TAB_KEY, current); return current }
    const last = localStorage.getItem(TAB_KEY) as Page | null
    return last && isExperimentPage(last) ? last : 'whatif'
  } catch { return isExperimentPage(current) ? current : 'whatif' }
}

export interface LeverMeta { id: string; label: string; source: 'builtin' | 'whatif'; evaluation: string; explorable: boolean }

/** What the shared lever catalog offers each tab: built-in levers are the exploration axes; What-if change
 * kinds are one condition at a time, and the explorable ones can also be exploration axes (re-simulation). */
export function leverSummary(levers: LeverMeta[]) {
  const builtin = levers.filter((l) => l.source === 'builtin')
  const whatif = levers.filter((l) => l.source === 'whatif')
  return { builtin: builtin.map((l) => l.label), whatif: whatif.length, as_axes: whatif.filter((l) => l.explorable).map((l) => l.label) }
}

export function experimentTabHref(page: ExperimentPage, keep: Record<string, string | undefined>): string {
  const q = new URLSearchParams(Object.entries(keep).filter((e): e is [string, string] => !!e[1]))
  const s = q.toString()
  return `#/${page}${s ? `?${s}` : ''}`
}

/** The active tab keeps the page's own state (an open exploration run, a selected variant …): clicking it
 * stays on the current URL; only switching tabs drops the page-specific parameters. */
export function activeTabHref(page: ExperimentPage, keep: Record<string, string | undefined>): string {
  const hash = typeof window !== 'undefined' ? window.location.hash : ''
  return hash === `#/${page}` || hash.startsWith(`#/${page}?`) ? hash : experimentTabHref(page, keep)
}

/** The What-if draft (its model basis, conditions and candidates) belongs to the What-if tab. Exploration
 * and CPU what-if pick their own profile, so on those tabs the draft is named as the What-if draft, not as
 * the basis of the calculation shown. */
export function draftNote(page: ExperimentPage, context: { basis_label?: string | null; changes: unknown[]; candidates: unknown[] } | null | undefined): string {
  if (!context) return ''
  const pending = context.changes.length > 0 || context.candidates.length > 0
  const counts = `조건 ${context.changes.length}개 · 후보 ${context.candidates.length}개`
  if (page === 'whatif') {
    return `${context.basis_label ? ` · 모델 기준 ${context.basis_label}` : ''}${pending ? ` · 진행 중인 ${counts}` : ''}`
  }
  if (!pending) return ''
  return ` · What-if 초안 (${context.basis_label ? `모델 기준 ${context.basis_label}, ` : ''}${counts}) — 이 탭의 계산 기준은 아래 설정`
}

export function ExperimentWorkspaceBar({ page, project, scenario, variant, experiment }: {
  page: ExperimentPage; project: string; scenario: string; variant: string; experiment?: string
}) {
  const leversQ = useAsync(() => getJson<{ levers: LeverMeta[] }>('/arch/exploration/levers'), [])
  const context = useExperimentContext({ project_ref: project, scenario_id: scenario, variant_id: variant })
  const active = EXPERIMENT_TABS.find((t) => t.page === page)!
  const keep = { project, scenario, variant, experiment }
  const s = leversQ.data ? leverSummary(leversQ.data.levers) : null
  return <section className="xws" aria-label="실험 workspace">
    <div className="xws-tabs seg" role="tablist" aria-label="실험 방법">
      {EXPERIMENT_TABS.map((t) => <a key={t.page} role="tab" aria-selected={t.page === page} className={t.page === page ? 'on' : ''}
        href={t.page === page ? activeTabHref(page, keep) : experimentTabHref(t.page, keep)}>{t.label} <span className="faint">· {t.tool}</span></a>)}
    </div>
    <div className="xws-info">
      <span><b>{active.label}</b> — {active.question}</span>
      <span className="faint">
        기준: {variant ? <span className="mono">{variant}</span> : 'variant 미선택'}
        {draftNote(page, context)}
      </span>
      {s && <span className="faint xws-levers">
        레버 카탈로그 (공유): 범위 탐색 내장 {s.builtin.length}개 ({s.builtin.join(' · ')}) · 한 조건 바꿔보기 {s.whatif}개
        {s.as_axes.length > 0 ? `, 그중 ${s.as_axes.length}개는 범위 탐색의 레버 축으로도 사용 (${s.as_axes.slice(0, 5).join(' · ')}${s.as_axes.length > 5 ? ' …' : ''})` : ''}
        · CPU 배치는 측정 CPU profile 기준 (위 레버와 별개)
      </span>}
    </div>
  </section>
}
