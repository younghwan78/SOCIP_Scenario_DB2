import { useEffect, useState } from 'react'
import { api, type CatalogItem } from './lib/api'
import { addComparison, useAsync, useRoute, type Page } from './lib/route'
import { Icon } from './components/Icons'
import { Resizer, usePref, useResizable } from './components/Layout'
import { Picker } from './components/Picker'
import { ExplorerPage } from './pages/Explorer'
import { MatrixPage } from './pages/Matrix'
import { PipelinePage } from './pages/Pipeline'
import { ComparePage } from './pages/Compare'
import { TimingBudgetPage } from './pages/TimingBudget'
import { TimingFleetPage } from './pages/TimingFleet'
import { ExplorePage } from './pages/Explore'
import { PredictionsPage } from './pages/Predictions'
import { ReportsPage } from './pages/Reports'
import { HomePage } from './pages/Home'
import { CalibrationPage } from './pages/Calibration'
import { LibraryPage } from './pages/Library'
import { SettingsPage } from './pages/Settings'
import { PREFERRED_REFERENCE } from './lib/defaults'

type NavItem = { page: Page; label: string; icon: string; also?: Page[] }
// Workflow order: 탐색 → 예측 → Architecture → Library. Home = brand link; legacy Streamlit lives in 설정.
const NAV: { title: string; items: NavItem[] }[] = [
  { title: '탐색', items: [
    { page: 'explorer', label: 'Scenario', icon: 'explorer', also: ['matrix'] },
    { page: 'pipeline', label: 'Pipeline', icon: 'pipeline' },
    { page: 'compare', label: 'Compare', icon: 'compare' }] },
  { title: '예측', items: [
    { page: 'timing', label: 'Timing Budget', icon: 'timer', also: ['timing-fleet'] },
    { page: 'predictions', label: '예측 현황', icon: 'bars' },
    { page: 'calibration', label: '예측 ↔ 실측', icon: 'trend' }] },
  { title: 'Architecture', items: [
    { page: 'explore', label: '조합 탐색', icon: 'probe' },
    { page: 'reports', label: '검토 보고서', icon: 'report' }] },
  { title: 'Library', items: [{ page: 'library', label: 'IP · DVFS · SW', icon: 'library' }] },
]

const TITLES: Record<Page, string> = {
  home: 'Home', explorer: 'Scenario', matrix: 'Scenario', pipeline: 'Pipeline', compare: 'Compare', timing: 'Timing Budget', 'timing-fleet': 'Timing Budget',
  explore: '조합 탐색', predictions: '예측 현황', reports: 'Architecture 검토 보고서', calibration: '예측 ↔ 실측', library: 'Library', settings: '설정',
}

export interface Ctx {
  catalog: CatalogItem[]
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
  const catalog = catalogQ.data?.items ?? []
  const scopedCatalog = route.params.project ? catalog.filter((c) => c.project_id === route.params.project) : catalog
  const scenario = route.params.scenario ?? scopedCatalog.find((c) => c.scenario_id === 'uc-camera-recording')?.scenario_id ?? scopedCatalog[0]?.scenario_id ?? ''
  const scenarioItem = catalog.find((c) => c.scenario_id === scenario)
  const project = scenarioItem?.project_id ?? route.params.project ?? ''
  const variant = route.params.variant ?? (scenarioItem?.variant_count ? PREFERRED_REFERENCE[scenario] ?? scenarioItem.default_variant_id ?? '' : '')

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
    }
    nav({ page, params: next }, replace)
  }
  const ctx: Ctx = { catalog, project, scenario, variant, params: route.params, navigate, openPicker: (m = 'open') => setPicker(m) }
  const link = (page: Page) => {
    const p = new URLSearchParams(Object.entries({ project, scenario, variant }).filter(([, v]) => v))
    return `#/${page}?${p.toString()}`
  }
  const socLabel = scenarioItem?.soc_ref?.replace(/^soc-/, '').replace(/^exynos/i, 'Exynos') ?? ''

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
          <div className="crumbs">
            {socLabel && <><span>{socLabel}</span><span className="sep">›</span></>}
            {scenarioItem?.board_type && <><span>{scenarioItem.board_type}</span><span className="sep">›</span></>}
            <span style={{ color: 'var(--text)', fontWeight: 600 }}>{scenarioItem?.scenario_name ?? scenario}</span>
            {(route.page === 'pipeline' || route.page === 'timing') && variant && <><span className="sep">›</span>
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
              <a className={route.page === 'timing-fleet' ? 'on' : ''} href={link('timing-fleet')}>전체 scenario</a>
            </div>
          )}
          <button className="find-btn" onClick={() => setPicker('open')}>
            <Icon name="search" size={15} /><span style={{ flexGrow: 1, textAlign: 'left' }}>Variant 찾기</span><span className="kbd">Ctrl K</span>
          </button>
        </header>}
        {catalogQ.error && route.page !== 'home' && route.page !== 'settings' && <div className="page"><div className="err">API에 연결할 수 없습니다: {catalogQ.error}<br />FastAPI(:18000)를 실행하고 <span className="mono">npm run dev</span>의 /api 프록시를 확인하세요.</div></div>}
        {!catalogQ.error && route.page === 'explorer' && <ExplorerPage key={`${scenario}:${route.params.type ?? ''}`} ctx={ctx} />}
        {!catalogQ.error && route.page === 'matrix' && <MatrixPage ctx={ctx} />}
        {!catalogQ.error && route.page === 'pipeline' && <PipelinePage key={`${scenario}:${variant}`} ctx={ctx} />}
        {!catalogQ.error && route.page === 'compare' && <ComparePage ctx={ctx} />}
        {!catalogQ.error && route.page === 'timing' && <TimingBudgetPage key={`${scenario}:${variant}`} ctx={ctx} />}
        {!catalogQ.error && route.page === 'timing-fleet' && <TimingFleetPage key={scenario} ctx={ctx} />}
        {!catalogQ.error && route.page === 'explore' && <ExplorePage ctx={ctx} />}
        {!catalogQ.error && route.page === 'predictions' && <PredictionsPage key={scenario} ctx={ctx} />}
        {!catalogQ.error && route.page === 'reports' && <ReportsPage ctx={ctx} />}
        {route.page === 'home' && <HomePage key={scenario} ctx={ctx} />}
        {!catalogQ.error && route.page === 'calibration' && <CalibrationPage key={scenario} ctx={ctx} />}
        {!catalogQ.error && route.page === 'library' && <LibraryPage ctx={ctx} />}
        {route.page === 'settings' && <SettingsPage />}
      </div>
      <Picker open={picker !== null} onClose={() => setPicker(null)} catalog={catalog} scenarioId={scenario}
        onPick={(s, v) => navigate(picker === 'compare' ? 'compare' : route.page === 'compare' ? 'compare' : route.page === 'timing' ? 'timing' : 'pipeline',
          picker === 'compare' || route.page === 'compare' ? { scenario: s, variants: addComparison(scenario, route.params.variants ?? variant, s, v) } : { scenario: s, variant: v })}
        onAddCompare={(s, v) => navigate('compare', { scenario: s, variants: addComparison(scenario, route.params.variants ?? variant, s, v) })} />
    </div>
  )
}
