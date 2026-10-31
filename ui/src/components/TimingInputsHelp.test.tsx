import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { ProfileSelect } from './ProfileSelect'
import { TimingInputsBody, type TimingInputs } from './TimingInputsHelp'
import { statisticOf, statParam } from '../lib/timingBudget'
import type { SimProfile } from '../lib/simProfile'

const v2: SimProfile = { id: 'simcfg-v2', version: 2, status: 'draft', description: '사외 2600 profile. 계수는 SYNTHETIC (pmp-v2)',
  run_config: { power_model: 'v2-vf', power_params_ref: 'pmp-v2', include_cpu_power: true, asv_group: 4, sw_margin: 0.15, vbat: 4 } }

it('keeps the profile picker on one row with the description in the tooltip only', () => {
  const html = renderToStaticMarkup(createElement(ProfileSelect, { profiles: [v2], value: 'simcfg-v2', onChange: () => {} }))
  expect(html).toContain('>draft<')
  expect(html).toContain('>SYNTHETIC<')
  expect(html).not.toContain('>사외 2600 profile')        // not rendered as text under the select
  expect(html).toMatch(/title="simcfg-v2 v2 · draft\n사외 2600 profile/)
})

it('lists the current inputs and what each one changes', () => {
  const inputs: TimingInputs = { statistic: 'mean', throughput: 'pipelined', margin: 0.25, profile: v2, measured: { measurement_ref: 'meas-1', sw: true },
    measuredOption: null, powerParams: '', defaultPowerParams: 'pmp-v2' }
  const html = renderToStaticMarkup(createElement(TimingInputsBody, { inputs }))
  expect(html).toContain('<b>mean</b> (기본)')
  expect(html).toContain('profile의 SW margin 15%는 이 화면에서 쓰지 않습니다 — 툴바 SW margin 25% 사용')
  expect(html).toContain('입력으로 사용: SW runtime')
  expect(html).toContain('pmp-v2</span> (profile 기본)')
  expect(html).toContain('처리량 기준이 stage 1 frame이면 NRT 필요 clock · 판정도')
  const stage = renderToStaticMarkup(createElement(TimingInputsBody, { inputs: { ...inputs, throughput: 'stage', statistic: 'max', measured: null } }))
  expect(stage).toContain('SW ms · SW 여유 · CPU mW · NRT 필요 clock · DVFS level · 판정')
  expect(stage).toContain('<b>max</b><')
})

it('defaults the SW statistic to mean and keeps max explicit in the URL', () => {
  expect(statisticOf(undefined)).toBe('mean')
  expect(statisticOf('max')).toBe('max')
  expect(statisticOf('bogus')).toBe('mean')
  expect(statParam('mean')).toBeUndefined()
  expect(statParam('max')).toBe('max')
})
