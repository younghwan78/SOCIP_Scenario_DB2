import { create } from 'zustand'

export type ViewLevel = 0 | 1 | 2
export type ViewMode = 'architecture' | 'topology' | 'resource'
export type ActiveTab = 'pipeline' | 'timeline' | 'evidence' | 'explorer' | 'query'

interface ScenarioState {
  // Hierarchical selection
  socId: string | null
  projectId: string | null
  scenarioId: string | null
  variantId: string | null
  
  // Pipeline View State
  viewLevel: ViewLevel
  viewMode: ViewMode
  expandTarget: string | null
  simOverlayMode: 'none' | 'latest' | 'specific'
  simEvidenceId: string | null

  // Active Main Navigation Tab
  activeTab: ActiveTab

  // Selected Timeline Slice for Inspector
  selectedTaskId: string | null

  // Actions
  setSocId: (id: string | null) => void
  setProjectId: (id: string | null) => void
  setScenarioId: (id: string | null) => void
  setVariantId: (id: string | null) => void
  setViewLevel: (level: ViewLevel) => void
  setViewMode: (mode: ViewMode) => void
  setExpandTarget: (target: string | null) => void
  setSimOverlay: (mode: 'none' | 'latest' | 'specific', evidenceId?: string | null) => void
  setActiveTab: (tab: ActiveTab) => void
  setSelectedTaskId: (taskId: string | null) => void
  resetHierarchy: () => void
}

export const useScenarioStore = create<ScenarioState>((set) => ({
  socId: null,
  projectId: null,
  scenarioId: null,
  variantId: null,

  viewLevel: 0,
  viewMode: 'architecture',
  expandTarget: null,
  simOverlayMode: 'none',
  simEvidenceId: null,

  activeTab: 'timeline',
  selectedTaskId: null,

  setSocId: (id) => set({ socId: id, projectId: null, scenarioId: null, variantId: null, selectedTaskId: null, simEvidenceId: null, simOverlayMode: 'none', expandTarget: null }),
  setProjectId: (id) => set({ projectId: id, scenarioId: null, variantId: null, selectedTaskId: null, simEvidenceId: null, simOverlayMode: 'none', expandTarget: null }),
  setScenarioId: (id) => set({ scenarioId: id, variantId: null, selectedTaskId: null, simEvidenceId: null, simOverlayMode: 'none', expandTarget: null }),
  setVariantId: (id) => set({ variantId: id, selectedTaskId: null, simEvidenceId: null, simOverlayMode: 'none', expandTarget: null }),
  
  setViewLevel: (level) => set({ viewLevel: level }),
  setViewMode: (mode) => set({ viewMode: mode }),
  setExpandTarget: (target) => set({ expandTarget: target }),
  setSimOverlay: (mode, evidenceId = null) => set({ simOverlayMode: mode, simEvidenceId: evidenceId }),
  setActiveTab: (tab) => set({ activeTab: tab }),
  setSelectedTaskId: (taskId) => set({ selectedTaskId: taskId }),
  
  resetHierarchy: () => set({
    socId: null,
    projectId: null,
    scenarioId: null,
    variantId: null,
    selectedTaskId: null,
    simEvidenceId: null,
    simOverlayMode: 'none',
    expandTarget: null,
  }),
}))
