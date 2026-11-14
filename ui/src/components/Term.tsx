import type { ReactNode } from 'react'
import { Hint } from './Hint'
import { termById, termHref } from '../lib/terms'

/** U-11: a verdict word with its meaning one focus away and a link to the full term table (Library · 용어). */
export function Term({ id, children }: { id: string; children?: ReactNode }) {
  const t = termById(id)
  if (!t) return <>{children}</>
  return <Hint label={`${t.term} 뜻`} text={<>
    <b>{t.term}</b>{t.states ? ` — ${t.states.join(' · ')}` : ''}<br />{t.meaning}<br />
    <a href={termHref(t.id)} onClick={(e) => e.stopPropagation()}>용어 전체 보기</a>
  </>}>{children ?? t.term}</Hint>
}

/** A one-line "용어:" strip for a table whose sortable headers cannot hold a button (no nested buttons). */
export function TermLegend({ ids }: { ids: string[] }) {
  return <span className="faint t-caption row-1 term-legend">용어: {ids.map((id) => <Term key={id} id={id} />)}
    <a href="#/library?tab=terms">전체</a></span>
}
