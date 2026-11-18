import { expect, it } from 'vitest'
import { evaluate, reportError, rootAdvisories } from './audit.mjs'

const adv = (id, title = 't') => ({ url: `https://github.com/advisories/${id}`, title, severity: 'high' })
const report = {
  vulnerabilities: {
    vite: { severity: 'high', via: ['picomatch'] },
    picomatch: { severity: 'high', via: [adv('GHSA-a')] },
    other: { severity: 'moderate', via: [adv('GHSA-b'), 'picomatch'] },
    minor: { severity: 'low', via: [adv('GHSA-c')] },
  },
}
const entry = (id, expires = '2099-01-01') => ({ id, reason: 'r', expires })

it('traces a vulnerability to its root advisories through the dependency chain', () => {
  expect(rootAdvisories(report.vulnerabilities, 'vite').map((a) => a.url.split('/').pop())).toEqual(['GHSA-a'])
  expect(rootAdvisories(report.vulnerabilities, 'other').map((a) => a.url.split('/').pop())).toEqual(['GHSA-b', 'GHSA-a'])
})

it('passes only when every root advisory at the level is allowlisted and current', () => {
  const r = evaluate(report, [entry('GHSA-a')], { today: '2026-11-19' })
  expect(r.failing.map((f) => f.name)).toEqual(['other'])           // GHSA-b is not reviewed; low GHSA-c is below the level
  expect(evaluate(report, [entry('GHSA-a'), entry('GHSA-b')], { today: '2026-11-19' }).failing).toEqual([])
})

it('fails an expired entry and reports entries no longer needed', () => {
  const r = evaluate(report, [entry('GHSA-a', '2026-11-01'), entry('GHSA-b'), entry('GHSA-gone')], { today: '2026-11-19' })
  expect(r.expired).toEqual(['GHSA-a'])
  expect(r.failing.map((f) => f.name).sort()).toEqual(['other', 'picomatch', 'vite'])
  expect(r.stale).toEqual(['GHSA-gone'])
})

it('treats a failed or malformed audit as an error, not as no findings', () => {
  expect(reportError({ error: { code: 'ENOTFOUND', summary: 'request to registry failed' } })).toContain('registry failed')
  expect(reportError(null)).toContain('no JSON')
  expect(reportError({ auditReportVersion: 2 })).toContain('no vulnerabilities section')
  expect(reportError({ vulnerabilities: {} })).toBeNull()
  expect(() => evaluate({ vulnerabilities: {} }, [], { level: 'severe' })).toThrow('unknown audit level')
})
