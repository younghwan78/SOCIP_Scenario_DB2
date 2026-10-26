// @vitest-environment jsdom
import { afterEach, expect, it } from 'vitest'
import { setApiCredential } from './auth'
import { experimentHref, listExperimentContexts, readExperimentContext, updateExperimentContext } from './experimentContext'

afterEach(() => { sessionStorage.clear(); setApiCredential(null) })
const scope = { project_ref: 'project', scenario_id: 'record', variant_id: 'rear' }
it('restores versioned drafts by project, scenario, variant and credential without storing the secret', () => {
  updateExperimentContext(scope, { changes: [{ target: 'fps', value: 30 }], basis_ref: 'basis-1' })
  expect(readExperimentContext({ ...scope, variant_id: 'front' })).toBeUndefined()
  setApiCredential({ keyId: 'analyst', secret: 'never-store-this' })
  expect(readExperimentContext(scope)).toBeUndefined()
  updateExperimentContext(scope, { changes: [{ target: 'fps', value: 60 }] })
  expect(JSON.stringify(sessionStorage)).not.toContain('never-store-this')
  setApiCredential(null)
  expect(readExperimentContext(scope)).toMatchObject({ changes: [{ target: 'fps', value: 30 }], basis_ref: 'basis-1' })
  expect(experimentHref('whatif', scope, 'saved ID')).toContain('experiment=saved+ID')
})
it('bounds retained scopes and rejects malformed local storage candidates', () => {
  for (let n = 0; n < 15; n++) updateExperimentContext({ ...scope, variant_id: String(n) }, { changes: [{ target: 'fps', value: 30 }] })
  expect(listExperimentContexts()).toHaveLength(10)
  expect(readExperimentContext({ ...scope, variant_id: '0' })).toBeUndefined()
  const key = sessionStorage.key(0)!
  sessionStorage.setItem(key, JSON.stringify({ version: 1, items: [{ scope, changes: [], candidates: [{ id: 'bad', metrics: {} }], updated_at: 'now' }] }))
  expect(readExperimentContext(scope)?.candidates).toEqual([])
  sessionStorage.setItem(key, '{broken')
  expect(listExperimentContexts()).toEqual([])
})
it('does not alias an anonymous session with an account named local', () => {
  updateExperimentContext(scope, { changes: [{ target: 'fps', value: 30 }] })
  setApiCredential({ keyId: 'local', secret: 'secret' })
  expect(readExperimentContext(scope)).toBeUndefined()
})
