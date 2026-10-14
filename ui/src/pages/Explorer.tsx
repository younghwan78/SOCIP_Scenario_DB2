import { useCallback, useMemo, useState, type CSSProperties } from 'react'
import type { Ctx } from '../App'
import { api } from '../lib/api'
import { useAsync } from '../lib/route'
import { CAMERA_LABEL, MISSING, MODE_LABEL, cameraOf, changedKeys, medoidId, stabOf, valueText } from '../lib/conditions'
import { CATEGORY_COLOR, CATEGORY_LABEL, CATEGORY_ORDER, focusFor, modeBreakdown, primaryCategory, scenarioPurpose } from '../lib/guides'
import { toRows } from '../components/Picker'
import { PageLayout, Resizer, usePref, useResizable } from '../components/Layout'
import { Icon } from '../components/Icons'
import { DataTable, type Column } from '../components/DataTable'
import { SEVERITY_RANK, preferredReference, resFpsKey } from '../lib/defaults'
import type { MemoryLevers, VariantRow } from '../lib/api'
import { archApi, type BoardRow } from '../lib/archExplore'
import { verdictChip } from '../lib/timingBudget'
import { ProvBadge } from '../components/Provenance'
import { VERDICT_HELP, VerdictPopover } from '../components/VerdictDetail'
import { BasisInfoButton } from '../components/BasisDetail'
import { calibrationApi, freshnessOf, measTooltip, predictionTooltip, simTooltip, uniqueShortIds, type Coverage } from '../lib/calibration'
import { batteryNote, maText, useBattery } from '../lib/battery'
import { DEFAULT_CANONICAL, canonicalOf } from '../lib/projects'

type FacetKey = 'resolution' | 'fps' | 'stab' | 'hdr' | 'camera'
const FACET_LABEL: Record<FacetKey, string> = { resolution: 'Res', fps: 'fps', stab: 'Stab', hdr: 'HDR', camera: 'Camera' }

function facetValue(key: FacetKey, dc: Record<string, unknown>): string | null {
  if (key === 'stab') return dc.stabilization === undefined ? null : stabOf(dc)
  if (key === 'camera') { const c = cameraOf(dc); return c ? CAMERA_LABEL[c] : null }
  const v = dc[key]
  return v === undefined || v === null || v === '' ? null : String(v)
}

const catRank = (c: string[]) => { const i = (CATEGORY_ORDER as readonly string[]).indexOf(primaryCategory(c)); return i < 0 ? 99 : i }
const catStyle = (c: string) => ({ '--cat': CATEGORY_COLOR[c] ?? CATEGORY_COLOR.other } as CSSProperties)

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
    .sort((a, b) => catRank(a.category) - catRank(b.category)
      || (canonicalOf(a) === DEFAULT_CANONICAL ? -1 : canonicalOf(b) === DEFAULT_CANONICAL ? 1 : a.scenario_name.localeCompare(b.scenario_name)))
  const selected = scenarios.find((s) => s.scenario_id === ctx.scenario) ?? scenarios[0]
  const variantsQ = useAsync(() => (selected ? api.variants(selected.scenario_id) : Promise.resolve({ items: [], total: 0 })), [selected?.scenario_id])
  const rows = useMemo(() => toRows(selected, variantsQ.data?.items ?? []), [selected, variantsQ.data])
  // memory power levers (LLC / SBWC / vOTF) per variant — server-side summary from the variant matrix
  const leverQ = useAsync(() => (selected ? api.matrix(undefined, selected.scenario_id).then((r) => new Map(r.items.map((x) => [x.variant_id, x.memory_levers ?? null]))).catch(() => null)
    : Promise.resolve(null)), [selected?.scenario_id])
  // evidence coverage is optional: an older API without /calibration/coverage just hides the columns' content
  const covQ = useAsync(() => (selected ? calibrationApi.coverage(selected.scenario_id).catch(() => null) : Promise.resolve(null)), [selected?.scenario_id])
  // freshness (re-resolves every prediction's inputs, ~1-2 s) arrives after coverage and only fills the ✓ / ⚠ mark
  const freshQ = useAsync(() => (selected ? archApi.freshness(selected.scenario_id).catch(() => null) : Promise.resolve(null)), [selected?.scenario_id])
  const covMerged = useMemo(() => {
    if (!covQ.data) return null
    const fr = new Map((freshQ.data?.rows ?? []).map((x) => [x.prediction_id, x]))
    return Object.fromEntries(Object.entries(covQ.data).map(([k, c]) => {
      const p = c.current_prediction
      if (!p || p.freshness || !freshQ.data) return [k, c]
      const f = fr.get(p.id)
      return [k, { ...c, current_prediction: { ...p, freshness: { status: f?.status ?? 'unknown', reasons: f?.reasons ?? ['판정 결과 없음'], changed: f?.changed ?? [] } } }]
    })) as Record<string, Coverage>
  }, [covQ.data, freshQ.data])
  const freshPending = freshQ.loading
  const cov = (v: string): Coverage | undefined => covMerged?.[v]
  const battery = useBattery(ctx.project, ctx.params.cfg)
  // U12: registered prediction power + its timing verdict so the table reads as a dashboard
  const boardQ = useAsync(() => (selected ? archApi.board(selected.scenario_id).catch(() => null) : Promise.resolve(null)), [selected?.scenario_id])
  const board = useMemo(() => new Map((boardQ.data?.rows ?? []).map((b): [string, BoardRow] => [b.variant_id, b])), [boardQ.data])
  const shortIds = useMemo(() => uniqueShortIds([...Object.values(covQ.data ?? {}).map((c) => c.current_prediction?.id), ...board.values()].map((x) => (typeof x === 'string' ? x : x?.id))), [covQ.data, board])
  const copyId = (id: string) => { try { void navigator.clipboard?.writeText(id) } catch { /* clipboard unavailable */ } }
  const byId = useMemo(() => new Map(rows.map((r) => [r.variant_id, r])), [rows])

  const listW = useResizable('explorer.list.w', 260, 180, 480)
  const [facets, setFacets] = useState<Partial<Record<FacetKey, Set<string>>>>({})
  const [showDerived, setShowDerived] = useState(false)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [refChoice, setRefChoice] = useState<Record<string, string>>({})
  const [search, setSearch] = useState('')
  const medoid = useMemo(() => medoidId(rows), [rows])
  const reference = (selected && refChoice[selected.scenario_id]) || preferredReference(selected ? canonicalOf(selected) : undefined, rows.map((r) => r.variant_id), medoid)
  const refRow = byId.get(reference)
  const isRef = useCallback((r: VariantRow) => r.variant_id === reference, [reference])
  const [descOpen, setDescOpen] = usePref('explorer.desc.open', true)
  const [verdictAt, setVerdictAt] = useState<{ id: string; x: number; y: number } | null>(null)

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

  const hasLever = [...(leverQ.data?.values() ?? [])].some((m) => !!(m?.llc?.length || m?.compressed?.length || m?.votf?.length))
  const memOf = (id: string) => leverQ.data?.get(id) ?? null
  const llcText = (m: MemoryLevers | null) => (!m?.llc?.length ? MISSING : m.llc_mb ? `${m.llc_mb} MB${m.llc_unsized ? ' +?' : ''}` : '크기 미정')
  const sbwcText = (m: MemoryLevers | null) => (m?.compressed_dma ? `${m.compressed_dma} DMA` : MISSING)
  const memCols: Column<VariantRow>[] = [
    { key: 'llc', label: 'LLC', width: 76, align: 'right', firstDir: -1,
      headTitle: 'LLC 할당 크기 — IP partition(allocation_owner)별 llc_allocation_mb 합 · hover = owner · buffer · DRAM 계수',
      sort: (r) => memOf(r.variant_id)?.llc_mb ?? (memOf(r.variant_id)?.llc?.length ? 0 : null),
      title: (r) => { const m = memOf(r.variant_id); return m?.llc?.length ? `owner ${m.llc_owners?.join(', ') || '—'} · buffer ${m.llc.join(', ')}${m.llc_weight_min ? ` · DRAM ×${m.llc_weight_min}` : ''}` : 'LLC 없음' },
      cellClass: (r) => (r.variant_id !== reference && llcText(memOf(r.variant_id)) !== llcText(memOf(reference)) ? 'chg' : ''),
      render: (r) => llcText(memOf(r.variant_id)) },
    { key: 'sbwc', label: '압축 DMA', width: 76, align: 'right', firstDir: -1,
      headTitle: 'SBWC/AFBC 압축이 적용된 DMA 수 — 압축 buffer를 쓰는 WDMA + RDMA port · hover = buffer',
      sort: (r) => memOf(r.variant_id)?.compressed_dma || null,
      title: (r) => { const m = memOf(r.variant_id); return m?.compressed?.length ? `buffer ${m.compressed.join(', ')}` : '압축 없음' },
      cellClass: (r) => (r.variant_id !== reference && sbwcText(memOf(r.variant_id)) !== sbwcText(memOf(reference)) ? 'chg' : ''),
      render: (r) => sbwcText(memOf(r.variant_id)) },
    { key: 'votf', label: 'vOTF', width: 64, align: 'right', firstDir: -1,
      headTitle: '활성 vOTF 연결 수 — DRAM 왕복 없는 streaming 연결',
      sort: (r) => memOf(r.variant_id)?.votf?.length ?? null,
      title: (r) => memOf(r.variant_id)?.votf?.join(', ') || 'vOTF 없음',
      cellClass: (r) => (r.variant_id !== reference && JSON.stringify(memOf(r.variant_id)?.votf ?? []) !== JSON.stringify(memOf(reference)?.votf ?? []) ? 'chg' : ''),
      render: (r) => memOf(r.variant_id) ? memOf(r.variant_id)?.votf?.length || MISSING : MISSING },
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
    // 예측 = which model basis the registered number rests on + whether today's inputs still give it (not a count)
    { key: 'pred', label: '예측 기준', width: 150, firstDir: -1,
      headTitle: '등록 예측의 기준 = config profile · power params · engine (cfg2 · pmp2 · e11)\n셀에는 예외만 표시: ⚠ 기준 = 설정/params/DVFS/engine 변경 · ⚠ 데이터 = variant YAML 변경 (표가 뜬 뒤 1~2초 안에 채워짐)\n표시 없음 = 현재 입력으로 같은 결과 또는 판정 불가 — hover의 상태 줄에서 구분\nhover = 기준 구성 · SW timing · 등록 횟수 · B<n> 클릭 = 기준 상세 · 그 외 클릭 = ID 복사\n(즉석 Simulate 결과는 표에 표시하지 않음 — hover에 건수)',
      sort: (r) => { const p = cov(r.variant_id)?.current_prediction; return p ? `${({ ok: 0, data: 1, basis: 2, unknown: 3 })[freshnessOf(p).level]}|${p.basis?.label ?? ''}` : null },
      title: (r) => { const c = cov(r.variant_id); if (!c?.current_prediction) return c?.simulation ? `등록 예측 없음 · ${simTooltip(c)}` : '등록 예측 없음'
        return `${predictionTooltip(c.current_prediction, shortIds.get(c.current_prediction.id))}${c.simulation ? `\n\n${simTooltip(c)}` : ''}` },
      cellClass: (r) => { const p = cov(r.variant_id)?.current_prediction; const l = p ? freshnessOf(p).level : null; return l === 'basis' || l === 'data' ? 'fr-stale' : '' },
      render: (r) => { const p = cov(r.variant_id)?.current_prediction; if (!covQ.data) return null
        if (!p) return <span className="faint">—</span>
        const f = freshnessOf(p)
        return <span style={{ cursor: 'copy', display: 'inline-flex', alignItems: 'center', gap: 4 }} onClick={(e) => { e.stopPropagation(); copyId(p.id) }}>
          {/* exceptions only: ✓ (normal) / ? (not decidable) / … (checking) stay in the hover, not in the cell */}
          {!(freshPending && !p.freshness) && (f.level === 'basis' || f.level === 'data') && <span className={`fr fr-${f.level}`}>{f.text}</span>}
          {p.basis?.basis_id
            ? <BasisInfoButton basisId={p.basis.basis_id} label={p.basis.label} warn={!!p.basis.overrides?.length}
              title={`예측 기준 ${p.basis.label}${p.basis.overrides?.length ? ` — 기준 외 입력: ${p.basis.overrides.join(', ')}` : ''}\n클릭: 기준 상세`} />
            : <span className="mono">{p.basis?.label ?? '기준 ?'}</span>}</span> } },
    { key: 'meas', label: '실측', width: 110, firstDir: -1,
      headTitle: '대표 측정 날짜 (실측 우선, 없으면 합성) · SW≠ = 실측 trace로 등록한 예측의 SW build ≠ 측정 SW (정의값 예측은 비교 안 함)\nhover = 측정별 날짜 · SW · silicon · build',
      sort: (r) => { const m = (cov(r.variant_id)?.measurements ?? [])[0]; return m ? `${m.synthetic ? 0 : 1}${m.at ?? ''}` : null },
      title: (r) => { const c = cov(r.variant_id); return c ? measTooltip(c) : '' },
      render: (r) => { const c = cov(r.variant_id); if (!covQ.data) return null
        const m = (c?.measurements ?? []).find((x) => x.shown) ?? (c?.measurements ?? [])[0]
        if (!c || !m) return c && (c.measurement || c.synthetic) ? <span>{c.measurement ? '실측' : '합성'}</span> : <span className="faint">—</span>
        // only a prediction fed by a measured trace has a SW build to compare; defined timing has none
        const psw = c.current_prediction?.sw?.source === 'measured' ? c.current_prediction.sw.ref : null
        const swDiff = psw && m.sw_baseline_ref && psw !== m.sw_baseline_ref
        return <a href={`#/calibration?scenario=${encodeURIComponent(r.scenario_id)}`} onClick={(e) => e.stopPropagation()} className={m.synthetic ? 'meas-syn' : ''}>
          {m.synthetic ? '합성 ' : ''}{(m.at ?? '').slice(5, 10).replace('-', '/') || '날짜?'}{swDiff ? <span className="fr fr-basis" title={`예측 SW ${psw} ≠ 측정 SW ${m.sw_baseline_ref}`}> · SW≠</span> : null}</a> } },
    ...COLS.map((c): Column<VariantRow> => ({ key: c.key, label: c.label, width: c.key === 'codec' ? 190 : c.key === 'mode' ? 170 : 130,
      sort: c.key === 'rf' ? (r) => resFpsKey(r.design_conditions) : (r) => { const v = c.get(r.design_conditions); return v === MISSING ? null : v },
      title: (r) => c.get(r.design_conditions),
      cellClass: (r) => (r.variant_id !== reference && c.keys.some((k) => diffOf(r).has(k)) ? 'chg' : ''),
      render: (r) => c.get(r.design_conditions) })),
    { key: 'pw', label: 'Power mW · mA', width: 150, align: 'right', firstDir: -1, headTitle: `등록(current) 예측 total power · 조합 탐색에서 등록 · ${batteryNote(battery)}`,
      sort: (r) => board.get(r.variant_id)?.power.total_mw ?? null,
      render: (r) => { const b = board.get(r.variant_id); return b ? <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}><span className="mono">{b.power.total_mw.toFixed(0)}</span><span className="mono faint" style={{ fontSize: 11 }} title={batteryNote(battery)}>{maText(b.power.total_mw, battery)}</span>
        <ProvBadge compact prov={{ kind: 'registered', engine: 'Arch exploration', id: shortIds.get(b.id) ?? b.id, at: b.created_at, notes: [`CPU ${b.power.cpu_mw.toFixed(0)} · IP ${b.power.hw_mw.toFixed(0)} · BW ${b.power.bw_mw.toFixed(0)} mW`] }} /></span> : <span className="faint">—</span> } },
    { key: 'vd', label: '판정', width: 84, headTitle: `등록 예측의 timing 판정 — 클릭하면 사유. ${VERDICT_HELP}`, sort: (r) => { const v = board.get(r.variant_id)?.verdict; return v ? ({ fail: 0, clock_up: 1, ok: 2 } as Record<string, number>)[v] ?? 3 : null },
      render: (r) => { const b = board.get(r.variant_id), v = b?.verdict; if (!v) return <span className="faint">—</span>; const c = verdictChip(v as 'ok' | 'clock_up' | 'fail')
        return <button className={`badge ${c.cls} badge-btn`} title={b?.verdict_detail?.reasons?.[0] ?? '클릭 = 판정 사유'} aria-label={`${r.variant_id} 판정 상세`}
          onClick={(e) => { e.stopPropagation(); setVerdictAt(b?.verdict_detail ? { id: r.variant_id, x: e.clientX, y: e.clientY } : null) }}>{c.label}</button> } },
    // LLC allocation (MB) / SBWC DMA count — plain cells like the condition columns, yellow = differs from 기준
    ...(hasLever ? memCols : []),
    { key: 'load', label: 'Load', width: 84, firstDir: -1, sort: (r) => (r.severity ? SEVERITY_RANK[r.severity] ?? 0 : null), render: (r) => r.severity && <span className={`badge load-${r.severity}`}>{r.severity}</span> },
    { key: 'delta', label: '다른 조건', width: 84, align: 'right', firstDir: -1, headTitle: '기준 variant(파생은 부모)와 값이 다른 조건 수 — 노란 셀이 그 조건', sort: (r) => (r.variant_id === reference ? 0 : diffOf(r).size), render: (r) => <span className="mono">{r.variant_id === reference ? 0 : diffOf(r).size}</span> },
    { key: 'open', label: '', width: 76, render: (r) => <a href="#" onClick={(e) => { e.preventDefault(); ctx.navigate('pipeline', { scenario: r.scenario_id, variant: r.variant_id }) }}>Pipeline</a> },
  ]

  return (
    <PageLayout id="explorer" top={
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span className="muted" style={{ fontSize: 13, marginRight: 4 }}>Scenario type <span className="faint" style={{ fontSize: 11 }}>(scenario 수)</span></span>
        <button className={`tpill ${type === 'all' ? 'on' : ''}`} onClick={() => ctx.navigate(undefined, { type: 'all' })} title={`${ctx.catalog.length} scenarios · ${totalVariants} variants`}><Icon name="all" />전체 <span className="cnt">({ctx.catalog.length})</span></button>
        {CATEGORY_ORDER.filter((c) => byType.get(c)).map((c) => (
          <button key={c} className={`tpill cat ${type === c ? 'on' : ''}`} style={catStyle(c)} onClick={() => ctx.navigate(undefined, { type: c, scenario: ctx.catalog.find((s) => primaryCategory(s.category) === c)?.scenario_id, variant: undefined })} title={`${byType.get(c)} scenarios · ${variantsByType.get(c) ?? 0} variants`}>
            <Icon name={c} />{CATEGORY_LABEL[c]} <span className="cnt">({byType.get(c)})</span></button>
        ))}
      </div>} main={
      <div className="explorer">
        <section className="panel scn-list" aria-label="Scenario 목록" style={{ width: listW.size }}>
          <div className="panel-head"><span className="muted" style={{ fontSize: 12, fontWeight: 600 }}>{(CATEGORY_LABEL[type] ?? '전체').toUpperCase()} · scenario ({scenarios.length}) · variant ({scenarios.reduce((n, s) => n + s.variant_count, 0)})</span></div>
          <div style={{ overflowY: 'auto' }}>
            {scenarios.map((s, i) => { const cat = primaryCategory(s.category); const head = type === 'all' && (i === 0 || primaryCategory(scenarios[i - 1].category) !== cat)
              const inCat = scenarios.filter((x) => primaryCategory(x.category) === cat)
              return <div key={s.scenario_id} className="scn-wrap" style={catStyle(cat)}>
              {head && <div className="scn-group"><span className="scn-dot" />{CATEGORY_LABEL[cat] ?? cat} <span className="cnt">scenario {inCat.length} · variant {inCat.reduce((n, x) => n + x.variant_count, 0)}</span></div>}
              <button className={`scn-item ${s.scenario_id === selected?.scenario_id ? 'on' : ''}`}
                onClick={() => { ctx.navigate(undefined, { scenario: s.scenario_id, variant: undefined }); setFacets({}); setPicked(new Set()) }}>
                <span className="nm">{s.scenario_name} <span className="cnt" title="variant 수">({s.variant_count})</span></span>
                <span className="ds">{scenarioPurpose(s.scenario_id).split(/[·:]/)[1]?.trim().slice(0, 42) ?? ''}</span>
                <span className="ct">variant {s.variant_count} · node {s.node_count} · buffer {s.buffer_count}</span>
              </button></div> })}
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
            <details className="desc-box" open={descOpen} onToggle={(e) => setDescOpen((e.currentTarget as HTMLDetailsElement).open)}>
              <summary title={descOpen ? '설명 접기' : '설명 펼치기'}>
                <span className="desc-caret" aria-hidden="true">{descOpen ? '▾' : '▸'}</span>
                {descOpen ? <span className="faint" style={{ fontSize: 12 }}>설명 · 구성 · Load</span> : <span className="desc-line">
                  <span>{scenarioPurpose(selected.scenario_id).split(/[.·:]/).slice(0, 2).join(' · ').slice(0, 60)}</span>
                  {isCamera && rows.length > 0 && <span className="faint">· {modeBreakdown(rows.filter((r) => !r.derived_from_variant)).map(({ mode, count }) => `${mode === 'kpi' ? 'KPI' : MODE_LABEL[mode]} ${count}`).join(' / ')}</span>}
                  <span className="faint">· Load {Object.entries(selected.severity_counts).map(([k, v]) => `${k} ${v}`).join(' / ')}</span></span>}
              </summary>
              <p>{scenarioPurpose(selected.scenario_id)}</p>
              {isCamera && rows.length > 0 && <div className="facet-row"><span className="faint" style={{ fontSize: 12 }}>구성</span>
                {modeBreakdown(rows.filter((r) => !r.derived_from_variant)).map(({ mode, count }) => <span key={mode} className="focus">{mode === 'kpi' ? 'Video recording · 기본 KPI' : MODE_LABEL[mode]} <span className="cnt">({count})</span></span>)}
                {derivedCount > 0 && <span className="focus">파생(explored/timing) <span className="cnt">({derivedCount})</span></span>}</div>}
              {isCamera && <div className="facet-row"><span className="faint" style={{ fontSize: 12 }}>검토 초점</span>
                {(() => { const f = focusFor(rows); return <>{f.slice(0, 6).map((x) => <span key={x} className="focus">{x}</span>)}{f.length > 6 && <span className="faint" style={{ fontSize: 12 }} title={f.slice(6).join(' · ')}>+{f.length - 6}</span>}</> })()}</div>}
              <div className="facet-row"><span className="faint" style={{ fontSize: 12 }}>Load</span>
                {Object.entries(selected.severity_counts).map(([k, v]) => <span key={k} className={`badge load-${k}`}>{k} <span className="cnt">({v})</span></span>)}
                <span className="faint" style={{ fontSize: 12 }}>· 작성자가 저장한 부하 등급이며 KPI 통과 여부가 아닙니다</span></div>
            </details>
            <div className="facet-row">
              {facetKeys.map((k) => {
                const counts = new Map<string, number>()
                rows.filter((r) => !r.derived_from_variant).forEach((r) => { const v = facetValue(k, r.design_conditions); if (v) counts.set(v, (counts.get(v) ?? 0) + 1) })
                return (
                  <span key={k} className={`facet-group fg-${k}`} role="group" aria-label={`${FACET_LABEL[k]} filter`}>
                    <span className="fg-label">{FACET_LABEL[k]}</span>
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
              rowClass={(r) => (r.variant_id === reference ? 'sel' : '')} stickyTop={isRef} />
            {!variantsQ.loading && !visible.length && <div className="empty">조건에 맞는 variant가 없습니다.</div>}
            {variantsQ.loading && <div className="empty">불러오는 중…</div>}
          </div>
          {verdictAt && board.get(verdictAt.id)?.verdict_detail && <VerdictPopover d={board.get(verdictAt.id)!.verdict_detail!} at={verdictAt} onClose={() => setVerdictAt(null)}
            onTiming={() => { const id = verdictAt.id; setVerdictAt(null); ctx.navigate('timing', { scenario: selected?.scenario_id, variant: id }) }} />}
          <div className="footer-bar">
            <span style={{ fontSize: 13 }}><b>{picked.size}개</b> 선택됨</span>
            {covQ.data && (() => { const base = rows.filter((r) => !r.derived_from_variant); const p = base.filter((r) => (cov(r.variant_id)?.simulation ?? 0) > 0 || cov(r.variant_id)?.current_prediction).length; const m = base.filter((r) => (cov(r.variant_id)?.measurement ?? 0) > 0).length
              return <span style={{ fontSize: 12, whiteSpace: 'nowrap' }} title="파생 제외 기본 variant 기준">예측 <b>{p}</b>/{base.length} · 실측 <b>{m}</b>/{base.length}</span> })()}
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
