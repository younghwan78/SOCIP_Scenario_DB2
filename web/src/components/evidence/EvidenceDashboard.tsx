import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Play, Zap, Cpu, BarChart2, Activity } from 'lucide-react'
import { api, type SimulationContext, type Credentials } from '../../api/client'
import { useScenarioStore } from '../../store/scenarioStore'
import { Button } from '../common/Button'
import { Card } from '../common/Card'
import { Badge } from '../common/Badge'

export const EvidenceDashboard: React.FC = () => {
  const queryClient = useQueryClient()
  const { scenarioId, variantId, simEvidenceId, setSimOverlay } = useScenarioStore()

  const [activeSubTab, setActiveSubTab] = useState<'overview' | 'power' | 'comparison' | 'sw_timing'>('overview')
  const [isRunningSim, setIsRunningSim] = useState(false)

  const [context, setContext] = useState<SimulationContext>({ silicon_rev: '', sw_baseline_ref: '', thermal: '', method: 'calculation' })
  const [credentials, setCredentials] = useState<Credentials>({ keyId: '', apiKey: '' })
  const [warnings, setWarnings] = useState<string[]>([])
  const { data: latestEvidence, error: loadError, isLoading } = useQuery({
    queryKey: ['simulationEvidence', scenarioId, variantId, simEvidenceId],
    queryFn: () => api.getSimulationEvidence(scenarioId!, variantId, simEvidenceId),
    enabled: Boolean(scenarioId && variantId),
  })
  const kpi = latestEvidence?.kpi || {}
  const simMutation = useMutation({
    mutationFn: async (input: { scenarioId: string; variantId: string; context: SimulationContext }) => {
      const ready = await api.getReadiness(input.scenarioId, input.variantId)
      if (ready.status === 'blocked') throw new Error(ready.errors.map(issue => issue.message).join('; '))
      return api.runSimulation(input.scenarioId, input.variantId, input.context, credentials)
    },
    onSuccess: (response, input) => {
      setWarnings(response.warnings)
      const current = useScenarioStore.getState()
      if (current.scenarioId === input.scenarioId && current.variantId === input.variantId) current.setSimOverlay('none')
      if (response.evidence) queryClient.setQueryData(['simulationEvidence', input.scenarioId, input.variantId, null],
        { ...response.evidence, isPreview: !response.persisted })
    },
  })
  const handleRunSimulation = async () => {
    if (!scenarioId || !variantId) return
    setIsRunningSim(true)
    setWarnings([])
    try { await simMutation.mutateAsync({ scenarioId, variantId, context }) }
    catch { /* displayed through simMutation.error */ }
    finally { setIsRunningSim(false) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%', overflowY: 'auto', padding: '16px', gap: '16px' }}>
      {/* Top Banner with Run Simulation Form */}
      <Card
        title="Scenario Simulation & Evidence Manager"
        extra={
          <Button
            variant="primary"
            icon={<Play size={14} />}
            disabled={!scenarioId || !variantId || isRunningSim || !context.silicon_rev.trim() || !context.sw_baseline_ref.trim() || !context.thermal.trim() || Boolean(credentials.keyId) !== Boolean(credentials.apiKey)}
            onClick={handleRunSimulation}
          >
            {isRunningSim ? 'Running Simulation...' : 'Run Simulation Preview'}
          </Button>
        }
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '13px', color: 'var(--text-secondary)' }}>
          <div>
            Active Scenario: <b style={{ color: 'var(--text-primary)' }}>{scenarioId || 'None'}</b> / Variant: <b style={{ color: 'var(--text-primary)' }}>{variantId || 'Base'}</b>
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            {latestEvidence ? (
              <Badge variant="success">{latestEvidence.isPreview ? 'Preview (not saved)' : 'Saved Simulation'}: {latestEvidence.id}</Badge>
            ) : (
              <Badge variant="default">No Evidence Loaded</Badge>
            )}
          </div>
        </div>
      </Card>

      <Card title="Execution conditions">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
          {(['silicon_rev', 'sw_baseline_ref', 'thermal'] as const).map(key => <label key={key}>{ { silicon_rev: 'Silicon revision', sw_baseline_ref: 'SW baseline ID', thermal: 'Thermal condition' }[key] }<input required value={context[key]} onChange={event => setContext(previous => ({ ...previous, [key]: event.target.value }))} /></label>)}
          <label>API key ID<input autoComplete="off" value={credentials.keyId} onChange={event => setCredentials(previous => ({ ...previous, keyId: event.target.value }))} /></label>
          <label>API key<input type="password" autoComplete="off" value={credentials.apiKey} onChange={event => setCredentials(previous => ({ ...previous, apiKey: event.target.value }))} /></label>
        </div>
        <p>Preview results are not saved. Credentials remain in this form only. Select a variant before running.</p>
        {isLoading && <p role="status">Loading saved simulation...</p>}
        {(loadError || simMutation.error) && <p role="alert">{(simMutation.error || loadError)?.message}</p>}
        {warnings.map((warning, index) => <p role="status" key={index}>{warning}</p>)}
      </Card>
      <div style={{ display: 'flex', gap: 8 }}>
        <Button disabled={!latestEvidence || latestEvidence.isPreview} onClick={() => latestEvidence && setSimOverlay('specific', latestEvidence.id)}>Pin saved result in URL</Button>
        {simEvidenceId && <Button onClick={() => setSimOverlay('none')}>Return to latest simulation</Button>}
      </div>
      {/* KPI Metrics Summary Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px' }}>
        <Card>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px', color: 'var(--brand-primary)' }}>
            <Zap size={16} />
            <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)' }}>TOTAL POWER</span>
          </div>
          <div style={{ fontSize: '20px', fontWeight: 800, fontFamily: 'var(--font-mono)' }}>
            {kpi.total_power_mw != null ? `${Number(kpi.total_power_mw).toFixed(1)} mW` : '-'}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
            Current: {kpi.total_power_ma != null ? `${Number(kpi.total_power_ma).toFixed(1)} mA` : '-'}
          </div>
        </Card>

        <Card>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px', color: 'var(--brand-teal)' }}>
            <Cpu size={16} />
            <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)' }}>CORE POWER</span>
          </div>
          <div style={{ fontSize: '20px', fontWeight: 800, fontFamily: 'var(--font-mono)' }}>
            {kpi.core_power_mw != null ? `${Number(kpi.core_power_mw).toFixed(1)} mW` : '-'}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
            Compute IP Core consumption
          </div>
        </Card>

        <Card>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px', color: 'var(--brand-purple)' }}>
            <BarChart2 size={16} />
            <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)' }}>TOTAL DMA BANDWIDTH</span>
          </div>
          <div style={{ fontSize: '20px', fontWeight: 800, fontFamily: 'var(--font-mono)' }}>
            {kpi.total_bw_mbs != null ? `${(Number(kpi.total_bw_mbs) / 1000).toFixed(2)} GB/s` : '-'}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
            BW Power: {kpi.bw_power_mw != null ? `${Number(kpi.bw_power_mw).toFixed(1)} mW` : '-'}
          </div>
        </Card>

        <Card>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px', color: 'var(--status-success)' }}>
            <Activity size={16} />
            <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)' }}>FRAME LATENCY</span>
          </div>
          <div style={{ fontSize: '20px', fontWeight: 800, fontFamily: 'var(--font-mono)' }}>
            {kpi.timeline_end_ms != null ? `${Number(kpi.timeline_end_ms).toFixed(2)} ms` : '-'}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
            HW Time Max: {kpi.hw_time_max_ms != null ? `${Number(kpi.hw_time_max_ms).toFixed(2)} ms` : '-'}
          </div>
        </Card>
      </div>

      {/* Breakdown Sub Tabs */}
      <div style={{ display: 'flex', gap: '6px', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '8px' }}>
        {[
          { key: 'overview', label: 'Overview' },
          { key: 'power', label: 'VDD Rail Power' },
          { key: 'sw_timing', label: 'SW Task Timing' },
          { key: 'comparison', label: 'Prediction vs Measurement' },
        ].map((tab) => (
          <button
            key={tab.key}
            disabled={tab.key === 'comparison'}
            title={tab.key === 'comparison' ? 'Comparison is available in the Streamlit Evidence Dashboard' : undefined}
            onClick={() => setActiveSubTab(tab.key as typeof activeSubTab)}
            style={{
              padding: '6px 14px',
              borderRadius: 'var(--radius-sm)',
              fontSize: '13px',
              fontWeight: activeSubTab === tab.key ? 700 : 500,
              color: activeSubTab === tab.key ? 'var(--text-primary)' : 'var(--text-secondary)',
              background: activeSubTab === tab.key ? 'var(--bg-surface-raised)' : 'transparent',
              border: activeSubTab === tab.key ? '1px solid var(--border-default)' : '1px solid transparent',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeSubTab === 'power' && <Card title="VDD rail power">
        <table style={{ width: '100%' }}><thead><tr><th scope="col">Rail</th><th scope="col">Power values</th></tr></thead>
          <tbody>{Object.entries(latestEvidence?.vdd_power || {}).map(([rail, values]) => <tr key={rail}><th scope="row">{rail}</th><td>{JSON.stringify(values)}</td></tr>)}</tbody>
        </table>
        {!Object.keys(latestEvidence?.vdd_power || {}).length && <p>No rail power recorded.</p>}
      </Card>}
      {/* Tab 1: SW Task Timing */}
      {activeSubTab === 'sw_timing' && (
        <Card title="Perfetto-extracted SW Task Timing Digest">
          {latestEvidence?.sw_task_timing && latestEvidence.sw_task_timing.length > 0 ? (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px', textAlign: 'left' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-muted)' }}>
                  <th style={{ padding: '8px' }}>Task Name</th>
                  <th style={{ padding: '8px' }}>Cluster</th>
                  <th style={{ padding: '8px' }}>Mean (ms)</th>
                  <th style={{ padding: '8px' }}>p50 (ms)</th>
                  <th style={{ padding: '8px' }}>p95 (ms)</th>
                  <th style={{ padding: '8px' }}>Max (ms)</th>
                  <th style={{ padding: '8px' }}>Calls/Frame</th>
                </tr>
              </thead>
              <tbody>
                {latestEvidence.sw_task_timing.map((row, idx) => (
                  <tr key={idx} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <td style={{ padding: '8px', fontWeight: 600 }}>{row.task}</td>
                    <td style={{ padding: '8px' }}>
                      <Badge variant="purple">{row.cluster || 'Unknown'}</Badge>
                    </td>
                    <td style={{ padding: '8px', fontFamily: 'var(--font-mono)' }}>{row.mean_ms?.toFixed(2)}</td>
                    <td style={{ padding: '8px', fontFamily: 'var(--font-mono)' }}>{row.p50_ms?.toFixed(2)}</td>
                    <td style={{ padding: '8px', fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--status-warning)' }}>
                      {row.p95_ms?.toFixed(2)}
                    </td>
                    <td style={{ padding: '8px', fontFamily: 'var(--font-mono)' }}>{row.max_ms?.toFixed(2)}</td>
                    <td style={{ padding: '8px', fontFamily: 'var(--font-mono)' }}>{row.count_per_frame?.toFixed(2) ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div style={{ color: 'var(--text-muted)', fontSize: '13px', padding: '16px' }}>
              No SW task timing statistics recorded for this evidence.
            </div>
          )}
        </Card>
      )}

      {/* Tab 2: Overview / Default */}
      {activeSubTab === 'overview' && (
        <Card title="Raw Evidence & Metadata">
          <pre
            style={{
              padding: '12px',
              background: 'var(--bg-app)',
              borderRadius: 'var(--radius-sm)',
              fontSize: '12px',
              fontFamily: 'var(--font-mono)',
              overflowX: 'auto',
              maxHeight: '320px',
            }}
          >
            {JSON.stringify(latestEvidence, null, 2)}
          </pre>
        </Card>
      )}
    </div>
  )
}
