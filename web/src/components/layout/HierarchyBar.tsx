import { useScenarioStore } from '../../store/scenarioStore'
import { CatalogSelect } from './CatalogSelect'

export const HierarchyBar = () => {
  const { socId, setSocId, projectId, setProjectId, scenarioId, setScenarioId, variantId, setVariantId } = useScenarioStore()
  const socScope = { soc_ref: socId || undefined }
  const scenarioScope = { ...socScope, project_ref: projectId || undefined }
  return <div style={{ minHeight: 'var(--hierarchy-bar-height)', background: 'var(--bg-surface-raised)',
    borderBottom: '1px solid var(--border-subtle)', display: 'flex', flexWrap: 'wrap', padding: '8px 16px', gap: 16 }}>
    <CatalogSelect kind="soc-platforms" label="SoC platform" scope={{}} value={socId} onChange={setSocId} emptyLabel="All SoCs" />
    <CatalogSelect key={`projects:${socId}`} kind="projects" label="Project or board" scope={socScope}
      value={projectId} onChange={setProjectId} emptyLabel="All Projects" />
    <CatalogSelect key={`scenarios:${socId}:${projectId}`} kind="scenarios" label="Scenario" scope={scenarioScope}
      value={scenarioId} onChange={setScenarioId} emptyLabel="Select Scenario" />
    <CatalogSelect key={`variants:${socId}:${projectId}:${scenarioId}`} kind="variants" label="Variant"
      scope={{ ...scenarioScope, scenario_id: scenarioId || undefined }} value={variantId} onChange={setVariantId}
      emptyLabel="Base Scenario (No Variant)" enabled={Boolean(scenarioId)} />
  </div>
}
