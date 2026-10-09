import { afterEach, expect, it, vi } from 'vitest'
import { runPreview, saveLabel, saveResult } from './simRun'

afterEach(() => vi.unstubAllGlobals())

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

it('previews without saving, then saves the identical request with persist: true', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(json({ items: [{ id: 'simcfg-p1', status: 'approved' }], total: 1 }))   // sim config profiles
    .mockResolvedValueOnce(json({ evidence_id: 'sim-x-1', params_hash: '0123456789abcdef', kpi: { total_power_mw: 900 }, persisted: false, cached: false }))
    .mockResolvedValueOnce(json({ evidence_id: 'sim-x-1', params_hash: '0123456789abcdef', kpi: { total_power_mw: 900 }, persisted: true, cached: false }))
  vi.stubGlobal('fetch', fetchMock)
  const done = await runPreview({ scenario: 'uc-a', variant: 'v1', project_id: 'proj-a', default_sw_profile_ref: 'sw-1' })
  const preview = JSON.parse(fetchMock.mock.calls[1][1].body)
  expect(preview.persist).toBe(false)
  expect(preview.execution_context.sw_baseline_ref).toBe('sw-1')
  expect(saveLabel(done)).toBeNull()
  const saved = await saveResult(done.req)
  const save = JSON.parse(fetchMock.mock.calls[2][1].body)
  expect(save).toEqual({ ...preview, persist: true, expected_params_hash: '0123456789abcdef' })
  expect(saved).toEqual({ status: 'saved', evidence_id: 'sim-x-1', existed: false })
  expect(saveLabel({ ...done, save: saved })).toBe('저장됨')
  expect(saveLabel({ ...done, save: { ...saved, existed: true } })).toBe('이미 저장된 동일 결과')
})

it('labels a preview that matched an already stored run', () => {
  const st = { status: 'done' as const, req: {} as never, res: { evidence_id: 'sim-1', kpi: {}, persisted: true, cached: true } }
  expect(saveLabel(st)).toBe('저장됨 (같은 조건)')
})

it('does not report saved when the server cannot confirm the preview fingerprint', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ evidence_id: 'different', persisted: true, params_hash: 'ffffffffffffffff' })))
  await expect(saveResult({ scenario_id: 's', variant_id: 'v', execution_context: {} as never,
    expected_params_hash: '0123456789abcdef' })).rejects.toThrow('저장을 확인하지 못했습니다')
})
