import { archApi, type RunDetail, type RunMeta } from '../lib/archExplore'
import { useAsync } from '../lib/route'
import { fmt } from '../lib/timingBudget'

/** U-10: the runs as a table — what tells two runs apart (profile, engine, DVFS, spec, cases, power range) —
 * instead of a select of near-identical titles. */
export function RunList({ runs, selected, compare, onPick, onCompare, showProject }: {
  runs: RunMeta[]; selected?: string; compare?: string; showProject?: boolean
  onPick: (id: string) => void; onCompare: (id: string | undefined) => void
}) {
  if (!runs.length) return null
  return <table className="tb-mini-table run-list" style={{ width: '100%' }}>
    <thead><tr>{showProject && <th>과제</th>}<th>run</th><th>생성</th><th>profile</th><th>engine</th><th>DVFS</th>
      <th className="n">spec 만족</th><th className="n">조합</th><th className="n">추천 mW</th><th /></tr></thead>
    <tbody>{runs.map((r) => {
      const s = r.summary
      return <tr key={r.id} className={r.id === selected ? 'selected' : r.id === compare ? 'compare' : ''}>
        {showProject && <td className="mono">{r.project_ref ?? '—'}</td>}
        <td><button className="link-btn" onClick={() => onPick(r.id)} aria-current={r.id === selected || undefined}>{r.title}</button></td>
        <td className="mono faint">{r.created_at?.slice(0, 16).replace('T', ' ') ?? '—'}</td>
        <td className="mono">{r.config_profile_ref ?? '기본'}</td>
        <td className="mono faint">{r.engine_rev ? r.engine_rev.replace('arch-exploration/', 'rev ') : '—'}</td>
        <td className="mono faint">{r.dvfs_table_ref ?? '미연결'}</td>
        <td className="n mono">{s ? `${s.spec_ok} / ${s.variants}` : '—'}</td>
        <td className="n mono">{s?.cases != null ? s.cases.toLocaleString() : '—'}</td>
        <td className="n mono">{s?.recommended_power_mw ? `${fmt(s.recommended_power_mw[0], 0)}–${fmt(s.recommended_power_mw[1], 0)}` : '—'}</td>
        <td>{selected && r.id !== selected && <button className="btn tb-mini" aria-pressed={r.id === compare}
          onClick={() => onCompare(r.id === compare ? undefined : r.id)}>{r.id === compare ? '비교 해제' : '선택 run과 비교'}</button>}</td>
      </tr>
    })}</tbody>
  </table>
}

export interface RunDeltaRow {
  scenario_id: string; variant_id: string
  a_mw: number | null; b_mw: number | null; delta_mw: number | null
  a_spec: boolean | null; b_spec: boolean | null
}

/** Per variant of either run: the recommended total in A and B and the change (A = the selected run, B = the
 * comparison run). Variants in one run only have a missing side. */
export function runDelta(a: RunDetail, b: RunDetail): RunDeltaRow[] {
  const key = (v: { scenario_id: string; variant_id: string }) => `${v.scenario_id}|${v.variant_id}`
  const bm = new Map(b.variants.map((v) => [key(v), v]))
  const rows: RunDeltaRow[] = []
  const seen = new Set<string>()
  for (const v of [...a.variants, ...b.variants]) {
    const k = key(v)
    if (seen.has(k)) continue
    seen.add(k)
    const va = a.variants.find((x) => key(x) === k), vb = bm.get(k)
    const am = va?.recommended?.total_mw ?? null, bmw = vb?.recommended?.total_mw ?? null
    rows.push({ scenario_id: v.scenario_id, variant_id: v.variant_id, a_mw: am, b_mw: bmw,
      delta_mw: am != null && bmw != null ? am - bmw : null, a_spec: va ? va.spec_ok : null, b_spec: vb ? vb.spec_ok : null })
  }
  return rows.sort((x, y) => Math.abs(y.delta_mw ?? 0) - Math.abs(x.delta_mw ?? 0))
}

/** What differs in how the two runs were computed (the same warning as the prediction comparison). */
export function lineageDiff(a: RunMeta, b: RunMeta): string[] {
  const out: string[] = []
  if (a.engine_rev !== b.engine_rev) out.push(`engine ${a.engine_rev} ≠ ${b.engine_rev}`)
  if ((a.config_profile_ref ?? null) !== (b.config_profile_ref ?? null)) out.push(`profile ${a.config_profile_ref ?? '기본'} ≠ ${b.config_profile_ref ?? '기본'}`)
  if ((a.dvfs_table_ref ?? null) !== (b.dvfs_table_ref ?? null)) out.push(`DVFS ${a.dvfs_table_ref ?? '미연결'} ≠ ${b.dvfs_table_ref ?? '미연결'}`)
  if ((a.soc_ref ?? null) !== (b.soc_ref ?? null)) out.push(`SoC ${a.soc_ref ?? '—'} ≠ ${b.soc_ref ?? '—'}`)
  return out
}

const signed = (v: number | null, d = 1) => (v == null ? '—' : `${v > 0 ? '+' : ''}${fmt(v, d)}`)
const specText = (v: boolean | null) => (v == null ? '없음' : v ? 'OK' : 'Fail')

export function RunDeltaView({ a, compareId, onClose }: { a: RunDetail; compareId: string; onClose: () => void }) {
  const q = useAsync(() => archApi.run(compareId), [compareId])
  if (q.error) return <div className="err">비교 run 조회 실패: {q.error}</div>
  if (!q.data) return <div className="empty">비교 run 불러오는 중…</div>
  const b = q.data
  const rows = runDelta(a, b)
  const lineage = lineageDiff(a, b)
  const changed = rows.filter((r) => r.a_spec !== r.b_spec).length
  return <section className="panel run-delta" aria-label="run 비교">
    <div className="row"><b>run 비교</b><span className="faint">A = {a.title} · B = {b.title} · Δ = A − B (추천 조합 total)</span>
      <span style={{ flex: 1 }} /><button className="btn tb-mini" onClick={onClose}>닫기</button></div>
    {lineage.length > 0 && <div className="t-caption" style={{ color: 'var(--warn-text)' }}>계산 기준이 다른 run입니다 — {lineage.join(' · ')}. Δ에는 입력 차이와 모델 차이가 함께 들어 있습니다.</div>}
    <div className="faint t-caption">variant {rows.length}개 · spec 판정이 바뀐 variant {changed}개</div>
    <table className="tb-mini-table" style={{ width: '100%' }}>
      <thead><tr><th>variant</th><th className="n">A mW</th><th className="n">B mW</th><th className="n">Δ mW</th><th>spec A / B</th></tr></thead>
      <tbody>{rows.map((r) => <tr key={`${r.scenario_id}|${r.variant_id}`}>
        <td className="mono">{r.variant_id}</td>
        <td className="n mono">{r.a_mw == null ? '—' : fmt(r.a_mw, 1)}</td>
        <td className="n mono">{r.b_mw == null ? '—' : fmt(r.b_mw, 1)}</td>
        <td className="n mono" style={{ color: r.delta_mw != null && r.delta_mw > 0 ? 'var(--del-text)' : undefined }}>{signed(r.delta_mw)}</td>
        <td className={r.a_spec !== r.b_spec ? 'err' : 'faint'} style={{ margin: 0 }}>{specText(r.a_spec)} / {specText(r.b_spec)}</td>
      </tr>)}</tbody>
    </table>
  </section>
}
