import { expect, it } from 'vitest'
import { clockExplanation, defaultChange, geometryError, sweepValues, validChange, type ChangeKindMeta, type SensorBinding } from './scenarioWhatIf'
it('explains DVFS clocks in Korean and preserves the shared-domain leader', () => {
  const base = { clock_reason: null, basis: 'rule' }
  expect(clockExplanation({ ...base, set_reason: 'dvfs_floor' })).toBe('최소 DVFS 단계 유지')
  expect(clockExplanation({ ...base, set_reason: 'dvfs_step' })).toBe('필요 clock을 만족하는 DVFS 단계로 올림')
  expect(clockExplanation({ ...base, set_reason: 'exact' })).toBe('요구값 적용')
  expect(clockExplanation({ ...base, set_reason: 'domain', domain_leader: 'gdc_o' })).toBe('공유 domain의 요구 clock 적용 · 기준 IP gdc_o')
})
it('keeps one value per target and leads the answer with the asked metrics', async () => {
  const { upsertChange, describeChange } = await import('./scenarioWhatIf')
  const a = upsertChange([{ target: 'fps', value: 30 }], { target: 'node_clock_mhz', node_id: 'mfc', value: 400 })
  expect(upsertChange(a, { target: 'fps', value: 60 })).toEqual([{ target: 'fps', value: 60 }, { target: 'node_clock_mhz', node_id: 'mfc', value: 400 }])
  expect(describeChange({ target: 'output_size', anchor_id: 'record_out', width: 1920, height: 1080 })).toBe('출력 크기 record_out → 1920×1080')
})
it('validates any registered kind from its metadata', async () => {
  const { validChange } = await import('./scenarioWhatIf')
  const kinds = [{ target: 'node_param', label: 'IP 설정값', shape: 'value' as const, selector: 'node_id' as const, selector_optional: true, needs_param: true, unit: 'Hz', max_value: 240, description: '', choices: [] }]
  expect(validChange({ target: 'node_param', param: 'refresh_hz', value: 120 }, kinds)).toBe(true)
  expect(validChange({ target: 'node_param', value: 120 }, kinds)).toBe(false)
  expect(validChange({ target: 'node_param', param: 'refresh_hz', value: 300 }, kinds)).toBe(false)
  expect(validChange({ target: 'unknown', value: 1 }, kinds)).toBe(false)
})

const geometry: ChangeKindMeta = { target: 'chain_size', label: 'Crop/scale', shape: 'size', selector: 'node_id', selector_optional: false, needs_param: false, unit: '', max_value: null, description: '', choices: [{ id: 'scaler', size: [3840, 2160], format: 'Y', geometry: { operations: ['crop', 'scale'], default_operation: 'crop', capabilities: { crop: { alignment: [16, 2], offset_alignment: [8, 2], formats: ['Y'], ports: ['out'] }, scale: { alignment: [16, 2], max_size: [8192, 8192], max_downscale: 4 } } } }] }
it('validates crop ROI, port, alignment, and scale limits from capabilities', () => {
  const crop = { target: 'chain_size', node_id: 'scaler', operation: 'crop' as const, width: 1920, height: 1080, x: 8, y: 2, port: 'out' }
  expect(geometryError(crop, geometry)).toBeNull()
  expect(geometryError({ ...crop, width: 1921 }, geometry)).toContain('16×2')
  expect(geometryError({ ...crop, x: 9 }, geometry)).toContain('8×2')
  expect(geometryError({ ...crop, x: 3000 }, geometry)).toContain('입력 크기')
  expect(geometryError({ ...crop, port: 'other' }, geometry)).toContain('port')
  expect(geometryError({ target: 'chain_size', node_id: 'scaler', operation: 'scale', width: 640, height: 360 }, geometry)).toContain('축소 배율')
  expect(geometryError({ target: 'chain_size', node_id: 'scaler', operation: 'scale', width: 7680, height: 4320 }, geometry)).toContain('입력 크기보다')
  expect(validChange(defaultChange(geometry, []), [geometry])).toBe(true)
})
const binding = (mode: string): SensorBinding => ({ catalog_ref: 'catalog', catalog_sha256: 'c'.repeat(64), mode_label: mode, lineup_ref: 'lineup', lineup_sha256: 'l'.repeat(64), board_config: 'board', slot: 'rear' })
const sensors: ChangeKindMeta = { target: 'sensor_binding', label: '센서', shape: 'choice', selector: 'node_id', selector_optional: false, needs_param: false, unit: '', max_value: null, description: '', choices: [{ id: 'sensor', options: [{ id: 'catalog#Mode 1', sensor_binding: binding('Mode 1'), supported: true }, { id: 'catalog#Mode 2', sensor_binding: binding('Mode 2'), supported: true }] }] }
it('pins the selected sensor binding for defaults and every sweep value', () => {
  const first = defaultChange(sensors, [])
  expect(first.sensor_binding?.mode_label).toBe('Mode 1')
  const values = sweepValues(first, sensors, 'catalog#Mode 1\ncatalog#Mode 2')
  expect(values.map((value) => value.sensor_binding?.mode_label)).toEqual(['Mode 1', 'Mode 2'])
  expect(validChange({ ...first, option: 'catalog#Mode 2' }, [sensors])).toBe(false)
  const punctuated = { ...sensors, choices: [{ ...sensors.choices[0], options: [{ id: 'catalog#Mode 1, RAW10', supported: true, sensor_binding: binding('Mode 1, RAW10') }, { id: 'catalog#Mode 2; RAW12', supported: true, sensor_binding: binding('Mode 2; RAW12') }] }] }
  expect(sweepValues(defaultChange(punctuated, []), punctuated, 'catalog#Mode 1, RAW10\ncatalog#Mode 2; RAW12').map((value) => value.option)).toEqual(['catalog#Mode 1, RAW10', 'catalog#Mode 2; RAW12'])
})
it('rejects degenerate, unbounded, unsupported and duplicate sweep values', () => {
  const fps: ChangeKindMeta = { target: 'fps', label: 'FPS', shape: 'value', selector: null, selector_optional: false, needs_param: false, unit: 'fps', max_value: 240, description: '', choices: [] }
  expect(sweepValues({ target: 'fps' }, fps, '15,30,60').map((c) => c.value)).toEqual([15, 30, 60])
  for (const raw of ['30', '30,30', '30,241', '30,Infinity', '1,2,3,4,5,6,7,8,9,10,11,12,13']) expect(() => sweepValues({ target: 'fps' }, fps, raw)).toThrow()
  expect(() => sweepValues(defaultChange(geometry, []), geometry, '1920x1080,1921x1080')).toThrow()
})
