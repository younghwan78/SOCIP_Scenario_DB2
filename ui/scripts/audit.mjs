// npm audit with a reviewed allowlist (CI: `npm run audit`).
//
// Fails when a vulnerability at or above --level (default moderate) has a root advisory that is not in
// audit-allowlist.json, or when an allowlist entry has expired. Each entry names the advisory (GHSA id), why it
// does not apply, and an expiry date, so an exception is re-reviewed instead of staying forever.
// Entries whose advisory no longer appears are reported so they can be removed.
import { execSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ORDER = ['info', 'low', 'moderate', 'high', 'critical']

export function rootAdvisories(vulns, name, seen = new Set()) {
  if (seen.has(name)) return []
  seen.add(name)
  const v = vulns[name]
  if (!v) return []
  return v.via.flatMap((via) => (typeof via === 'string' ? rootAdvisories(vulns, via, seen) : [via]))
}

const ghsa = (advisory) => String(advisory.url ?? '').split('/').pop()

/** A report npm audit could not produce (registry error, unexpected format) must fail, not pass as "no findings". */
export function reportError(report) {
  if (!report || typeof report !== 'object') return 'npm audit produced no JSON report'
  if (report.error) return `npm audit failed: ${report.error.summary ?? report.error.code ?? JSON.stringify(report.error)}`
  if (typeof report.vulnerabilities !== 'object' || report.vulnerabilities === null) return 'npm audit report has no vulnerabilities section'
  return null
}

export function evaluate(report, allowlist, { level = 'moderate', today = new Date().toISOString().slice(0, 10) } = {}) {
  const min = ORDER.indexOf(level)
  if (min < 0) throw new Error(`unknown audit level: ${level}`)
  const allowed = new Map(allowlist.map((e) => [e.id, e]))
  const expired = allowlist.filter((e) => !e.expires || e.expires < today)
  const vulns = report.vulnerabilities ?? {}
  const failing = []
  const used = new Set()
  for (const [name, v] of Object.entries(vulns)) {
    if (ORDER.indexOf(v.severity) < min) continue
    const roots = rootAdvisories(vulns, name)
    const open = roots.filter((a) => !allowed.has(ghsa(a)) || expired.includes(allowed.get(ghsa(a))))
    roots.forEach((a) => allowed.has(ghsa(a)) && used.add(ghsa(a)))
    if (open.length || !roots.length) failing.push({ name, severity: v.severity, advisories: open.map((a) => `${ghsa(a)} ${a.title}`) })
  }
  const stale = allowlist.filter((e) => !used.has(e.id)).map((e) => e.id)
  return { failing, expired: expired.map((e) => e.id), stale }
}

function main() {
  const here = dirname(fileURLToPath(import.meta.url))
  const level = process.argv.find((a) => a.startsWith('--level='))?.split('=')[1] ?? 'moderate'
  const allowlist = JSON.parse(readFileSync(join(here, '..', 'audit-allowlist.json'), 'utf8'))
  let out
  try {
    out = execSync('npm audit --json', { cwd: join(here, '..'), encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], maxBuffer: 64 * 1024 * 1024 })
  } catch (e) {
    out = e.stdout // npm audit exits 1 when it finds anything
  }
  let report
  try {
    report = JSON.parse(out ?? '')
  } catch {
    report = null
  }
  const error = reportError(report)
  if (error) {
    console.error(error)
    process.exit(1)
  }
  const r = evaluate(report, allowlist, { level })
  for (const id of r.stale) console.log(`allowlist entry no longer needed: ${id}`)
  for (const id of r.expired) console.error(`allowlist entry expired: ${id} (re-review it or remove it)`)
  for (const f of r.failing) console.error(`${f.severity} ${f.name}: ${f.advisories.join('; ') || 'no advisory detail'}`)
  if (r.failing.length || r.expired.length) process.exit(1)
  console.log(`npm audit: no unreviewed advisory at ${level}+ (${allowlist.length} allowlisted)`)
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) main()
