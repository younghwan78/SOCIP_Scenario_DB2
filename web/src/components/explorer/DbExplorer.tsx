import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search, Play, ArrowUpDown } from 'lucide-react'
import { api } from '../../api/client'
import { useScenarioStore } from '../../store/scenarioStore'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'

export const DbExplorer: React.FC = () => {
  const { socId, projectId, setScenarioId, setActiveTab } = useScenarioStore()
  const [searchTerm, setSearchTerm] = useState('')
  const [sortField, setSortField] = useState<'id' | 'name' | 'category'>('id')
  const [sortAsc, setSortAsc] = useState(true)

  const { data: scenarios = [], isLoading, error } = useQuery({
    queryKey: ['explorerScenarios', socId, projectId],
    queryFn: () => api.getScenarios({ soc_ref: socId || undefined, project_ref: projectId || undefined }),
  })

  const filteredScenarios = scenarios
    .filter((s) => {
      const q = searchTerm.toLowerCase()
      return (
        s.id.toLowerCase().includes(q) ||
        s.name.toLowerCase().includes(q) ||
        s.category.toLowerCase().includes(q)
      )
    })
    .sort((a, b) => {
      const valA = a[sortField] || ''
      const valB = b[sortField] || ''
      return sortAsc ? valA.localeCompare(valB) : valB.localeCompare(valA)
    })

  const handleSort = (field: 'id' | 'name' | 'category') => {
    if (sortField === field) {
      setSortAsc(!sortAsc)
    } else {
      setSortField(field)
      setSortAsc(true)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%', padding: '16px', gap: '12px' }}>
      {error && <p role="alert">{error.message}</p>}
      {/* Top Search Bar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, maxWidth: '400px', background: 'var(--bg-surface)', padding: '6px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)' }}>
          <Search size={16} color="var(--text-muted)" />
          <input
            type="text"
            aria-label="Search scenarios"
            placeholder="Search scenarios by ID, name, category..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{ border: 'none', background: 'transparent', width: '100%', padding: 0 }}
          />
        </div>

        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
          Total Scenarios: <b>{filteredScenarios.length}</b> / {scenarios.length}
        </div>
      </div>

      {/* High-Performance Table Grid */}
      <div
        style={{
          flex: 1,
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-md)',
          overflow: 'auto',
        }}
      >
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px', textAlign: 'left' }}>
          <thead>
            <tr style={{ background: 'var(--bg-surface-raised)', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-muted)' }}>
              <th onClick={() => handleSort('id')} style={{ padding: '10px 14px', fontWeight: 700, cursor: 'pointer' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>Scenario ID <ArrowUpDown size={12} /></span>
              </th>
              <th onClick={() => handleSort('name')} style={{ padding: '10px 14px', fontWeight: 700, cursor: 'pointer' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>Scenario Name <ArrowUpDown size={12} /></span>
              </th>
              <th onClick={() => handleSort('category')} style={{ padding: '10px 14px', fontWeight: 700, cursor: 'pointer' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>Category <ArrowUpDown size={12} /></span>
              </th>
              <th style={{ padding: '10px 14px', fontWeight: 700 }}>SoC Platform</th>
              <th style={{ padding: '10px 14px', fontWeight: 700, width: '160px' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={5} style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>
                  Loading scenario database...
                </td>
              </tr>
            ) : filteredScenarios.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>
                  No scenarios found matching filters.
                </td>
              </tr>
            ) : (
              filteredScenarios.map((sc) => (
                <tr
                  key={sc.id}
                  style={{
                    borderBottom: '1px solid var(--border-subtle)',
                    transition: 'background var(--transition-fast)',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-surface-hover)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  <td style={{ padding: '10px 14px', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{sc.id}</td>
                  <td style={{ padding: '10px 14px', fontWeight: 700 }}>{sc.name}</td>
                  <td style={{ padding: '10px 14px' }}>
                    <Badge variant="teal">{sc.category}</Badge>
                  </td>
                  <td style={{ padding: '10px 14px', color: 'var(--text-secondary)' }}>{sc.soc_ref}</td>
                  <td style={{ padding: '10px 14px' }}>
                    <Button
                      size="sm"
                      variant="primary"
                      icon={<Play size={12} />}
                      onClick={() => {
                        setScenarioId(sc.id)
                        setActiveTab('timeline')
                      }}
                    >
                      Open in Timeline
                    </Button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
