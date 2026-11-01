import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { ProfileSelect } from './ProfileSelect'
import { TimingInputsBody, type TimingInputs } from './TimingInputsHelp'
import { appliedCpuModel, statisticOf, statParam } from '../lib/timingBudget'
import { defaultPowerParams, effectiveProfile, type SimProfile } from '../lib/simProfile'

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
  // pipelined: SW moves the verdict / output interval when a task (or one CPU's sum) passes the period, never the HW side
  expect(html).toContain('SW ms · SW 여유 · CPU mW · 판정 · 출력 간격')
  expect(html).toContain('처리량 기준이 stage 1 frame이면 NRT · Post clock · HW ms도')
  expect(html).toContain('HW ms · clock · BW GB/s')
  const stage = renderToStaticMarkup(createElement(TimingInputsBody, { inputs: { ...inputs, throughput: 'stage', statistic: 'max', measured: null, pinnedDomains: ['CAM'] } }))
  expect(stage).toContain('SW ms · SW 여유 · CPU mW · NRT · Post 필요 clock · DVFS level · HW ms · 판정 · 출력 간격')
  expect(stage).toContain('DVFS level 고정: CAM은 clock 그대로')
  expect(stage).not.toContain('HW ms · clock · BW GB/s')
  expect(stage).toContain('<b>max</b><')
  // measured CPU profile: CPU power does not follow the SW statistic
  const prof = renderToStaticMarkup(createElement(TimingInputsBody, { inputs: { ...inputs, cpuModel: 'profile' } }))
  expect(prof).toContain('SW ms · SW 여유 · 판정')
  expect(prof).toContain('CPU 모델이 측정 profile이라 CPU mW는 SW 통계와 무관')
  expect(prof).toContain('HW ms · clock · BW GB/s · CPU mW')
})

it('describes the CPU model the server applied, not only the one requested', () => {
  const report = (kind?: 'profile' | 'flat') => ({ power: { cpu_profile: kind ? { kind } : undefined } }) as unknown as Parameters<typeof appliedCpuModel>[0]
  expect(appliedCpuModel(null, 'profile')).toBe('profile')                    // before the result: the request
  expect(appliedCpuModel(report('profile'), 'profile')).toBe('profile')
  expect(appliedCpuModel(report('flat'), 'profile')).toBe('flat')             // no usable profile: the server fell back
  expect(appliedCpuModel(report(), 'flat')).toBe('flat')
})

it('resolves the profile the server runs with', () => {
  const v1: SimProfile = { id: 'simcfg-v1', version: 1, run_config: { power_model: 'v1-vfps' } }
  expect(effectiveProfile([v1, v2], 'simcfg-v1', { config_profile_ref: 'simcfg-v2' })?.id).toBe('simcfg-v1')
  // "코드 기본값" under a basis: no profile is sent and the server applies the basis profile
  expect(effectiveProfile([v1, v2], null, { config_profile_ref: 'simcfg-v2@2' })?.id).toBe('simcfg-v2')
  expect(effectiveProfile([v1, v2], null, null)).toBeUndefined()
})

it('names the power params the server will use when the screen picks none', () => {
  expect(defaultPowerParams({ power_params_ref: 'pmp-b@1' }, v2)).toBe('pmp-b@1')
  expect(defaultPowerParams({ power_params_ref: null }, v2)).toBe('pmp-v2')   // basis without one: the chosen profile's
  expect(defaultPowerParams(null, v2)).toBe('pmp-v2')
  expect(defaultPowerParams(null, undefined)).toBeNull()
})

it('defaults the SW statistic to mean and keeps max explicit in the URL', () => {
  expect(statisticOf(undefined)).toBe('mean')
  expect(statisticOf('max')).toBe('max')
  expect(statisticOf('bogus')).toBe('mean')
  expect(statParam('mean')).toBeUndefined()
  expect(statParam('max')).toBe('max')
})
