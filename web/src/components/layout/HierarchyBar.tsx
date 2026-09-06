import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, Cpu, CircuitBoard, Film, GitFork } from 'lucide-react'
import { api } from '../../api/client'
import { useScenarioStore } from '../../store/scenarioStore'

export const HierarchyBar: React.FC = () => {
  const {
    socId, setSocId,
    projectId, setProjectId,
    scenarioId, setScenarioId,
    variantId, setVariantId,
  } = useScenarioStore()

  // 1. Fetch SoC Platforms
  const { data: socList = [], error: socError } = useQuery({
    queryKey: ['socPlatforms'],
    queryFn: api.getSocPlatforms,
  })

  // 2. Fetch Projects (filtered by SoC)
  const { data: projectList = [], error: projectError } = useQuery({
    queryKey: ['projects', socId],
    queryFn: () => api.getProjects(socId || undefined),
    enabled: true,
  })

  // 3. Fetch Scenarios (filtered by SoC/Project)
  const { data: scenarioList = [], error: scenarioError } = useQuery({
    queryKey: ['scenarios', socId, projectId],
    queryFn: () => api.getScenarios({ soc_ref: socId || undefined, project_ref: projectId || undefined }),
    enabled: true,
  })

  // 4. Fetch Variants (for selected scenario)
  const { data: variantData, error: variantError } = useQuery({
    queryKey: ['variants', scenarioId],
    queryFn: () => api.getVariants(scenarioId!),
    enabled: Boolean(scenarioId),
  })
  const variantList = variantData?.items || []

  return (
    <div
      style={{
        height: 'var(--hierarchy-bar-height)',
        background: 'var(--bg-surface-raised)',
        borderBottom: '1px solid var(--border-subtle)',
        display: 'flex',
        alignItems: 'center',
        padding: '0 16px',
        gap: '8px',
        fontSize: 'var(--text-xs)',
        userSelect: 'none',
      }}
    >
      {(socError || projectError || scenarioError || variantError) && <span role="alert">{String(socError || projectError || scenarioError || variantError)}</span>}
      {/* 1. SoC Platform Selector */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
        <Cpu size={14} color="var(--text-muted)" />
        <select
          aria-label="SoC platform"
          value={socId || ''}
          onChange={(e) => setSocId(e.target.value || null)}
          style={{ padding: '3px 8px', fontSize: '12px', fontWeight: 600 }}
        >
          <option value="">-- All SoCs --</option>
          {socList.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name || s.id}
            </option>
          ))}
        </select>
      </div>

      <ChevronRight size={13} color="var(--text-muted)" />

      {/* 2. Project / Board Selector */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
        <CircuitBoard size={14} color="var(--text-muted)" />
        <select
          aria-label="Project or board"
          value={projectId || ''}
          onChange={(e) => setProjectId(e.target.value || null)}
          style={{ padding: '3px 8px', fontSize: '12px' }}
        >
          <option value="">-- All Projects --</option>
          {projectList.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name || p.id} ({p.board_type})
            </option>
          ))}
        </select>
      </div>

      <ChevronRight size={13} color="var(--text-muted)" />

      {/* 3. Scenario Selector */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
        <Film size={14} color="var(--text-muted)" />
        <select
          aria-label="Scenario"
          value={scenarioId || ''}
          onChange={(e) => setScenarioId(e.target.value || null)}
          style={{ padding: '3px 8px', fontSize: '12px', fontWeight: 600, minWidth: '180px' }}
        >
          <option value="">-- Select Scenario --</option>
          {scenarioList.map((sc) => (
            <option key={sc.id} value={sc.id}>
              [{sc.category}] {sc.name || sc.id}
            </option>
          ))}
        </select>
      </div>

      <ChevronRight size={13} color="var(--text-muted)" />

      {/* 4. Variant Selector */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
        <GitFork size={14} color="var(--text-muted)" />
        <select
          aria-label="Variant"
          value={variantId || ''}
          onChange={(e) => setVariantId(e.target.value || null)}
          style={{ padding: '3px 8px', fontSize: '12px', minWidth: '120px' }}
          disabled={!scenarioId || variantList.length === 0}
        >
          <option value="">Base Scenario (No Variant)</option>
          {variantList.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name || v.id}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}
