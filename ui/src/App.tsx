import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { api, type CatalogItem } from './lib/api'
import { useAsync, useRoute, type Page } from './lib/route'
import { Icon } from './components/Icons'
import { Resizer, usePref, useResizable } from './components/Layout'
import { Picker } from './components/Picker'
import { ModelStatusBar } from './components/Provenance'
import { ExperimentContextBar } from './components/ExperimentContext'
import { PREFERRED_REFERENCE } from './lib/defaults'
import { addItem, canonicalOf, compareItems, counterpart, defaultScenario, formatItems, loadCompareSet, parseItems, projectText, projectsOf, type ProjectInfo } from './lib/projects'
import { AdmissionWaitPill } from './components/AdmissionWait'

const ExplorerPage = lazy(() => import('./pages/Explorer').then((m) => ({ default: m.ExplorerPage })))
const MatrixPage = lazy(() => import('./pages/Matrix').then((m) => ({ default: m.MatrixPage })))
const PipelinePage = lazy(() => import('./pages/Pipeline').then((m) => ({ default: m.PipelinePage })))
const BehaviorPage = lazy(() => import('./pages/Behavior').then((m) => ({ default: m.BehaviorPage })))
const ComparePage = lazy(() => import('./pages/Compare').then((m) => ({ default: m.ComparePage })))
const TimingBudgetPage = lazy(() => import('./pages/TimingBudget').then((m) => ({ default: m.TimingBudgetPage })))
const TimingFleetPage = lazy(() => import('./pages/TimingFleet').then((m) => ({ default: m.TimingFleetPage })))
const ExplorePage = lazy(() => import('./pages/Explore').then((m) => ({ default: m.ExplorePage })))
const PredictionsPage = lazy(() => import('./pages/Predictions').then((m) => ({ default: m.PredictionsPage })))
const ReportsPage = lazy(() => import('./pages/Reports').then((m) => ({ default: m.ReportsPage })))
const HomePage = lazy(() => import('./pages/Home').then((m) => ({ default: m.HomePage })))
const CalibrationPage = lazy(() => import('./pages/Calibration').then((m) => ({ default: m.CalibrationPage })))
const CpuWhatIfPage = lazy(() => import('./pages/CpuWhatIf').then((m) => ({ default: m.CpuWhatIfPage })))
const LibraryPage = lazy(() => import('./pages/Library').then((m) => ({ default: m.LibraryPage })))
const SettingsPage = lazy(() => import('./pages/Settings').then((m) => ({ default: m.SettingsPage })))
const ScenarioWhatIfPage = lazy(() => import('./pages/ScenarioWhatIf').then((m) => ({ default: m.ScenarioWhatIfPage })))

type NavItem = { page: Page; label: string; icon: string; also?: Page[] }
// Review workflow (U9): 선택 → 예측 → 검증 → 최적화 → 결정·보고, then Library. Home = brand link; legacy Streamlit lives in 설정.
const NAV: { title: string; items: NavItem[] }[] = [
  { title: '1 · 선택', items: [
    { page: 'explorer', label: 'Scenario', icon: 'explorer', also: ['matrix'] },
    { page: 'pipeline', label: 'Pipeline', icon: 'pipeline' },
    { page: 'behavior', label: 'Behavior', icon: 'timer' },
    { page: 'compare', label: 'Compare', icon: 'compare' }] },
  { title: '2 · 예측', items: [
    { page: 'whatif', label: 'What-if', icon: 'probe' },
    { page: 'timing', label: 'Timing Budget', icon: 'timer', also: ['timing-fleet'] },
    { page: 'predictions', label: '예측 현황', icon: 'bars' }] },
  { title: '3 · 검증', items: [
    { page: 'calibration', label: '예측 ↔ 실측', icon: 'trend' }] },
  { title: '4 · 최적화', items: [
    { page: 'explore', label: '조합 탐색', icon: 'probe' },
    { page: 'cpu', label: 'CPU what-if', icon: 'probe' }] },
  { title: '5 · 결정 · 보고', items: [
    { page: 'reports', label: '검토 보고서', icon: 'report' }] },
  { title: 'Library', items: [{ page: 'library', label: 'IP · DVFS · SW', icon: 'library' }] },
]

/** U9: the natural next page of the review workflow (shown as a button in the top bar). */
const NEXT: Partial<Record<Page, { page: Page; label: string }>> = {
  explorer: { page: 'pipeline', label: 'Pipeline 보기' }, matrix: { page: 'pipeline', label: 'Pipeline 보기' },
  pipeline: { page: 'whatif', label: '조건 변경 실험' }, whatif: { page: 'compare', label: '후보 비교' }, compare: { page: 'timing', label: 'Timing Budget' },
  timing: { page: 'predictions', label: '예측 현황' }, 'timing-fleet': { page: 'predictions', label: '예측 현황' },
  predictions: { page: 'calibration', label: '실측과 비교' }, calibration: { page: 'explore', label: '조합 탐색' },
  explore: { page: 'reports', label: '검토 보고서' }, cpu: { page: 'explore', label: '조합 탐색' },
}

const TITLES: Record<Page, string> = {
  home: 'Home', explorer: 'Scenario', matrix: 'Scenario', pipeline: 'Pipeline', behavior: 'Behavior · full-stack', compare: 'Compare', timing: 'Timing Budget · variant', 'timing-fleet': 'Timing Budget · 전체 variant',
  explore: '조합 탐색', predictions: '예측 현황', reports: 'Architecture 검토 보고서', calibration: '예측 ↔ 실측', cpu: 'CPU 배치 · 주파수 what-if', whatif: 'What-if · 조건 · 한계 · 병목', library: 'Library', settings: '설정',
}

/** Where a variant picked in the picker opens: pages with a variant crumb stay where they are, else Pipeline. */
export const pickerTarget = (page: Page): Page => (page === 'timing' || page === 'behavior' || page === 'cpu' ? page : 'pipeline')

export interface Ctx {
  /** scenarios of the selected project (과제) */
  catalog: CatalogItem[]
  /** every project's scenarios (cross-project pages: Home, Compare, Picker) */
  allCatalog: CatalogItem[]
  projects: ProjectInfo[]
  setProject: (projectId: string) => void
  project: string
  scenario: string
  variant: string
  params: Record<string, string>
  navigate: (page: Page | undefined, params?: Record<string, string | undefined>, replace?: boolean) => void
  openPicker: (mode?: 'open' | 'compare') => void
}

export default function App() {
  const [route, nav] = useRoute()
  const [picker, setPicker] = useState<null | 'open' | 'compare'>(null)
  const side = useResizable('sidebar.w', 224, 168, 360)
  const [sideOpen, setSideOpen] = usePref('sidebar.open', true)
  const catalogQ = useAsync(() => api.catalog(), [])
  const catalog = useMemo(() => catalogQ.data?.items ?? [], [catalogQ.data])
  const projects = useMemo(() => projectsOf(catalog), [catalog])
  const [lastProject, setLastProject] = usePref('project', '')
  const known = (p?: string) => (p && projects.some((x) => x.id === p) ? p : undefined)
  const routeItem = route.params.scenario ? catalog.find((c) => c.scenario_id === route.params.scenario) : undefined
  // scenario in the URL decides the project; otherwise ?project=, then the last choice, then the first project
  const project = routeItem?.project_id ?? known(route.params.project) ?? known(lastProject) ?? projects[0]?.id ?? route.params.project ?? ''
  const scopedCatalog = useMemo(() => catalog.filter((c) => c.project_id === project), [catalog, project])
  const scenario = route.params.scenario ?? defaultScenario(scopedCatalog)?.scenario_id ?? ''
  const scenarioItem = catalog.find((c) => c.scenario_id === scenario)
  const variant = route.params.variant ?? (scenarioItem?.variant_count ? scenarioItem.default_variant_id ?? PREFERRED_REFERENCE[canonicalOf(scenarioItem)] ?? '' : '')
  useEffect(() => { if (project && project !== lastProject && known(project)) setLastProject(project) }, [project]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPicker('open') }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') { e.preventDefault(); setSideOpen((o) => !o) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setSideOpen])

  const navigate: Ctx['navigate'] = (page, params = {}, replace = false) => {
    const next = { ...params }
    if (next.scenario && next.scenario !== scenario) {
      next.project = catalog.find((c) => c.scenario_id === next.scenario)?.project_id
      if (!('variant' in next)) next.variant = undefined
      if (!('variants' in next)) next.variants = undefined
      if (!('experiment' in next)) next.experiment = undefined
    }
    if ((next.variant && next.variant !== variant) || (next.scenario && next.scenario !== scenario) || (next.project && next.project !== project)) {
      for (const key of ['experiment', 'whatif_target', 'whatif_node', 'whatif_ip', 'whatif_catalog']) if (!(key in next)) next[key] = undefined
    }
    nav({ page, params: next }, replace)
  }
  /** Switch 과제: keep the use case and select the target project's known default variant. */
  const setProject = (pid: string) => {
    if (!pid) return
    if (pid === project) { if (route.page === 'home') nav({ page: 'explorer', params: { project: pid } }); return }
    setLastProject(pid)
    const target = counterpart(catalog, scenarioItem, pid) ?? defaultScenario(catalog.filter((c) => c.project_id === pid))
    // A counterpart shares its use case, not necessarily its variant set.
    // Use the target catalog's known default; a source-only variant would 404.
    nav({ page: route.page === 'home' ? 'explorer' : route.page, params: { project: pid, scenario: target?.scenario_id,
      variant: target?.default_variant_id ?? undefined, variants: undefined, type: undefined,
      run: undefined, report: undefined, m: undefined, v: undefined, experiment: undefined } })
  }
  const ctx: Ctx = { catalog: scopedCatalog, allCatalog: catalog, projects, setProject, project, scenario, variant, params: route.params, navigate, openPicker: (m = 'open') => setPicker(m) }
  const currentItems = route.page === 'compare' ? compareItems(route.params, scenario, variant) : variant ? [{ scenario, variant }] : []
  // from another page, "add to compare" extends the kept compare set (not a fresh one from the current variant)
  const compareBase = () => {
    if (route.page === 'compare') return currentItems
    const kept = parseItems(loadCompareSet())
    return kept.length ? kept : currentItems
  }
  const toCompare = (s: string, v: string) => navigate('compare', { items: formatItems(addItem(compareBase(), { scenario: s, variant: v })), variants: undefined })
  const link = (page: Page) => {
    const p = new URLSearchParams(Object.entries({ project, scenario, variant, experiment: route.params.experiment ?? '' }).filter(([, v]) => v))
    return `#/${page}?${p.toString()}`
  }

  return (
    <div className="app">
      <nav className={`sidebar ${sideOpen ? '' : 'rail'}`} aria-label="주 메뉴" style={sideOpen ? { width: side.size } : undefined}>
        <a className="brand" href="#/" title="Home" aria-label="ScenarioDB Home" aria-current={route.page === 'home' ? 'page' : undefined}>
          <span className="brand-icon"><Icon name="db" size={22} /></span>
          {sideOpen && <span className="brand-name">ScenarioDB</span>}
        </a>
        {NAV.map((g) => (
          <div key={g.title} className="nav-group">
            {sideOpen ? <h6>{g.title}</h6> : <div className="nav-sep" />}
            {g.items.map((it) => {
              const active = route.page === it.page || !!it.also?.includes(route.page)
              return (
                <a key={it.label} className={`nav-item ${active ? 'active' : ''}`} href={link(it.page)} title={sideOpen ? undefined : it.label}
                  aria-current={active ? 'page' : undefined}>
                  <Icon name={it.icon} size={17} />{sideOpen && <span className="nav-label">{it.label}</span>}
                </a>
              )
            })}
          </div>
        ))}
        <div className="nav-bottom">
        <a className={`nav-item nav-quiet ${route.page === 'settings' ? 'active' : ''}`} href={link('settings')} title={sideOpen ? undefined : '설정 · 기존 도구'}
          aria-current={route.page === 'settings' ? 'page' : undefined}>
          <Icon name="settings" size={17} />{sideOpen && <span className="nav-label">설정 · 기존 도구</span>}
        </a>
        <div className="nav-status" title={catalogQ.error ? 'API 연결 실패' : 'API 연결됨'}>
          <span className={`dot ${catalogQ.error ? 'err' : ''}`} />
          {sideOpen && <span>{catalogQ.error ? 'API 연결 실패' : catalogQ.loading ? 'API 연결 중…' : 'API 연결됨'}</span>}
        </div>
        <button className="nav-collapse" onClick={() => setSideOpen((o) => !o)} title={`${sideOpen ? '사이드바 접기' : '사이드바 펼치기'} (Ctrl+B)`} aria-label={sideOpen ? '사이드바 접기' : '사이드바 펼치기'}>
          <Icon name="sidebar" size={16} />{sideOpen && <span>접기</span>}
        </button>
        </div>
      </nav>
      {sideOpen && <Resizer axis="x" label="사이드바 폭" {...side.bind} onReset={side.reset} className="side-resizer" />}
      <div className="main">
        {route.page !== 'home' && <header className="topbar">
          <h1>{TITLES[route.page]}</h1>
          <span className="vsep" />
          {projects.length > 0 && route.page !== 'compare' && (
            <label className="proj-select" title="과제 (SoC · board) 선택">
              <span className="faint">과제</span>
              <select aria-label="과제 선택" value={project} onChange={(e) => setProject(e.target.value)}>
                {projects.map((p) => <option key={p.id} value={p.id}>{projectText(p)} ({p.scenarios} · {p.variants})</option>)}
              </select>
            </label>
          )}
          <div className="crumbs">
            {route.page === 'compare'
              ? <span style={{ color: 'var(--text)', fontWeight: 600 }}>{currentItems.length}개 비교 · 과제 {new Set(currentItems.map((i) => catalog.find((c) => c.scenario_id === i.scenario)?.project_id)).size}개</span>
              : <span style={{ color: 'var(--text)', fontWeight: 600 }}>{scenarioItem?.scenario_name ?? scenario}</span>}
            {(route.page === 'pipeline' || route.page === 'behavior' || route.page === 'timing' || route.page === 'cpu') && variant && <><span className="sep">›</span>
              <button className="crumb-variant" onClick={() => setPicker('open')}>{variant}<Icon name="chevron" size={12} /></button></>}
          </div>
          <span className="grow" />
          {(route.page === 'explorer' || route.page === 'matrix') && (
            <div className="seg" role="group" aria-label="보기">
              <a className={route.page === 'explorer' ? 'on' : ''} href={link('explorer')}>Scenario별</a>
              <a className={route.page === 'matrix' ? 'on' : ''} href={link('matrix')}>전체 Matrix</a>
            </div>
          )}
          {(route.page === 'timing' || route.page === 'timing-fleet') && (
            <div className="seg" role="group" aria-label="보기">
              <a className={route.page === 'timing' ? 'on' : ''} href={link('timing')}>Variant</a>
              <a className={route.page === 'timing-fleet' ? 'on' : ''} href={link('timing-fleet')}>전체 variant</a>
            </div>
          )}
          {NEXT[route.page] && <a className="btn next-step" href={link(NEXT[route.page]!.page)} title="검토 흐름의 다음 단계">다음: {NEXT[route.page]!.label} →</a>}
          <button className="find-btn" onClick={() => setPicker('open')}>
            <Icon name="search" size={15} /><span style={{ flexGrow: 1, textAlign: 'left' }}>Variant 찾기</span><span className="kbd">Ctrl K</span>
          </button>
        </header>}
        {!catalogQ.error && route.page !== 'home' && route.page !== 'settings' && <ModelStatusBar ctx={ctx} />}
        {!catalogQ.error && route.page !== 'home' && route.page !== 'settings' && route.page !== 'whatif' && <ExperimentContextBar scope={{ project_ref: project, scenario_id: scenario, variant_id: variant }} page={route.page} />}
        {catalogQ.error && route.page !== 'home' && route.page !== 'settings' && <div className="page"><div className="err">API에 연결할 수 없습니다: {catalogQ.error}<br />FastAPI(:18000)를 실행하고 <span className="mono">npm run dev</span>의 /api 프록시를 확인하세요.</div></div>}
        <Suspense fallback={<div className="page" role="status">화면을 불러오는 중…</div>}>
        {!catalogQ.error && route.page === 'explorer' && <ExplorerPage key={`${scenario}:${route.params.type ?? ''}`} ctx={ctx} />}
        {!catalogQ.error && route.page === 'matrix' && <MatrixPage key={project} ctx={ctx} />}
        {!catalogQ.error && route.page === 'pipeline' && <PipelinePage key={`${scenario}:${variant}`} ctx={ctx} />}
        {!catalogQ.error && route.page === 'behavior' && <BehaviorPage key={`${scenario}:${variant}`} ctx={ctx} />}
        {!catalogQ.error && route.page === 'compare' && <ComparePage ctx={ctx} />}
        {!catalogQ.error && route.page === 'timing' && <TimingBudgetPage key={`${scenario}:${variant}`} ctx={ctx} />}
        {!catalogQ.error && route.page === 'timing-fleet' && <TimingFleetPage key={scenario} ctx={ctx} />}
        {!catalogQ.error && route.page === 'explore' && <ExplorePage key={project} ctx={ctx} />}
        {!catalogQ.error && route.page === 'predictions' && <PredictionsPage key={scenario} ctx={ctx} />}
        {!catalogQ.error && route.page === 'reports' && <ReportsPage ctx={ctx} />}
        {route.page === 'home' && <HomePage key={scenario} ctx={ctx} />}
        {!catalogQ.error && route.page === 'calibration' && <CalibrationPage key={scenario} ctx={ctx} />}
        {!catalogQ.error && route.page === 'cpu' && <CpuWhatIfPage key={`${project}:${scenario}:${variant}`} ctx={ctx} />}
        {!catalogQ.error && route.page === 'whatif' && <ScenarioWhatIfPage ctx={ctx} />}
        {!catalogQ.error && route.page === 'library' && <LibraryPage ctx={ctx} />}
        {route.page === 'settings' && <SettingsPage ctx={ctx} />}
        </Suspense>
      </div>
      <Picker open={picker !== null} onClose={() => setPicker(null)} catalog={catalog} projects={projects} scenarioId={scenario}
        onPick={(s, v) => (picker === 'compare' || route.page === 'compare' ? toCompare(s, v)
          : navigate(pickerTarget(route.page), { scenario: s, variant: v }))}
        onAddCompare={toCompare} />
      <AdmissionWaitPill />
    </div>
  )
}
