import { useEffect, useState } from 'react'
import { api, type CatalogItem } from './lib/api'
import { useAsync, useRoute, type Page } from './lib/route'
import { Icon } from './components/Icons'
import { Resizer, usePref, useResizable } from './components/Layout'
import { Picker } from './components/Picker'
import { ExplorerPage } from './pages/Explorer'
import { MatrixPage } from './pages/Matrix'
import { PipelinePage } from './pages/Pipeline'
import { ComparePage } from './pages/Compare'

const NAV: { title: string; items: ({ page: Page; label: string; icon: string } | { href: string; label: string; icon: string })[] }[] = [
  { title: 'Browse', items: [{ page: 'explorer', label: 'DB Explorer', icon: 'explorer' }, { page: 'matrix', label: '전체 Variant Matrix', icon: 'matrix' }] },
  { title: 'Analyze', items: [{ page: 'pipeline', label: 'Pipeline', icon: 'pipeline' }, { page: 'compare', label: 'Variant Compare', icon: 'compare' }] },
  { title: 'Streamlit (기존)', items: [
    { href: 'http://localhost:18502/Evidence_Dashboard', label: 'Evidence · 예측/실측', icon: 'external' },
    { href: 'http://localhost:18502/Import_Workbench', label: 'Import · Sensor · Driver', icon: 'external' }] },
]

const TITLES: Record<Page, string> = { explorer: 'DB Explorer', matrix: 'DB Explorer', pipeline: 'Pipeline', compare: 'Variant Compare' }

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
  const project = route.params.project ?? catalog[0]?.project_id ?? ''
  const scenario = route.params.scenario ?? 'uc-camera-recording'
  const scenarioItem = catalog.find((c) => c.scenario_id === scenario)
  const variant = route.params.variant ?? scenarioItem?.default_variant_id ?? ''

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPicker('open') }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') { e.preventDefault(); setSideOpen((o) => !o) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setSideOpen])

  const navigate: Ctx['navigate'] = (page, params = {}, replace = false) => nav({ page, params }, replace)
  const ctx: Ctx = { catalog, project, scenario, variant, params: route.params, navigate, openPicker: (m = 'open') => setPicker(m) }
  const link = (page: Page) => {
    const p = new URLSearchParams(Object.entries({ project, scenario, variant }).filter(([, v]) => v))
    return `#/${page}?${p.toString()}`
  }
  const socLabel = scenarioItem?.soc_ref?.replace(/^soc-/, '').replace(/^exynos/i, 'Exynos') ?? ''

  return (
    <div className="app">
      <nav className={`sidebar ${sideOpen ? '' : 'rail'}`} aria-label="주 메뉴" style={sideOpen ? { width: side.size } : undefined}>
        <div className="brand">
          <span style={{ color: 'var(--primary)', display: 'flex' }}><Icon name="db" size={22} /></span>
          {sideOpen && <span className="brand-name">ScenarioDB</span>}
        </div>
        {NAV.map((g) => (
          <div key={g.title} className="nav-group">
            {sideOpen ? <h6>{g.title}</h6> : <div className="nav-sep" />}
            {g.items.map((it) => {
              const active = 'page' in it && route.page === it.page
              const href = 'page' in it ? link(it.page) : it.href
              return (
                <a key={it.label} className={`nav-item ${active ? 'active' : ''}`} href={href} title={sideOpen ? undefined : it.label}
                  {...('href' in it ? { target: '_blank', rel: 'noreferrer' } : {})}>
                  <Icon name={it.icon} size={17} />{sideOpen && <span className="nav-label">{it.label}</span>}
                </a>
              )
            })}
          </div>
        ))}
        <div className="nav-status" title={catalogQ.error ? 'API 연결 실패' : 'API 연결됨'}>
          <span className={`dot ${catalogQ.error ? 'err' : ''}`} />
          {sideOpen && <span>{catalogQ.error ? 'API 연결 실패' : catalogQ.loading ? 'API 연결 중…' : 'API 연결됨'}</span>}
        </div>
        <button className="nav-collapse" onClick={() => setSideOpen((o) => !o)} title={`${sideOpen ? '사이드바 접기' : '사이드바 펼치기'} (Ctrl+B)`} aria-label={sideOpen ? '사이드바 접기' : '사이드바 펼치기'}>
          <Icon name="sidebar" size={16} />{sideOpen && <span>접기</span>}
        </button>
      </nav>
      {sideOpen && <Resizer axis="x" label="사이드바 폭" {...side.bind} onReset={side.reset} className="side-resizer" />}
      <div className="main">
        <header className="topbar">
          <h1>{TITLES[route.page]}</h1>
          <span className="vsep" />
          <div className="crumbs">
            {socLabel && <><span>{socLabel}</span><span className="sep">›</span></>}
            {scenarioItem?.board_type && <><span>{scenarioItem.board_type}</span><span className="sep">›</span></>}
            <span style={{ color: 'var(--text)', fontWeight: 600 }}>{scenarioItem?.scenario_name ?? scenario}</span>
            {route.page === 'pipeline' && variant && <><span className="sep">›</span>
              <button className="crumb-variant" onClick={() => setPicker('open')}>{variant}<Icon name="chevron" size={12} /></button></>}
          </div>
          <span className="grow" />
          {(route.page === 'explorer' || route.page === 'matrix') && (
            <div className="seg" role="group" aria-label="보기">
              <a className={route.page === 'explorer' ? 'on' : ''} href={link('explorer')}>Scenario별</a>
              <a className={route.page === 'matrix' ? 'on' : ''} href={link('matrix')}>전체 Matrix</a>
            </div>
          )}
          <button className="find-btn" onClick={() => setPicker('open')}>
            <Icon name="search" size={15} /><span style={{ flexGrow: 1, textAlign: 'left' }}>Variant 찾기</span><span className="kbd">Ctrl K</span>
          </button>
        </header>
        {catalogQ.error && <div className="page"><div className="err">API에 연결할 수 없습니다: {catalogQ.error}<br />FastAPI(:18000)를 실행하고 <span className="mono">npm run dev</span>의 /api 프록시를 확인하세요.</div></div>}
        {!catalogQ.error && route.page === 'explorer' && <ExplorerPage ctx={ctx} />}
        {!catalogQ.error && route.page === 'matrix' && <MatrixPage ctx={ctx} />}
        {!catalogQ.error && route.page === 'pipeline' && <PipelinePage ctx={ctx} />}
        {!catalogQ.error && route.page === 'compare' && <ComparePage ctx={ctx} />}
      </div>
      <Picker open={picker !== null} onClose={() => setPicker(null)} catalog={catalog} scenarioId={scenario}
        onPick={(s, v) => navigate(picker === 'compare' ? 'compare' : route.page === 'compare' ? 'compare' : 'pipeline',
          picker === 'compare' || route.page === 'compare' ? { scenario: s, variants: [...(route.params.variants ?? '').split(',').filter(Boolean), v].join(',') } : { scenario: s, variant: v })}
        onAddCompare={(s, v) => navigate('compare', { scenario: s, variants: [...(route.params.variants ?? variant).split(',').filter(Boolean), v].join(',') })} />
    </div>
  )
}
