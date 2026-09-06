import React, { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ZoomIn, ZoomOut, Maximize2, Keyboard, HelpCircle } from 'lucide-react'
import { api } from '../../api/client'
import { TimelineEngine } from '../../engine/timeline/TimelineEngine'
import type { HoverHitInfo } from '../../engine/timeline/timelineTypes'
import { useScenarioStore } from '../../store/scenarioStore'
import { Button } from '../common/Button'
import { TimelineInspector } from './TimelineInspector'
import { TimelineStatsCard } from './TimelineStatsCard'

export const TimelineViewer: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const engineRef = useRef<TimelineEngine | null>(null)

  const { scenarioId, variantId, selectedTaskId, setSelectedTaskId, simEvidenceId, setSimOverlay } = useScenarioStore()
  const [hoverHit, setHoverHit] = useState<HoverHitInfo | null>(null)

  const { data: evidenceData, isLoading, error } = useQuery({
    queryKey: ['simulationEvidence', scenarioId, variantId, simEvidenceId],
    queryFn: () => api.getSimulationEvidence(scenarioId!, variantId, simEvidenceId),
    enabled: Boolean(scenarioId && variantId),
  })

  // Initialize Timeline Engine
  useEffect(() => {
    if (!canvasRef.current) return

    const engine = new TimelineEngine()
    engine.attach(canvasRef.current)
    engine.onSelectSlice = (taskId) => setSelectedTaskId(taskId)
    engine.onHoverSlice = (hit) => setHoverHit(hit)
    engineRef.current = engine

    return () => {
      engine.detach()
      engineRef.current = null
    }
  }, [setSelectedTaskId])

  // Feed Data into Engine when loaded
  useEffect(() => {
    if (!engineRef.current) return
    setHoverHit(null)
    const events = evidenceData?.timeline_events || []
    const swTimings = evidenceData?.sw_task_timing || []
    engineRef.current.setData(events, swTimings)
  }, [evidenceData])

  // Sync selected task
  useEffect(() => {
    if (engineRef.current) {
      engineRef.current.setSelectedTaskId(selectedTaskId)
    }
  }, [selectedTaskId])

  const selectedEvent = evidenceData?.timeline_events?.find((e) => e.task_id === selectedTaskId) || null
  const selectedSwTiming = evidenceData?.sw_task_timing?.find((t) => t.task === selectedEvent?.task_id || t.task === selectedEvent?.hw_name)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%', overflow: 'hidden' }}>
      {error && <p role="alert">{error.message}</p>}
      {simEvidenceId && <Button onClick={() => setSimOverlay('none')}>Return to latest simulation</Button>}
      {!isLoading && !error && !evidenceData && <p role="status">{!variantId ? 'Select a variant to view simulation results. Base scenarios can be opened in Pipeline.' : 'No simulation result. Run a preview in Evidence.'}</p>}
      {evidenceData && <p style={{ padding: '4px 16px' }}>Evidence: {evidenceData.id} · {evidenceData.isPreview ? 'Preview (not saved)' : 'Saved simulation'}</p>}
      <label style={{ padding: '4px 16px' }}>Inspect task <select value={selectedTaskId || ''} onChange={event => setSelectedTaskId(event.target.value || null)}>
        <option value="">Select a task…</option>
        {(evidenceData?.timeline_events || []).map(event => <option key={event.task_id} value={event.task_id}>{event.hw_name || event.task_id} ({event.task_id})</option>)}
      </select></label>
      {/* Top Statistical KPI Cards */}
      {evidenceData?.timeline_events && <TimelineStatsCard events={evidenceData.timeline_events} />}

      {/* Timeline Controls Toolbar */}
      <div
        style={{
          height: '40px',
          background: 'var(--bg-surface-raised)',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 16px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontWeight: 700, fontSize: '12px', color: 'var(--text-secondary)' }}>VIEWPORT</span>
          <Button size="sm" icon={<ZoomIn size={14} />} onClick={() => engineRef.current?.zoomBy(0.75)}>
            Zoom In (W)
          </Button>
          <Button size="sm" icon={<ZoomOut size={14} />} onClick={() => engineRef.current?.zoomBy(1.33)}>
            Zoom Out (S)
          </Button>
          <Button size="sm" icon={<Maximize2 size={14} />} onClick={() => engineRef.current?.fitAll()}>
            Fit All (F)
          </Button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', fontSize: '11px', color: 'var(--text-muted)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Keyboard size={13} />
            <span><b>W/S:</b> Zoom · <b>A/D:</b> Pan · <b>Drag:</b> Scroll</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <HelpCircle size={13} />
            <span>Click slice to inspect</span>
          </div>
        </div>
      </div>

      {/* Main Canvas + Inspector Split View */}
      <div style={{ display: 'flex', flex: 1, position: 'relative', overflow: 'hidden' }}>
        <div style={{ flex: 1, position: 'relative', width: '100%', height: '100%' }}>
          {isLoading && (
            <div
              style={{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'rgba(11, 15, 25, 0.7)',
                zIndex: 2,
                color: 'var(--text-secondary)',
                fontSize: '13px',
              }}
            >
              Loading scenario timeline events...
            </div>
          )}
          <canvas
            ref={canvasRef}
            aria-label="Simulation timeline; use the task selector to inspect events"
            style={{
              width: '100%',
              height: '100%',
              display: 'block',
            }}
          />

          {/* Hover Tooltip Popup */}
          {hoverHit && (
            <div
              style={{
                position: 'fixed',
                left: `${hoverHit.screenX + 12}px`,
                top: `${hoverHit.screenY + 12}px`,
                background: '#0F172A',
                color: '#F8FAFC',
                padding: '8px 12px',
                borderRadius: '6px',
                fontSize: '11px',
                lineHeight: 1.4,
                boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
                border: '1px solid #334155',
                pointerEvents: 'none',
                zIndex: 100,
                maxWidth: '260px',
              }}
            >
              <div style={{ fontWeight: 700, color: '#38BDF8', marginBottom: '3px' }}>
                {hoverHit.event.hw_name || hoverHit.event.task_id}
              </div>
              <div>Start: <b>{hoverHit.event.start_ms.toFixed(2)} ms</b></div>
              <div>End: <b>{hoverHit.event.end_ms.toFixed(2)} ms</b></div>
              <div>Duration: <b>{hoverHit.event.duration_ms.toFixed(2)} ms</b></div>
              {hoverHit.event.token_wait_ms ? <div>Token Wait: <b style={{ color: '#FB923C' }}>{hoverHit.event.token_wait_ms.toFixed(2)} ms</b></div> : null}
              {hoverHit.event.slack_ms !== undefined ? (
                <div>Slack: <b style={{ color: hoverHit.event.slack_ms < 0 ? '#EF4444' : '#10B981' }}>{hoverHit.event.slack_ms.toFixed(2)} ms</b></div>
              ) : null}
            </div>
          )}
        </div>

        {/* Selected Task Inspector Drawer */}
        {selectedEvent && (
          <TimelineInspector
            event={selectedEvent}
            swTiming={selectedSwTiming}
            onClose={() => setSelectedTaskId(null)}
          />
        )}
      </div>
    </div>
  )
}
