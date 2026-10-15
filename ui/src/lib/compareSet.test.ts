// @vitest-environment jsdom
import { afterEach, expect, it } from 'vitest'
import { loadCompareSet, saveCompareSet } from './projects'

afterEach(() => window.localStorage.clear())
it('keeps the compare set until it is cleared', () => {
  expect(loadCompareSet()).toBe('')
  saveCompareSet('scn~a,scn~b')
  expect(loadCompareSet()).toBe('scn~a,scn~b')
  saveCompareSet('garbage-without-separator')      // not a valid set -> forget it
  expect(loadCompareSet()).toBe('')
  saveCompareSet('scn~a,scn~b'); saveCompareSet(undefined)
  expect(loadCompareSet()).toBe('')
})
