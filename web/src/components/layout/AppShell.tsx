import React, { lazy, Suspense } from 'react'

import { Header } from './Header'

import { HierarchyBar } from './HierarchyBar'

import { useScenarioStore } from '../../store/scenarioStore'

const TimelineViewer = lazy(() => import('../timeline/TimelineViewer').then(module => ({ default: module.TimelineViewer })))

const PipelineViewer = lazy(() => import('../pipeline/PipelineViewer').then(module => ({ default: module.PipelineViewer })))

const EvidenceDashboard = lazy(() => import('../evidence/EvidenceDashboard').then(module => ({ default: module.EvidenceDashboard })))

const DbExplorer = lazy(() => import('../explorer/DbExplorer').then(module => ({ default: module.DbExplorer })))

const ArchitectureQuery = lazy(() => import('../query/ArchitectureQuery').then(module => ({ default: module.ArchitectureQuery })))



export const AppShell: React.FC = () => {

  const activeTab = useScenarioStore(state => state.activeTab)
  const contextKey = useScenarioStore(state => `${state.scenarioId}/${state.variantId}`)



  return (

    <div style={{ display: 'flex', flexDirection: 'column', width: '100vw', height: '100vh', overflow: 'hidden' }}>

      {/* Top Main Navigation Header */}

      <Header />



      {/* Hierarchical Context Selector Bar */}

      <HierarchyBar />



      {/* Dynamic View Area */}

      <main style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>

        <Suspense fallback={<p role="status">Loading view…</p>}>

        {activeTab === 'timeline' && <TimelineViewer />}

        {activeTab === 'pipeline' && <PipelineViewer />}

        {activeTab === 'evidence' && <EvidenceDashboard key={contextKey} />}

        {activeTab === 'explorer' && <DbExplorer />}

        {activeTab === 'query' && <ArchitectureQuery />}

      </Suspense>

      </main>

    </div>

  )

}

