// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { Hint } from './Hint'
import { IQ_COLOR, PCOL } from '../lib/archExplore'
import { CATEGORY_COLOR } from '../lib/guides'
import { specNotes } from '../pages/Explore'
import type { VariantResult } from '../lib/archExplore'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

function render(node: React.ReactElement) {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const root = createRoot(host)
  act(() => root.render(node))
  return { host, done: () => { act(() => root.unmount()); host.remove() } }
}

it('is reachable without a mouse: a button described by the explanation, toggled and closed by keys', () => {
  const { host, done } = render(<Hint label="판정 근거" text={'ISP stage over period\nMIF short'}><span>fail</span></Hint>)
  const button = host.querySelector('button')!
  const tip = host.querySelector('[role=tooltip]')!
  expect(button.getAttribute('aria-label')).toBe('판정 근거')
  expect(button.getAttribute('aria-describedby')).toBe(tip.id)
  expect(tip.textContent).toBe('ISP stage over period\nMIF short')
  expect(button.getAttribute('aria-expanded')).toBe('false')
  act(() => button.click())
  expect(button.getAttribute('aria-expanded')).toBe('true')
  expect(host.querySelector('.hint')!.className).toContain('open')
  act(() => { button.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
  expect(button.getAttribute('aria-expanded')).toBe('false')
  done()
})

it('renders only its content when there is nothing to explain', () => {
  const { host, done } = render(<Hint text={null}><span>ok</span></Hint>)
  expect(host.innerHTML).toBe('<span>ok</span>')
  done()
})

it('lists every reason behind a verdict, including the partial power model', () => {
  const v = { spec_reasons: ['RT HW over budget'], coverage: { zero_power_ips: ['GPU'], hw_power_modeled: true, cpu_power_modeled: true, power_coverage: 'partial' } } as unknown as VariantResult
  expect(specNotes(v)).toEqual(['RT HW over budget', '전력 미모델 IP: GPU — power는 모델된 IP 합계'])
})

it('takes chart colours from CSS tokens, so a theme redefines variables instead of call sites', () => {
  // (tokens.css defines each --name; vitest does not load CSS, the build does)
  for (const value of [...Object.values(IQ_COLOR), ...Object.values(PCOL), ...Object.values(CATEGORY_COLOR)]) {
    expect(value).toMatch(/^var\(--(iq|chart|cat)-[a-z-]+\)$/)
  }
})
