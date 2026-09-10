import { useState } from 'react'
import { useCatalogSearch } from '../../api/useCatalogSearch'
import { useQuery } from '@tanstack/react-query'
import { api, type CatalogItem, type CatalogKind, type CatalogParams } from '../../api/client'

const labelFor = (item: CatalogItem) => item.category.length
  ? `[${item.category.join(', ')}] ${item.name}`
  : item.board_type ? `${item.name} (${item.board_type})` : item.name

export function CatalogSelect({ kind, label, scope, value, onChange, emptyLabel, enabled = true }: {
  kind: CatalogKind; label: string; scope: CatalogParams; value: string | null
  onChange: (value: string | null) => void; emptyLabel: string; enabled?: boolean
}) {
  const { input, setInput, search } = useCatalogSearch()
  const [page, setPage] = useState({ search: '', offset: 0 })
  const offset = page.search === search ? page.offset : 0
  const params = { ...scope, q: search, offset }
  const { data, error, isFetching } = useQuery({
    queryKey: ['catalog', kind, params],
    queryFn: ({ signal }) => api.getCatalog(kind, params, signal),
    enabled,
  })
  const items = data?.items ?? []
  // A URL selection can be on any page. Resolve only that ID in the same scope.
  const needsSelected = enabled && Boolean(value) && !items.some(item => item.id === value)
  const selected = useQuery({
    queryKey: ['catalog-selection', kind, scope, value],
    queryFn: ({ signal }) => api.getCatalog(kind, { ...scope, id: value!, limit: 1 }, signal),
    enabled: needsSelected,
  })
  const selectedItem = selected.data?.items[0]
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 170, flex: 1 }}>
    <label style={{ fontSize: 11 }}>{label}
      <input aria-label={`Search ${label}`} placeholder="Search…" value={input} disabled={!enabled}
        onChange={event => setInput(event.target.value)} style={{ width: '100%', fontSize: 12 }} />
    </label>
    <select aria-label={label} value={value ?? ''} disabled={!enabled}
      onChange={event => onChange(event.target.value || null)} style={{ width: '100%', fontSize: 12 }}>
      <option value="">{emptyLabel}</option>
      {needsSelected && <option value={value!}>{selectedItem ? labelFor(selectedItem) : value}</option>}
      {items.map(item => <option key={item.id} value={item.id}>{labelFor(item)}</option>)}
    </select>
    <div style={{ display: 'flex', gap: 6, fontSize: 11, alignItems: 'center' }}>
      <button aria-label={`Previous ${label} page`} disabled={!enabled || !offset || isFetching}
        onClick={() => setPage({ search, offset: Math.max(0, offset - 100) })}>‹</button>
      <span role="status">{!enabled ? 'Select a scenario first' : isFetching ? 'Loading…' : `${data?.total ? offset + 1 : 0}–${offset + items.length} / ${data?.total ?? 0}`}</span>
      <button aria-label={`Next ${label} page`} disabled={!enabled || !data?.has_next || isFetching}
        onClick={() => setPage({ search, offset: offset + 100 })}>›</button>
    </div>
    {(error || selected.error) && <span role="alert">{String(error || selected.error)}</span>}
    {needsSelected && selected.isSuccess && !selectedItem && <span role="alert">Selected {label} is unavailable in this scope.</span>}
  </div>
}
