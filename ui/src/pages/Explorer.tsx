import { useMemo, useState } from 'react'
import type { Ctx } from '../App'
import { api } from '../lib/api'
import { useAsync } from '../lib/route'
import { CAMERA_LABEL, MISSING, MODE_LABEL, cameraOf, changedKeys, medoidId, stabOf, valueText } from '../lib/conditions'
import { CATEGORY_LABEL, CATEGORY_ORDER, focusFor, modeBreakdown, primaryCategory, scenarioPurpose } from '../lib/guides'
import { toRows } from '../components/Picker'
import { PageLayout, Resizer, useResizable } from '../components/Layout'
import { Icon } from '../components/Icons'
import { DataTable, type Column } from '../components/DataTable'
import { SEVERITY_RANK, preferredReference, resFpsKey } from '../lib/defaults'
import type { VariantRow } from '../lib/api'

type FacetKey = 'resolution' | 'fps' | 'stab' | 'hdr' | 'camera'
const FACET_LABEL: Record<FacetKey, string> = { resolution: 'Res', fps: 'fps', stab: 'Stab', hdr: 'HDR', camera: 'Camera' }

function facetValue(key: FacetKey, dc: Record<string, unknown>): string | null {
  if (key === 'stab') return dc.stabilization === undefined ? null : stabOf(dc)
  if (key === 'camera') { const c = cameraOf(dc); return c ? CAMERA_LABEL[c] : null }
  const v = dc[key]
  return v === undefined || v === null || v === '' ? null : String(v)
}

export function ExplorerPage({ ctx }: { ctx: Ctx }) {
  const type = ctx.params.type ?? 'camera'
  const byType = useMemo(() => {
    const m = new Map<string, number>()
    ctx.catalog.forEach((c) => { const k = primaryCategory(c.category); m.set(k, (m.get(k) ?? 0) + 1) })
    return m
  }, [ctx.catalog])
  const variantsByType = useMemo(() => {
    const m = new Map<string, number>()
    ctx.catalog.forEach((c) => { const k = primaryCategory(c.category); m.set(k, (m.get(k) ?? 0) + c.variant_count) })
    return m
  }, [ctx.catalog])
  const totalVariants = ctx.catalog.reduce((s, c) => s + c.variant_count, 0)
  const scenarios = ctx.catalog.filter((c) => type === 'all' || primaryCategory(c.category) === type)
    .sort((a, b) => (a.scenario_id === 'uc-camera-recording' ? -1 : b.scenario_id === 'uc-camera-recording' ? 1 : a.scenario_name.localeCompare(b.scenario_name)))
  const selected = scenarios.find((s) => s.scenario_id === ctx.scenario) ?? scenarios[0]
  const variantsQ = useAsync(() => (selected ? api.variants(selected.scenario_id) : Promise.resolve({ items: [], total: 0 })), [selected?.scenario_id])
  const rows = useMemo(() => toRows(selected, variantsQ.data?.items ?? []), [selected, variantsQ.data])
  const byId = useMemo(() => new Map(rows.map((r) => [r.variant_id, r])), [rows])

  const listW = useResizable('explorer.list.w', 260, 180, 480)
  const [facets, setFacets] = useState<Partial<Record<FacetKey, Set<string>>>>({})
  const [showDerived, setShowDerived] = useState(false)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [refChoice, setRefChoice] = useState<Record<string, string>>({})
  const [search, setSearch] = useState('')
  const medoid = useMemo(() => medoidId(rows), [rows])
  const reference = (selected && refChoice[selected.scenario_id]) || preferredReference(selected?.scenario_id, rows.map((r) => r.variant_id), medoid)
  const refRow = byId.get(reference)

  const facetKeys = (['resolution', 'fps', 'stab', 'hdr', 'camera'] as FacetKey[]).filter((k) => rows.some((r) => facetValue(k, r.design_conditions) !== null))
  const visible = rows.filter((r) => (showDerived || !r.derived_from_variant)
    && facetKeys.every((k) => !facets[k]?.size || facets[k]!.has(facetValue(k, r.design_conditions) ?? ''))
    && (!search || search.toLowerCase().split(/\s+/).every((t) => `${r.variant_id} ${Object.values(r.design_conditions).join(' ')}`.toLowerCase().includes(t))))
    .sort((a, b) => a.variant_id.localeCompare(b.variant_id))
  const derivedCount = rows.filter((r) => r.derived_from_variant).length
  const toggleFacet = (k: FacetKey, v: string) => setFacets((f) => { const s = new Set(f[k] ?? []); if (s.has(v)) s.delete(v); else s.add(v); return { ...f, [k]: s } })
  const togglePick = (v: string) => setPicked((p) => { const s = new Set(p); if (s.has(v)) s.delete(v); else s.add(v); return s })
  const isCamera = selected?.category.includes('camera')

  const COLS: { key: string; label: string; get: (dc: Record<string, unknown>) => string; keys: string[] }[] = [
    { key: 'rf', label: 'Res · fps', get: (dc) => [dc.resolution, dc.fps].filter((v) => v !== undefined && v !== null && v !== '').map(valueText).join(' · ') || MISSING, keys: ['resolution', 'fps'] },
    { key: 'hdr', label: 'HDR', get: (dc) => valueText(dc.hdr), keys: ['hdr'] },
    { key: 'stab', label: 'Stabilization', get: (dc) => (dc.stabilization === undefined ? MISSING : stabOf(dc)), keys: ['stabilization'] },
    { key: 'cam', label: 'Camera', get: (dc) => { const c = cameraOf(dc); return c ? CAMERA_LABEL[c] + (dc.camera_mode && dc.camera_mode !== 'single' ? ` · ${dc.camera_mode}` : '') : MISSING }, keys: ['sensor_place', 'camera_mode'] },
    { key: 'codec', label: 'Codec · Bitrate', get: (dc) => [dc.codec_mfc, dc.record_bitrate_mbps ? `${dc.record_bitrate_mbps} Mbps` : null, dc.format].filter(Boolean).join(' · ') || MISSING, keys: ['codec_mfc', 'record_bitrate_mbps', 'format'] },
    { key: 'mode', label: 'Mode', get: (dc) => [dc.extend_mode && dc.extend_mode !== 'EX_NONE' ? String(dc.extend_mode).replace('EX_', '') : null, dc.subscenario].filter(Boolean).join(' · ') || MISSING, keys: ['extend_mode', 'subscenario'] },
  ]

  const diffOf = (r: VariantRow) => new Set(changedKeys(r, refRow, byId))
  const columns: Column<VariantRow>[] = [
    { key: 'pick', label: '', width: 34, minWidth: 30, render: (r) => <input type="checkbox" aria-label={`${r.variant_id} 선택`} checked={picked.has(r.variant_id)} onChange={() => togglePick(r.variant_id)} onClick={(e) => e.stopPropagation()} /> },
    { key: 'variant', label: 'Variant', width: 290, sticky: true, sort: (r) => r.variant_id, title: (r) => r.variant_id, render: (r) => {
      const isRef = r.variant_id === reference
      return <span className="mono" style={{ fontWeight: isRef ? 600 : 400 }}>{r.variant_id}
        {isRef && <span className="badge" style={{ background: 'var(--primary)', color: '#fff', marginLeft: 6 }}>기준</span>}
        {r.derived_from_variant && <span className="faint" style={{ marginLeft: 6, fontSize: 11 }}>← {r.derived_from_variant}</span>}</span>
    } },
    ...COLS.map((c): Column<VariantRow> => ({ key: c.key, label: c.label, width: c.key === 'codec' ? 190 : c.key === 'mode' ? 170 : 130,
      sort: c.key === 'rf' ? (r) => resFpsKey(r.design_conditions) : (r) => { const v = c.get(r.design_conditions); return v === MISSING ? null : v },
      title: (r) => c.get(r.design_conditions),
      cellClass: (r) => (r.variant_id !== reference && c.keys.some((k) => diffOf(r).has(k)) ? 'chg' : ''),
      render: (r) => c.get(r.design_conditions) })),
    { key: 'load', label: 'Load', width: 84, firstDir: -1, sort: (r) => (r.severity ? SEVERITY_RANK[r.severity] ?? 0 : null), render: (r) => r.severity && <span className={`badge load-${r.severity}`}>{r.severity}</span> },
    { key: 'delta', label: 'Δ 기준', width: 72, align: 'right', firstDir: -1, headTitle: '기준(파생은 부모)과 다른 조건 수 · 클릭 정렬', sort: (r) => (r.variant_id === reference ? 0 : diffOf(r).size), render: (r) => <span className="mono">{r.variant_id === reference ? 0 : diffOf(r).size}</span> },
    { key: 'open', label: '', width: 76, render: (r) => <a href="#" onClick={(e) => { e.preventDefault(); ctx.navigate('pipeline', { scenario: r.scenario_id, variant: r.variant_id }) }}>Pipeline</a> },
  ]

  return (
    <PageLayout id="explorer" top={
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span className="muted" style={{ fontSize: 13, marginRight: 4 }}>Scenario type <span className="faint" style={{ fontSize: 11 }}>(scenario 수)</span></span>
        <button className={`tpill ${type === 'all' ? 'on' : ''}`} onClick={() => ctx.navigate(undefined, { type: 'all' })} title={`${ctx.catalog.length} scenarios · ${totalVariants} variants`}><Icon name="all" />전체 <span className="cnt">({ctx.catalog.length})</span></button>
        {CATEGORY_ORDER.filter((c) => byType.get(c)).map((c) => (
          <button key={c} className={`tpill ${type === c ? 'on' : ''}`} onClick={() => ctx.navigate(undefined, { type: c, scenario: undefined })} title={`${byType.get(c)} scenarios · ${variantsByType.get(c) ?? 0} variants`}>
            <Icon name={c} />{CATEGORY_LABEL[c]} <span className="cnt">({byType.get(c)})</span></button>
        ))}
      </div>} main={
      <div className="explorer">
        <section className="panel scn-list" aria-label="Scenario 목록" style={{ width: listW.size }}>
          <div className="panel-head"><span className="muted" style={{ fontSize: 12, fontWeight: 600 }}>{(CATEGORY_LABEL[type] ?? '전체').toUpperCase()} · scenario ({scenarios.length}) · variant ({scenarios.reduce((n, s) => n + s.variant_count, 0)})</span></div>
          <div style={{ overflowY: 'auto' }}>
            {scenarios.map((s) => (
              <button key={s.scenario_id} className={`scn-item ${s.scenario_id === selected?.scenario_id ? 'on' : ''}`}
                onClick={() => { ctx.navigate(undefined, { scenario: s.scenario_id, variant: undefined }); setFacets({}); setPicked(new Set()) }}>
                <span className="nm">{s.scenario_name} <span className="cnt" title="variant 수">({s.variant_count})</span></span>
                <span className="ds">{scenarioPurpose(s.scenario_id).split(/[·:]/)[1]?.trim().slice(0, 42) ?? ''}</span>
                <span className="ct">variant {s.variant_count} · node {s.node_count} · buffer {s.buffer_count}</span>
              </button>
            ))}
          </div>
        </section>
        <Resizer axis="x" label="Scenario 목록 폭" {...listW.bind} onReset={listW.reset} />
        <section className="panel" aria-label="Variant 목록" style={{ flexGrow: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          {selected && <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '14px 16px', borderBottom: '1px solid var(--line-soft)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <h2 style={{ margin: 0, fontSize: 16 }}>{selected.scenario_name}</h2>
              <span className="mono faint" style={{ fontSize: 12 }}>{selected.scenario_id}</span>
              <span className="grow" />
              <label className="muted" style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>기준
                <select value={reference} onChange={(e) => setRefChoice((r) => ({ ...r, [selected.scenario_id]: e.target.value }))}>
                  {rows.filter((r) => !r.derived_from_variant).map((r) => <option key={r.variant_id} value={r.variant_id}>{r.variant_id}{selected && preferredReference(selected.scenario_id, [r.variant_id], '') === r.variant_id ? ' (기본 기준)' : r.variant_id === medoid ? ' (대표·자동)' : ''}</option>)}
                </select>
              </label>
            </div>
            <div className="desc-box">
              <p>{scenarioPurpose(selected.scenario_id)}</p>
              {isCamera && rows.length > 0 && <div className="facet-row"><span className="faint" style={{ fontSize: 12 }}>구성</span>
                {modeBreakdown(rows.filter((r) => !r.derived_from_variant)).map(({ mode, count }) => <span key={mode} className="focus">{mode === 'kpi' ? 'Video recording · 기본 KPI' : MODE_LABEL[mode]} <span className="cnt">({count})</span></span>)}
                {derivedCount > 0 && <span className="focus">파생(explored/timing) <span className="cnt">({derivedCount})</span></span>}</div>}
              {isCamera && <div className="facet-row"><span className="faint" style={{ fontSize: 12 }}>검토 초점</span>
                {(() => { const f = focusFor(rows); return <>{f.slice(0, 6).map((x) => <span key={x} className="focus">{x}</span>)}{f.length > 6 && <span className="faint" style={{ fontSize: 12 }} title={f.slice(6).join(' · ')}>+{f.length - 6}</span>}</> })()}</div>}
              <div className="facet-row"><span className="faint" style={{ fontSize: 12 }}>Load</span>
                {Object.entries(selected.severity_counts).map(([k, v]) => <span key={k} className={`badge load-${k}`}>{k} <span className="cnt">({v})</span></span>)}
                <span className="faint" style={{ fontSize: 12 }}>· 작성자가 저장한 부하 등급이며 KPI 통과 여부가 아닙니다</span></div>
            </div>
            <div className="facet-row">
              {facetKeys.map((k) => {
                const counts = new Map<string, number>()
                rows.filter((r) => !r.derived_from_variant).forEach((r) => { const v = facetValue(k, r.design_conditions); if (v) counts.set(v, (counts.get(v) ?? 0) + 1) })
                return (
                  <span key={k} style={{ display: 'inline-flex', gap: 4, alignItems: 'center', marginRight: 14 }}>
                    <span className="faint" style={{ fontSize: 12, marginRight: 4 }}>{FACET_LABEL[k]}</span>
                    {[...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6).map(([v, n]) => (
                      <button key={v} className={`facet ${facets[k]?.has(v) ? 'on' : ''}`} onClick={() => toggleFacet(k, v)}>{v} <span className="cnt">({n})</span></button>
                    ))}
                  </span>
                )
              })}
              <span className="input" style={{ width: 200 }}><Icon name="search" size={14} /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="variant·조건 검색" aria-label="variant 검색" /></span>
            </div>
          </div>}
          <div className="table-scroll" style={{ flexGrow: 1 }}>
            {variantsQ.error && <div className="err" style={{ margin: 12 }}>{variantsQ.error}</div>}
            <DataTable id="explorer.variants" columns={columns} rows={visible} rowKey={(r) => r.variant_id}
              rowClass={(r) => (r.variant_id === reference ? 'sel' : '')} pinTop={(r) => r.variant_id === reference} />
            {!variantsQ.loading && !visible.length && <div className="empty">조건에 맞는 variant가 없습니다.</div>}
            {variantsQ.loading && <div className="empty">불러오는 중…</div>}
          </div>
          <div className="footer-bar">
            <span style={{ fontSize: 13 }}><b>{picked.size}개</b> 선택됨</span>
            <span className="faint" style={{ fontSize: 12 }}>{rows.length}개 중 {visible.length}개 표시 · 노란 셀 = 기준(파생은 부모)과 다른 조건 · 헤더 클릭 정렬 · 헤더 경계 drag 폭 조절</span>
            {derivedCount > 0 && <label className="muted" style={{ fontSize: 12, display: 'flex', gap: 6 }}><input type="checkbox" checked={showDerived} onChange={(e) => setShowDerived(e.target.checked)} />파생 {derivedCount}개 표시</label>}
            <span className="grow" />
            <button className="btn" disabled={!picked.size} onClick={() => ctx.navigate('pipeline', { scenario: selected?.scenario_id, variant: [...picked][0] })}>Pipeline 열기</button>
            <button className="btn primary" disabled={!picked.size} onClick={() => ctx.navigate('compare', { scenario: selected?.scenario_id, variants: [reference, ...[...picked].filter((p) => p !== reference)].join(',') })}>
              기준 + 선택 {picked.size}개 비교</button>
          </div>
        </section>
      </div>} />
  )
}
