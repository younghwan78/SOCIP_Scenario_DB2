import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type CatalogItem, type ResolvedVariant, type VariantRow } from '../lib/api'
import { CAMERA_LABEL, KPI_SET, MODE_LABEL, cameraOf, kpiLabel, recordingMode, stabOf, summaryText, type Camera, type Mode } from '../lib/conditions'
import { Icon } from './Icons'

const PIN_KEY = 'sdb.pinned'
const RECENT_KEY = 'sdb.recent'
const load = (k: string): string[] => { try { return JSON.parse(localStorage.getItem(k) ?? '[]') as string[] } catch { return [] } }
const save = (k: string, v: string[]) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* storage unavailable */ } }

export function rememberRecent(scenario: string, variant: string): void {
  const key = `${scenario}::${variant}`
  save(RECENT_KEY, [key, ...load(RECENT_KEY).filter((k) => k !== key)].slice(0, 6))
}

export function toRows(scenario: CatalogItem | undefined, variants: ResolvedVariant[]): VariantRow[] {
  return variants.map((v) => ({
    project_id: scenario?.project_id ?? '', scenario_id: v.scenario_id, scenario_name: scenario?.scenario_name,
    variant_id: v.id, severity: v.severity, design_conditions: v.design_conditions ?? {}, derived_from_variant: v.derived_from_variant,
  }))
}

interface Props {
  open: boolean
  onClose: () => void
  catalog: CatalogItem[]
  scenarioId?: string
  onPick: (scenario: string, variant: string) => void
  onAddCompare?: (scenario: string, variant: string) => void
}

type Facet = { kpi: Set<string>; mode: Set<Mode>; stab: Set<string>; hdr: Set<string>; cam: Set<Camera> }
const emptyFacet = (): Facet => ({ kpi: new Set(), mode: new Set(), stab: new Set(), hdr: new Set(), cam: new Set() })

export function matches(row: VariantRow, f: Facet, query: string): boolean {
  const dc = row.design_conditions
  const mode = recordingMode(row)
  const kpi = kpiLabel(dc)
  const modeOk = (!f.kpi.size && !f.mode.size) || (mode === 'kpi' && kpi !== null && f.kpi.has(kpi)) || f.mode.has(mode) || (f.mode.has('kpi') && mode === 'kpi')
  if (!modeOk) return false
  if (f.stab.size && !f.stab.has(stabOf(dc))) return false
  if (f.hdr.size && !f.hdr.has(String(dc.hdr ?? '—'))) return false
  if (f.cam.size) { const c = cameraOf(dc); if (!c || !f.cam.has(c)) return false }
  const hay = `${row.variant_id} ${Object.values(dc).join(' ')}`.toLowerCase()
  return query.toLowerCase().split(/\s+/).filter(Boolean).every((t) => hay.includes(t))
}

export function Picker({ open, onClose, catalog, scenarioId, onPick, onAddCompare }: Props) {
  const [scenario, setScenario] = useState(scenarioId ?? 'uc-camera-recording')
  const [variants, setVariants] = useState<ResolvedVariant[]>([])
  const [query, setQuery] = useState('')
  const [facet, setFacet] = useState<Facet>(emptyFacet)
  const [showDerived, setShowDerived] = useState(false)
  const [active, setActive] = useState(0)
  const [pins, setPins] = useState<string[]>(() => load(PIN_KEY))
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => { if (open) { setScenario(scenarioId ?? scenario); setTimeout(() => inputRef.current?.focus(), 0) } }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open || !scenario) return
    let alive = true
    api.variants(scenario).then((r) => { if (alive) setVariants(r.items) }).catch(() => { if (alive) setVariants([]) })
    return () => { alive = false }
  }, [open, scenario])

  const scenarioItem = catalog.find((c) => c.scenario_id === scenario)
  const rows = useMemo(() => toRows(scenarioItem, variants), [scenarioItem, variants])
  const derivedCount = rows.filter((r) => r.derived_from_variant).length
  const results = useMemo(() => rows.filter((r) => (showDerived || !r.derived_from_variant) && matches(r, facet, query))
    .sort((a, b) => a.variant_id.localeCompare(b.variant_id)), [rows, facet, query, showDerived])
  const recent = load(RECENT_KEY)
  const quick = [...new Set([...pins, ...recent])].map((k) => k.split('::')).filter(([s]) => s === scenario).map(([, v]) => rows.find((r) => r.variant_id === v)).filter((r): r is VariantRow => !!r).slice(0, 5)
  const list = [...quick, ...results]

  useEffect(() => { setActive(0) }, [query, facet, scenario])
  if (!open) return null

  const toggle = <K extends keyof Facet>(k: K, v: Facet[K] extends Set<infer T> ? T : never) => setFacet((f) => {
    const s = new Set(f[k] as Set<unknown>)
    if (s.has(v)) s.delete(v); else s.add(v)
    return { ...f, [k]: s }
  })
  const count = (pred: (r: VariantRow) => boolean) => rows.filter((r) => !r.derived_from_variant && pred(r)).length
  const pinToggle = (vid: string) => {
    const key = `${scenario}::${vid}`
    const next = pins.includes(key) ? pins.filter((p) => p !== key) : [key, ...pins]
    setPins(next); save(PIN_KEY, next)
  }
  const pick = (r: VariantRow | undefined, compare = false) => {
    if (!r) return
    rememberRecent(scenario, r.variant_id)
    if (compare && onAddCompare) onAddCompare(scenario, r.variant_id)
    else onPick(scenario, r.variant_id)
    onClose()
  }
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') onClose()
    else if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, list.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); pick(list[active], e.shiftKey) }
  }
  const stabValues = [...new Set(rows.map((r) => stabOf(r.design_conditions)))].sort()
  const hdrValues = [...new Set(rows.map((r) => r.design_conditions.hdr).filter(Boolean).map(String))].sort()

  return (
    <div className="backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label="Variant 찾기" onKeyDown={onKey}>
        <div className="dialog-head">
          <Icon name="search" size={18} />
          <input ref={inputRef} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="variant 검색 (공백 = AND, 예: uhd30 vdis)" aria-label="Variant 검색" />
          <span className="mono faint" style={{ fontSize: 12 }}>{scenarioItem?.scenario_name ?? scenario} · {rows.length}</span>
          <button className="btn" onClick={onClose} aria-label="닫기"><Icon name="close" /></button>
        </div>
        <div className="dialog-facets">
          <div className="facet-row">
            <span className="facet-label">Scenario</span>
            {catalog.filter((c) => c.category.includes('camera') || c.scenario_id === scenario).map((c) => (
              <button key={c.scenario_id} className={`facet ${c.scenario_id === scenario ? 'on' : ''}`} onClick={() => { setScenario(c.scenario_id); setFacet(emptyFacet()) }}>{c.scenario_name}</button>
            ))}
            <select aria-label="다른 scenario" value="" onChange={(e) => { if (e.target.value) { setScenario(e.target.value); setFacet(emptyFacet()) } }}>
              <option value="">다른 scenario…</option>
              {catalog.filter((c) => !c.category.includes('camera')).map((c) => <option key={c.scenario_id} value={c.scenario_id}>{c.scenario_name}</option>)}
            </select>
          </div>
          <div className="facet-row">
            <span className="facet-label">Mode</span>
            <span className="facet-box">
              <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--primary-strong)', marginRight: 2 }}>KPI</span>
              {KPI_SET.map((k) => {
                const n = count((r) => recordingMode(r) === 'kpi' && kpiLabel(r.design_conditions) === k)
                return <button key={k} className={`facet ${facet.kpi.has(k) ? 'on' : ''}`} disabled={!n} onClick={() => toggle('kpi', k)}>{k} {n || ''}</button>
              })}
            </span>
            {(['pro', 'slow', 'portrait', 'none'] as Mode[]).map((m) => {
              const n = count((r) => recordingMode(r) === m)
              return <button key={m} className={`facet ${facet.mode.has(m) ? 'on' : ''}`} disabled={!n} onClick={() => toggle('mode', m)}>{MODE_LABEL[m]} {n || ''}</button>
            })}
          </div>
          <div className="facet-row">
            <span className="facet-label">Stab</span>
            {stabValues.map((s) => <button key={s} className={`facet ${facet.stab.has(s) ? 'on' : ''}`} onClick={() => toggle('stab', s)}>{s} {count((r) => stabOf(r.design_conditions) === s)}</button>)}
            {hdrValues.length > 0 && <span className="facet-label" style={{ width: 34, marginLeft: 12 }}>HDR</span>}
            {hdrValues.map((h) => <button key={h} className={`facet ${facet.hdr.has(h) ? 'on' : ''}`} onClick={() => toggle('hdr', h)}>{h}</button>)}
          </div>
          <div className="facet-row">
            <span className="facet-label">Camera</span>
            {(Object.keys(CAMERA_LABEL) as Camera[]).map((c) => {
              const n = count((r) => cameraOf(r.design_conditions) === c)
              return <button key={c} className={`facet ${facet.cam.has(c) ? 'on' : ''}`} disabled={!n} title={n ? '' : 'sensor 역할 매핑이 필요합니다'} onClick={() => toggle('cam', c)}>{CAMERA_LABEL[c]} {n || ''}</button>
            })}
          </div>
        </div>
        <div style={{ overflowY: 'auto', flexGrow: 1 }}>
          {quick.length > 0 && <div className="section-label">PINNED · 최근</div>}
          {quick.map((r, i) => <Row key={`q-${r.variant_id}`} r={r} active={i === active} pinned={pins.includes(`${scenario}::${r.variant_id}`)} onPin={pinToggle} onPick={pick} />)}
          <div className="section-label">
            <span>결과 {results.length}</span><span className="grow" />
            {derivedCount > 0 && <label style={{ display: 'flex', gap: 6, fontWeight: 400, letterSpacing: 0, color: 'var(--muted)' }}>
              <input type="checkbox" checked={showDerived} onChange={(e) => setShowDerived(e.target.checked)} />파생 variant {derivedCount}개 표시</label>}
          </div>
          {results.map((r, i) => <Row key={r.variant_id} r={r} active={i + quick.length === active} pinned={pins.includes(`${scenario}::${r.variant_id}`)} onPin={pinToggle} onPick={pick} />)}
          {!results.length && <div className="empty">조건에 맞는 variant가 없습니다.</div>}
        </div>
        <div className="dialog-foot">
          <span><span className="mono">↑↓</span> 이동</span><span><span className="mono">Enter</span> 열기</span>
          {onAddCompare && <span><span className="mono">Shift+Enter</span> Compare에 추가</span>}<span>★ pin</span>
        </div>
      </div>
    </div>
  )
}

function Row({ r, active, pinned, onPin, onPick }: { r: VariantRow; active: boolean; pinned: boolean; onPin: (v: string) => void; onPick: (r: VariantRow, compare?: boolean) => void }) {
  return (
    <div className={`pick-row ${active ? 'active' : ''}`} role="button" tabIndex={-1} onClick={(e) => onPick(r, e.shiftKey)}>
      <button className="btn" style={{ padding: '2px 6px', color: pinned ? 'var(--primary)' : 'var(--disabled)' }} aria-label={pinned ? 'pin 해제' : 'pin'}
        onClick={(e) => { e.stopPropagation(); onPin(r.variant_id) }}><Icon name="star" size={13} /></button>
      <span className="vid">{r.variant_id}</span>
      <span className="cond">{summaryText(r.design_conditions) || '조건 요약 없음'}{r.derived_from_variant ? ` · ← ${r.derived_from_variant}` : ''}</span>
      {r.severity && <span className={`badge load-${r.severity}`}>{r.severity}</span>}
    </div>
  )
}
