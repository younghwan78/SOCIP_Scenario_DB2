import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { SimRunControls, SimSaveLine } from './SimSave'

const done = { status: 'done' as const, req: {} as never, res: { evidence_id: 'sim-1', kpi: { total_power_mw: 812.4 }, persisted: false } }
const noop = () => {}

it('offers "결과 저장" only for an unsaved preview', () => {
  expect(renderToStaticMarkup(createElement(SimRunControls, { sim: done, onRun: noop, onSave: noop }))).toContain('결과 저장')
  expect(renderToStaticMarkup(createElement(SimRunControls, { sim: done, onRun: noop, onSave: noop }))).toContain('812 mW')
  const saved = { ...done, save: { status: 'saved' as const, evidence_id: 'sim-1', existed: false } }
  const html = renderToStaticMarkup(createElement(SimSaveLine, { st: saved, onSave: noop }))
  expect(html).not.toContain('>결과 저장<')
  expect(html).toContain('저장됨')
  expect(html).not.toContain('미저장')
  expect(renderToStaticMarkup(createElement(SimRunControls, {
    sim: { ...done, save: { status: 'saving' } }, onRun: noop, onSave: noop,
  }))).toContain('disabled=""')
  expect(renderToStaticMarkup(createElement(SimRunControls, { sim: undefined, onRun: noop, onSave: noop }))).toContain('Simulation 실행')
})
