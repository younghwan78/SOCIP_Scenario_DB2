import { useState } from 'react'
import { request, type Page } from '../../api/client'
import { Card } from '../common/Card'
import { Button } from '../common/Button'
interface Row { scenario_id: string; scenario_name: string; variant_id: string; matched_issue_count: number }
export function ArchitectureQuery() {
  const [queryText, setQueryText] = useState('{"scope": {}, "where": [], "limit": 50, "offset": 0}')
  const [result, setResult] = useState<Page<Row> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  async function execute() {
    setError(null); setResult(null); setBusy(true)
    try {
      const payload = JSON.parse(queryText)
      if (!payload || Array.isArray(payload) || typeof payload !== 'object') throw new Error('Enter a JSON query object.')
      setResult(await request<Page<Row>>('/query/variants', { method: 'POST', body: JSON.stringify(payload) }))
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  return <div style={{ padding: 16, width: '100%', overflow: 'auto' }}>
    <Card title="Architecture Query" extra={<Button disabled={busy} onClick={execute}>{busy ? 'Running...' : 'Execute Query'}</Button>}>
      <p>Filter variants with scope and where conditions. Example: field axis.fps, operator gte, value 60. Use limit and offset to page results.</p>
      <label>JSON query<textarea rows={8} value={queryText} onChange={event => setQueryText(event.target.value)} spellCheck={false} style={{ width: '100%', fontFamily: 'var(--font-mono)' }} /></label>
      {error && <p role="alert">{error}</p>}
    </Card>
    {result && <Card title={`Results (${result.items.length} of ${result.total})`}>
      {result.has_next && <p>More results are available. Increase offset to load the next page.</p>}
      <table style={{ width: '100%' }}><thead><tr><th>Scenario</th><th>Variant</th><th>Matched issues</th></tr></thead>
        <tbody>{result.items.map(row => <tr key={`${row.scenario_id}/${row.variant_id}`}><td>{row.scenario_name || row.scenario_id}</td><td>{row.variant_id}</td><td>{row.matched_issue_count}</td></tr>)}</tbody>
      </table>{!result.items.length && <p>No variants match this query.</p>}
    </Card>}
  </div>
}
