import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { verdictChip } from '../lib/timingBudget'
import { TimingVerdictBadge } from './TimingVerdictBadge'

it('shows unsupported timing in grey with an explanation outside the title', () => {
  const chip = verdictChip('not_applicable')
  expect(chip.cls).toBe('v-na')
  expect(chip.label).toBe('timing 판정 미지원')
  const html = renderToStaticMarkup(createElement(TimingVerdictBadge, { status: 'not_applicable' }))
  expect(html).toContain('badge v-na')
  expect(html).toContain('white-space:normal')
  expect(html).toContain('>timing 판정 미지원</span>')
  expect(html).toContain(`>${chip.explanation}</span>`)
  expect(html).not.toContain('충족')
})

it('keeps existing supported verdict labels and tones', () => {
  expect(verdictChip('ok')).toEqual({ label: 'OK', cls: 'v-ok' })
  expect(verdictChip('clock_up')).toEqual({ label: 'Clock ↑', cls: 'v-warn' })
  expect(verdictChip('fail')).toEqual({ label: 'Fail', cls: 'v-fail' })
})
