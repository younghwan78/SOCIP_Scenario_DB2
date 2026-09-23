import { useMemo, useState } from 'react'
import type { Ctx } from '../App'
import { api, type VariantRow } from '../lib/api'
import { useAsync } from '../lib/route'
import { matrixColumns, medoidId } from '../lib/conditions'
import { scenarioPurpose } from '../lib/guides'
import { Icon } from '../components/Icons'

const COLS = ['Res · fps', 'Mode · Format', 'Output · HDR', 'Stab', 'Camera', 'Codec · Rate', 'Screen']

export function MatrixPage({ ctx }: { ctx: Ctx }) {
  const q = useAsync(() => api.matrix(), [])
  const [open, setOpen] = useState<Set<string>>(new Set(['uc-camera-recording', 'uc-camera-preview', 'uc-camera-capture']))
  const [search, setSearch] = useState('')
  const [load, setLoad] = useState('')
  const [picked, setPicked] = useState<Set<string>>(new Set())

  const groups = useMemo(() => {
    const m = new Map<string, VariantRow[]>()
    for (const r of q.data?.items ?? []) {
      if (!m.has(r.scenario_id)) m.set(r.scenario_id, [])
      m.get(r.scenario_id)!.push(r)
    }
    const order = ctx.catalog.map((c) => c.scenario_id)
    return [...m.entries()].sort((a, b) => (order.indexOf(a[0]) - order.indexOf(b[0])) || a[0].localeCompare(b[0]))
      .sort((a, b) => Number(!a[0].includes('camera')) - Number(!b[0].includes('camera')))
  }, [q.data, ctx.catalog])

  const match = (r: VariantRow) => (!load || r.severity === load) && (!search || search.toLowerCase().split(/\s+/).every((t) => `${r.variant_id} ${Object.values(r.design_conditions).join(' ')}`.toLowerCase().includes(t)))
  const pickedScenarios = new Set([...picked].map((k) => k.split('::')[0]))
  const total = q.data?.items.length ?? 0

  return (
    <div className="page">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>전체 Variant Matrix</h2>
        <span className="muted" style={{ fontSize: 13 }}>{groups.length} scenarios · {total} variants · scenario별 묶음, 공통 열 기준</span>
        <span className="grow" />
        <span className="input" style={{ width: 240 }}><Icon name="search" size={14} /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="variant, 조건 검색" aria-label="검색" /></span>
        <select value={load} onChange={(e) => setLoad(e.target.value)} aria-label="Load">
          <option value="">Load: 전체</option>{['light', 'medium', 'heavy', 'critical'].map((l) => <option key={l} value={l}>{l}</option>)}
        </select>
        <button className="btn" onClick={() => setOpen(new Set(groups.map(([g]) => g)))}>모두 펼치기</button>
        <button className="btn" onClick={() => setOpen(new Set())}>모두 접기</button>
      </div>
      {q.error && <div className="err">{q.error}</div>}
      <div className="panel table-scroll" style={{ flexGrow: 1 }}>
        <table className="grid">
          <thead><tr><th style={{ width: 28 }} aria-label="선택" /><th className="rowhead">Variant</th>{COLS.map((c) => <th key={c}>{c}</th>)}<th>Load</th></tr></thead>
          <tbody>
            {groups.map(([sid, rows]) => {
              const shown = rows.filter(match)
              const isOpen = open.has(sid) || !!search
              const name = rows[0]?.scenario_name ?? sid
              const ref = medoidId(rows)
              const refCols = matrixColumns(rows.find((r) => r.variant_id === ref)?.design_conditions ?? {})
              return [
                <tr key={`g-${sid}`} className="group-row" onClick={() => setOpen((o) => { const s = new Set(o); if (s.has(sid)) s.delete(sid); else s.add(sid); return s })}>
                  <td colSpan={COLS.length + 3}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
                      <span className="faint" style={{ width: 12 }}>{isOpen ? '▾' : '▸'}</span><b>{name}</b>
                      <span className="mono faint" style={{ fontSize: 11 }}>{sid}</span>
                      <span className="muted" style={{ fontSize: 12, whiteSpace: 'normal' }}>{scenarioPurpose(sid).slice(0, 70)}{scenarioPurpose(sid).length > 70 ? '…' : ''}</span>
                      <span className="muted" style={{ fontSize: 12 }}>· {rows.length} variants{search || load ? ` · ${shown.length} 일치` : ''}</span>
                    </span>
                  </td>
                </tr>,
                ...(isOpen ? shown : []).map((r) => {
                  const cols = matrixColumns(r.design_conditions)
                  const key = `${sid}::${r.variant_id}`
                  return (
                    <tr key={key} className={r.variant_id === ref ? 'sel' : ''}>
                      <td><input type="checkbox" aria-label={`${r.variant_id} 선택`} checked={picked.has(key)} onChange={() => setPicked((p) => { const s = new Set(p); if (s.has(key)) s.delete(key); else s.add(key); return s })} /></td>
                      <td className="mono rowhead">{r.variant_id}{r.derived_from_variant && <span className="faint" style={{ fontSize: 11, marginLeft: 6 }}>← {r.derived_from_variant}</span>}</td>
                      {COLS.map((c) => <td key={c} className={r.variant_id !== ref && cols[c] !== refCols[c] ? 'chg' : ''}>{cols[c]}</td>)}
                      <td>{r.severity && <span className={`badge load-${r.severity}`}>{r.severity}</span>}</td>
                    </tr>
                  )
                }),
              ]
            })}
          </tbody>
        </table>
        {q.loading && <div className="empty">불러오는 중…</div>}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 12 }} className="muted">
        <span>노란 셀 = scenario 안 대표 variant(음영 행)와 다른 값 · — = 해당 없음/미등록 · 열은 scenario 공통 축으로 정규화</span>
        <span className="grow" />
        {picked.size > 0 && pickedScenarios.size > 1 && <span>비교는 같은 scenario 안에서만 가능합니다</span>}
        <button className="btn primary" disabled={picked.size < 2 || pickedScenarios.size !== 1}
          onClick={() => ctx.navigate('compare', { scenario: [...pickedScenarios][0], variants: [...picked].map((k) => k.split('::')[1]).join(',') })}>선택 {picked.size}개 비교</button>
      </div>
    </div>
  )
}
