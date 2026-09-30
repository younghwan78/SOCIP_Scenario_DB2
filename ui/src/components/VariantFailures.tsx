// Per-variant failures of a fleet / exploration run. Collapsed by default:
// the summary line names the count and causes; expanding lists every variant
// grouped by cause with stage, exception, full message, raising location and hint.
export interface VariantFailure {
  variant_id: string
  scenario_id?: string
  stage?: string
  error_type?: string
  category?: string
  error: string
  location?: string | null
  hint?: string | null
}

const CATEGORY_LABEL: Record<string, string> = {
  sw_stage_budget: 'SW stage budget / PPC',
  sw_timing: 'SW timing 값',
  buffer: 'Buffer / compression',
  sensor: 'Sensor',
  dvfs: 'DVFS',
  power_params: 'Power params',
  measured_profile: '실측 timing profile',
  shape: 'Size / shape',
  scope_limit: '탐색 범위 상한',
  reference: 'DB 참조 누락',
  internal: '내부 오류',
  other: '기타',
}

export function groupFailures(errors: VariantFailure[]): { key: string; category: string; message: string; hint?: string | null; items: VariantFailure[] }[] {
  const groups = new Map<string, { key: string; category: string; message: string; hint?: string | null; items: VariantFailure[] }>()
  for (const e of errors) {
    const category = e.category ?? 'other'
    // Same cause across variants usually differs only in ids/numbers; group on the message shape.
    const shape = e.error.replace(/[0-9]+(\.[0-9]+)?/g, '#')
    const key = `${category}|${shape}`
    const g = groups.get(key) ?? { key, category, message: e.error, hint: e.hint, items: [] }
    g.items.push(e)
    groups.set(key, g)
  }
  return [...groups.values()].sort((a, b) => b.items.length - a.items.length)
}

export function VariantFailures({ errors }: { errors: VariantFailure[] }) {
  if (!errors.length) return null
  const groups = groupFailures(errors)
  const causes = [...new Set(groups.map((g) => CATEGORY_LABEL[g.category] ?? g.category))]
  return (
    <details className="err vf">
      <summary>
        {errors.length}개 variant 계산 실패 — 원인 {groups.length}종 ({causes.join(', ')}) <span className="faint">· 펼쳐서 상세 보기</span>
      </summary>
      {groups.map((g) => (
        <div key={g.key} className="vf-group">
          <div className="vf-head"><span className="chip">{CATEGORY_LABEL[g.category] ?? g.category}</span> <b>{g.items.length}개</b></div>
          {g.hint && <div className="vf-hint">{g.hint}</div>}
          <table className="grid vf-table">
            <thead><tr><th>variant</th><th>단계</th><th>예외</th><th>메시지</th><th>위치</th></tr></thead>
            <tbody>{g.items.map((e) => (
              <tr key={`${e.scenario_id ?? ''}:${e.variant_id}`}>
                <td className="mono">{e.variant_id}{e.scenario_id ? <div className="faint">{e.scenario_id}</div> : null}</td>
                <td>{e.stage ?? '—'}</td>
                <td className="mono">{e.error_type ?? '—'}</td>
                <td><pre className="vf-msg">{e.error}</pre></td>
                <td className="mono faint">{e.location ?? '—'}</td>
              </tr>))}</tbody>
          </table>
        </div>
      ))}
    </details>
  )
}
