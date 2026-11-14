// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { TERMS, termById, termHref } from '../lib/terms'
import { SpecBadge, specLabel } from './SpecBadge'
import { Term, TermLegend } from './Term'
import { TermsTab, termMatches } from './TermsTab'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

function render(node: React.ReactNode) {
  const host = document.createElement('div')
  const root = createRoot(host)
  act(() => root.render(node))
  return { host, unmount: () => act(() => root.unmount()) }
}

it('has one entry per id, each with a meaning, and the spec verdict reads 충족 / 미달', () => {
  expect(new Set(TERMS.map((t) => t.id)).size).toBe(TERMS.length)
  expect(TERMS.every((t) => t.meaning.length > 10)).toBe(true)
  expect(termById('spec')?.states).toEqual(['충족', '미달', '판정 미지원'])
  expect(termById('timing-verdict')?.states?.slice(0, 3)).toEqual(['OK', 'Clock ↑', 'Fail'])
  expect([specLabel(true), specLabel(false)]).toEqual(['충족', '미달'])
  expect(termHref('power-reference')).toBe('#/library?tab=terms&sel=power-reference')
})

it('finds a term by its avoided (older) wording too', () => {
  const spec = termById('spec')!
  expect(termMatches(spec, 'spec OK')).toBe(true)
  expect(termMatches(spec, '만족')).toBe(true)
  expect(termMatches(spec, 'tornado')).toBe(false)
})

it('a term opens its meaning with a link to the full table', () => {
  const r = render(<><Term id="verified" /><SpecBadge ok={false} /></>)
  const trigger = r.host.querySelector<HTMLButtonElement>('.hint-trigger')!
  expect(trigger.getAttribute('aria-label')).toBe('검증 뜻')
  expect(r.host.querySelector('[role=tooltip]')?.textContent).toContain('실측 검증이 아닙니다')
  expect(r.host.querySelector<HTMLAnchorElement>('[role=tooltip] a')?.getAttribute('href')).toBe('#/library?tab=terms&sel=verified')
  expect(r.host.querySelector('.badge')?.textContent).toBe('미달')
  r.unmount()
})

it('the legend lists the terms and the 용어 tab filters and marks the selected one', () => {
  const l = render(<TermLegend ids={['spec', 'baseline']} />)
  expect([...l.host.querySelectorAll('.hint')].map((h) => h.firstChild?.textContent)).toEqual(['spec 판정', 'baseline'])
  l.unmount()
  const t = render(<TermsTab selected="baseline" />)
  expect(t.host.querySelector('tr.selected')?.id).toBe('term-baseline')
  const input = t.host.querySelector<HTMLInputElement>('input[type=search]')!
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  act(() => { set.call(input, 'eligible'); input.dispatchEvent(new Event('input', { bubbles: true })) })
  expect([...t.host.querySelectorAll('tbody tr')].map((tr) => tr.id)).toEqual(['term-eligible'])
  t.unmount()
})
