import React, { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ZoomIn, ZoomOut, Maximize2 } from 'lucide-react'
import { api } from '../../api/client'
import { PipelineGraphEngine, type LayoutGraphResult, type LayoutedNode } from '../../engine/pipeline/PipelineGraphEngine'
import { useScenarioStore, type ViewLevel, type ViewMode } from '../../store/scenarioStore'
import { Button } from '../common/Button'
import { Badge } from '../common/Badge'
import type { ViewResponse } from '../../types'

export const PipelineViewer: React.FC = () => {
  const {
    scenarioId,
    variantId,
    viewLevel,
    setViewLevel,
    viewMode,
    setViewMode,
    expandTarget,
    setExpandTarget,
    simOverlayMode,
    simEvidenceId,
  } = useScenarioStore()

  const [layoutResult, setLayoutResult] = useState<LayoutGraphResult | null>(null)
  const [selectedNode, setSelectedNode] = useState<LayoutedNode | null>(null)
  const [scale, setScale] = useState<number>(1)
  const [offset, setOffset] = useState<{ x: number; y: number }>({ x: 40, y: 40 })
  const [isDragging, setIsDragging] = useState(false)
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 })

  const engineRef = useRef<PipelineGraphEngine | null>(null)
  const [layoutSource, setLayoutSource] = useState<ViewResponse | null>(null)
  const [layoutError, setLayoutError] = useState<string | null>(null)
  const moveFrame = useRef<number | null>(null)
  useEffect(() => {
    engineRef.current = new PipelineGraphEngine()
    return () => {
      engineRef.current?.dispose()
      engineRef.current = null
      if (moveFrame.current !== null) cancelAnimationFrame(moveFrame.current)
    }
  }, [])

  // Fetch Pipeline View Data from FastAPI
  const { data: viewData, isLoading, error } = useQuery({
    queryKey: ['pipelineView', scenarioId, variantId, viewLevel, viewMode, expandTarget, simOverlayMode, simEvidenceId],
    queryFn: () =>
      api.getView({
        scenarioId: scenarioId!,
        variantId: variantId || undefined,
        level: viewLevel,
        mode: viewMode,
        expand: expandTarget || undefined,
        sim: simOverlayMode === 'latest' ? 'latest' : 'none',
        simEvidenceId: simEvidenceId || undefined,
      }),
    enabled: Boolean(scenarioId),
  })

  const visibleLayoutError = layoutSource === viewData ? layoutError : null
  const computing = Boolean(viewData && layoutSource !== viewData)
  useEffect(() => {
    let active = true
    if (!viewData || !engineRef.current) return
    engineRef.current.layoutView(viewData).then(result => {
      if (active) { setLayoutResult(result); setLayoutSource(viewData); setLayoutError(null); setSelectedNode(null) }
    }).catch(reason => {
      if (active) {
        setLayoutResult(null); setLayoutSource(viewData); setSelectedNode(null)
        setLayoutError(reason instanceof Error ? reason.message : String(reason))
      }
    })
    return () => { active = false }
  }, [viewData])

  const handleMouseDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return
    e.currentTarget.setPointerCapture(e.pointerId)
    setIsDragging(true)
    setDragStart({ x: e.clientX - offset.x, y: e.clientY - offset.y })
  }

  const handleMouseMove = (e: React.PointerEvent) => {
    if (!isDragging) return
    const next = { x: e.clientX - dragStart.x, y: e.clientY - dragStart.y }
    if (moveFrame.current !== null) cancelAnimationFrame(moveFrame.current)
    moveFrame.current = requestAnimationFrame(() => { setOffset(next); moveFrame.current = null })
  }

  const handleMouseUp = () => {
    setIsDragging(false)
  }

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    const zoomFactor = e.deltaY > 0 ? 0.9 : 1.1
    setScale((prev) => Math.min(3, Math.max(0.2, prev * zoomFactor)))
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%', overflow: 'hidden' }}>
      {(error || visibleLayoutError) && <p role="alert">{error?.message || visibleLayoutError}</p>}
      {!scenarioId && <p role="status">Select a scenario to open its pipeline.</p>}
      {/* Level & Mode Selector Toolbar */}
      <div
        style={{
          height: '46px',
          background: 'var(--bg-surface)',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 16px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {/* Level Switcher */}
          <div style={{ display: 'flex', background: 'var(--bg-surface-raised)', borderRadius: 'var(--radius-sm)', padding: '2px' }}>
            {([0, 1, 2] as ViewLevel[]).map((lvl) => (
              <button
                key={lvl}
                onClick={() => setViewLevel(lvl)}
                style={{
                  padding: '4px 10px',
                  borderRadius: 'var(--radius-xs)',
                  fontSize: '12px',
                  fontWeight: viewLevel === lvl ? 700 : 500,
                  color: viewLevel === lvl ? 'var(--text-primary)' : 'var(--text-secondary)',
                  background: viewLevel === lvl ? 'var(--brand-primary)' : 'transparent',
                }}
              >
                Level {lvl}
              </button>
            ))}
          </div>

          {/* Mode Switcher for Level 0 */}
          {viewLevel === 0 && (
            <div style={{ display: 'flex', background: 'var(--bg-surface-raised)', borderRadius: 'var(--radius-sm)', padding: '2px' }}>
              {(['architecture', 'topology', 'resource'] as ViewMode[]).map((m) => (
                <button
                  key={m}
                  onClick={() => setViewMode(m)}
                  style={{
                    padding: '4px 10px',
                    borderRadius: 'var(--radius-xs)',
                    fontSize: '12px',
                    fontWeight: viewMode === m ? 700 : 500,
                    color: viewMode === m ? 'var(--text-primary)' : 'var(--text-secondary)',
                    background: viewMode === m ? 'var(--bg-surface-active)' : 'transparent',
                  }}
                >
                  {m.charAt(0).toUpperCase() + m.slice(1)}
                </button>
              ))}
            </div>
          )}

          {/* Drill-down Target for Level 2 */}
          {viewLevel === 2 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Expand:</span>
              <select
                aria-label="Subsystem to expand"
                value={expandTarget || 'camera'}
                onChange={(e) => setExpandTarget(e.target.value)}
                style={{ padding: '3px 8px', fontSize: '12px' }}
              >
                <option value="camera">Camera Subsystem</option>
                <option value="video">Video / Codec Subsystem</option>
                <option value="display">Display Subsystem</option>
              </select>
            </div>
          )}
        </div>

        {/* View Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Button size="sm" icon={<ZoomIn size={14} />} onClick={() => setScale((s) => s * 1.2)}>
            Zoom In
          </Button>
          <Button size="sm" icon={<ZoomOut size={14} />} onClick={() => setScale((s) => s * 0.8)}>
            Zoom Out
          </Button>
          <Button size="sm" icon={<Maximize2 size={14} />} onClick={() => { setScale(1); setOffset({ x: 40, y: 40 }) }}>
            Reset View
          </Button>
        </div>
      </div>

      {/* SVG Canvas Area + Side Inspector */}
      <div style={{ display: 'flex', flex: 1, position: 'relative', overflow: 'hidden' }}>
        <div
          onPointerDown={handleMouseDown}
          onPointerMove={handleMouseMove}
          onPointerUp={handleMouseUp}
          onPointerCancel={handleMouseUp}
          onWheel={handleWheel}
          style={{
            flex: 1,
            width: '100%',
            height: '100%',
            cursor: isDragging ? 'grabbing' : 'grab',
            touchAction: 'none',
            position: 'relative',
            background: 'var(--bg-app)',
          }}
        >
          {(isLoading || computing) && (
            <div
              style={{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'rgba(11,15,25,0.6)',
                zIndex: 2,
                color: 'var(--text-secondary)',
              }}
            >
              Computing ELK.js orthogonal layout...
            </div>
          )}

          {layoutResult && layoutSource === viewData && (
            <svg
              style={{ width: '100%', height: '100%', display: 'block' }}
            >
              <defs>
                <marker id="arrow-teal" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
                  <path d="M0,0 L0,6 L7,3 z" fill="#14B8A6" />
                </marker>
                <marker id="arrow-orange" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
                  <path d="M0,0 L0,6 L7,3 z" fill="#F97316" />
                </marker>
                <marker id="arrow-purple" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
                  <path d="M0,0 L0,6 L7,3 z" fill="#8B5CF6" />
                </marker>
              </defs>

              <g transform={`translate(${offset.x}, ${offset.y}) scale(${scale})`}>
                {/* 1. Edges */}
                {layoutResult.edges.map((edge) => (
                  <g key={edge.id}>
                    {edge.sections.map((sec, idx) => {
                      let pathData = `M ${sec.startPoint.x} ${sec.startPoint.y}`
                      if (sec.bendPoints) {
                        for (const bp of sec.bendPoints) {
                          pathData += ` L ${bp.x} ${bp.y}`
                        }
                      }
                      pathData += ` L ${sec.endPoint.x} ${sec.endPoint.y}`

                      return (
                        <path
                          key={idx}
                          d={pathData}
                          stroke={edge.strokeColor}
                          strokeWidth="2"
                          fill="none"
                          strokeDasharray={edge.flowType === 'M2M' ? '5 4' : 'none'}
                          markerEnd="url(#arrow-teal)"
                        />
                      )
                    })}
                  </g>
                ))}

                {/* 2. Nodes */}
                {layoutResult.nodes.map((node) => {
                  const isSelected = selectedNode?.id === node.id
                  return (
                    <g
                      key={node.id}
                      role="button" tabIndex={0} aria-label={`Inspect ${node.label}`}
                      onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedNode(node) } }}
                      transform={`translate(${node.x}, ${node.y})`}
                      onClick={(e) => {
                        e.stopPropagation()
                        setSelectedNode(node)
                      }}
                      style={{ cursor: 'pointer' }}
                    >
                      <rect
                        width={node.width}
                        height={node.height}
                        rx="6"
                        fill={node.color}
                        stroke={isSelected ? '#FFFFFF' : node.stroke}
                        strokeWidth={isSelected ? '2.5' : '1.5'}
                      />
                      <text
                        x={node.width / 2}
                        y={node.height / 2 + 4}
                        textAnchor="middle"
                        fill={node.textColor}
                        fontWeight="700"
                        fontSize="12"
                        fontFamily="Inter, sans-serif"
                      >
                        {node.label}
                      </text>
                    </g>
                  )
                })}
              </g>
            </svg>
          )}
        </div>

        {/* Selected Node Inspector Drawer */}
        {selectedNode && layoutSource === viewData && (
          <div
            style={{
              width: '300px',
              background: 'var(--bg-surface)',
              borderLeft: '1px solid var(--border-subtle)',
              padding: '16px',
              display: 'flex',
              flexDirection: 'column',
              gap: '12px',
              zIndex: 5,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontWeight: 700, fontSize: '13px' }}>IP Inspector</span>
              <button aria-label="Close inspector" onClick={() => setSelectedNode(null)} style={{ color: 'var(--text-muted)' }}>✕</button>
            </div>
            <div>
              <div style={{ fontSize: '15px', fontWeight: 800 }}>{selectedNode.label}</div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>ID: {selectedNode.id}</div>
              <div style={{ display: 'flex', gap: '6px', marginTop: '6px' }}>
                <Badge variant="teal">{selectedNode.type.toUpperCase()}</Badge>
                {selectedNode.layer && <Badge variant="purple">{selectedNode.layer}</Badge>}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
