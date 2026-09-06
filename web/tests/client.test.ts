import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../src/api/client'

afterEach(() => vi.unstubAllGlobals())
const page = (items: unknown[], more = false) => ({ items, total: items.length, limit: 1000, offset: 0, has_next: more })
const response = (body: unknown) => ({ ok: true, json: async () => body })

it('unwraps all pages and normalizes real scenario metadata', async () => {
  const fetch = vi.fn().mockResolvedValueOnce(response(page([{ id: 'a', project_ref: 'p', metadata_: { name: 'Camera', category: ['camera', 'codec'] } }], true)))
    .mockResolvedValueOnce(response(page([{ id: 'b', project_ref: 'p', metadata_: {} }])))
  vi.stubGlobal('fetch', fetch)
  const rows = await api.getScenarios({ soc_ref: 'soc-a' })
  expect(rows.map(row => row.name)).toEqual(['Camera', 'b'])
  expect(rows[0].category).toBe('camera, codec')
  expect(fetch.mock.calls[1][0]).toContain('offset=1')
})

it('uses latest simulation endpoint with exact variant scope', async () => {
  const fetch = vi.fn().mockResolvedValue(response(page([{ id: 'simulation-b' }])))
  vi.stubGlobal('fetch', fetch)
  expect(await api.getLatestSimulation('scenario-a', null)).toBeNull()
  expect(fetch).not.toHaveBeenCalled()
  expect((await api.getLatestSimulation('scenario-a', 'variant-a'))?.id).toBe('simulation-b')
  expect(fetch.mock.calls[0][0]).toContain('/simulation/results?')
  expect(fetch.mock.calls[0][0]).toContain('variant_ref=variant-a')
  expect(fetch.mock.calls[0][0]).toContain('latest=true')
})

it('sends required body and credentials without query-string secrets', async () => {
  const fetch = vi.fn().mockResolvedValue(response({ evidence_id: 'sim-a', evidence: {} }))
  vi.stubGlobal('fetch', fetch)
  const context = { silicon_rev: 'EVT1', sw_baseline_ref: 'sw-a', thermal: 'nominal', method: 'calculation' as const }
  await api.runSimulation('scenario-a', 'variant-a', context, { keyId: 'analyst', apiKey: 'test-only' })
  const [url, options] = fetch.mock.calls[0]
  expect(url).toBe('/api/v1/simulation/run')
  expect(JSON.parse(options.body)).toMatchObject({ scenario_id: 'scenario-a', variant_id: 'variant-a', execution_context: context, persist: false })
  expect(options.headers.get('X-ScenarioDB-API-Key')).toBe('test-only')
})

it('includes the displayed default subsystem for level 2', async () => {
  const fetch = vi.fn().mockResolvedValue(response({}))
  vi.stubGlobal('fetch', fetch)
  await api.getView({ scenarioId: 'scenario-a', level: 2 })
  expect(fetch.mock.calls[0][0]).toContain('expand=camera')
})

it('preserves structured validation details for visible errors', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 422, statusText: 'Invalid', json: async () => ({ detail: [{ loc: ['body', 'execution_context'], msg: 'required' }] }) }))
  await expect(api.getEvidence('x')).rejects.toThrow('execution_context')
})

it('rejects a pinned evidence from a different scenario or kind', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ id: 'foreign', kind: 'evidence.simulation', scenario_ref: 'other', variant_ref: 'v' })))
  await expect(api.getSimulationEvidence('current', 'v', 'foreign')).rejects.toThrow('does not belong')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ id: 'measurement', kind: 'evidence.measurement', scenario_ref: 'current', variant_ref: 'v' })))
  await expect(api.getSimulationEvidence('current', 'v', 'measurement')).rejects.toThrow('does not belong')
})

it('loads a matching pinned simulation directly instead of latest', async () => {
  const fetch = vi.fn().mockResolvedValue(response({ id: 'saved', kind: 'evidence.simulation', scenario_ref: 'current', variant_ref: 'v' }))
  vi.stubGlobal('fetch', fetch)
  expect((await api.getSimulationEvidence('current', 'v', 'saved'))?.id).toBe('saved')
  expect(fetch.mock.calls[0][0]).toBe('/api/v1/evidence/saved')
})
