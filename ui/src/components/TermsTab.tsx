import { useEffect, useMemo, useState } from 'react'
import { TERMS, type TermEntry } from '../lib/terms'

const FAMILIES: TermEntry['family'][] = ['판정', '기준', '결과', '대상']

export function termMatches(t: TermEntry, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return [t.term, t.meaning, ...(t.states ?? []), ...(t.avoid ?? []), t.where ?? ''].some((s) => s.toLowerCase().includes(q))
}

/** U-11: the verdict vocabulary in one place — canonical badge words, meaning, the words not to use, where. */
export function TermsTab({ selected }: { selected?: string }) {
  const [q, setQ] = useState('')
  const shown = useMemo(() => TERMS.filter((t) => termMatches(t, q)), [q])
  useEffect(() => {
    if (selected) document.getElementById(`term-${selected}`)?.scrollIntoView?.({ block: 'center' })
  }, [selected])
  return <section className="card terms" aria-label="용어">
    <div className="row" style={{ flexWrap: 'wrap', marginBottom: 8 }}>
      <input type="search" className="dt-filter" value={q} onChange={(e) => setQ(e.target.value)} placeholder="용어 · 뜻 · 예전 표현 찾기" aria-label="용어 찾기" />
      <span className="faint t-caption">badge는 "표시 단어" 열의 문구만 씁니다. "쓰지 않는 표현"은 같은 뜻의 예전 · 혼용 문구입니다. 저장소의 GLOSSARY.md(도메인 개념)와 함께 봅니다.</span>
    </div>
    {FAMILIES.map((f) => {
      const rows = shown.filter((t) => t.family === f)
      if (!rows.length) return null
      return <div key={f} className="table-x">
        <h3 style={{ fontSize: 'var(--fs-lead)', margin: '12px 0 6px' }}>{f}</h3>
        <table className="grid">
          <thead><tr><th style={{ width: 150 }}>용어</th><th style={{ width: 220 }}>표시 단어</th><th>뜻</th><th style={{ width: 200 }}>쓰지 않는 표현</th><th style={{ width: 200 }}>쓰는 곳</th></tr></thead>
          <tbody>{rows.map((t) => <tr key={t.id} id={`term-${t.id}`} className={t.id === selected ? 'selected' : ''}>
            <td><b>{t.term}</b></td>
            <td>{t.states?.map((s) => <span key={s} className="badge" style={{ marginRight: 4 }}>{s}</span>) ?? <span className="faint">—</span>}</td>
            <td style={{ whiteSpace: 'normal' }}>{t.meaning}</td>
            <td className="faint" style={{ whiteSpace: 'normal' }}>{t.avoid?.join(' · ') ?? '—'}</td>
            <td className="faint" style={{ whiteSpace: 'normal' }}>{t.where ?? '—'}</td>
          </tr>)}</tbody>
        </table>
      </div>
    })}
    {!shown.length && <div className="empty">일치하는 용어 없음</div>}
  </section>
}
