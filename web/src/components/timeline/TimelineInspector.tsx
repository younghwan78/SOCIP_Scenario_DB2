import React from 'react'
import { X, Clock, AlertTriangle, Cpu, Layers } from 'lucide-react'
import type { SwTaskTiming, TimelineEvent } from '../../types'
import { Badge } from '../common/Badge'

interface TimelineInspectorProps {
  event: TimelineEvent | null
  swTiming?: SwTaskTiming
  onClose: () => void
}

export const TimelineInspector: React.FC<TimelineInspectorProps> = ({ event, swTiming, onClose }) => {
  if (!event) return null

  const isViolated = event.slack_ms !== undefined && event.slack_ms !== null && event.slack_ms < 0

  return (
    <aside
      style={{
        width: '320px',
        background: 'var(--bg-surface)',
        borderLeft: '1px solid var(--border-subtle)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflowY: 'auto',
        boxShadow: 'var(--shadow-lg)',
        zIndex: 5,
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '12px 16px',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'var(--bg-surface-raised)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Clock size={16} color="var(--brand-teal)" />
          <span style={{ fontWeight: 700, fontSize: '13px' }}>Task Inspector</span>
        </div>
        <button onClick={onClose} style={{ color: 'var(--text-muted)', cursor: 'pointer' }}>
          <X size={16} />
        </button>
      </div>

      {/* Body */}
      <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {/* Task Title & Badges */}
        <div>
          <div style={{ fontSize: '15px', fontWeight: 800, color: 'var(--text-primary)', wordBreak: 'break-all' }}>
            {event.hw_name || event.task_id}
          </div>
          <div style={{ display: 'flex', gap: '6px', marginTop: '6px', flexWrap: 'wrap' }}>
            {event.task_type && <Badge variant={event.task_type === 'sw' ? 'purple' : 'teal'}>{event.task_type.toUpperCase()}</Badge>}
            {event.edge_type && <Badge variant="warning">{event.edge_type}</Badge>}
            {event.critical && <Badge variant="error">CRITICAL PATH</Badge>}
            {isViolated && <Badge variant="error">DEADLINE VIOLATED</Badge>}
          </div>
        </div>

        {/* Timing Metrics Breakdown */}
        <div style={{ background: 'var(--bg-surface-raised)', padding: '12px', borderRadius: 'var(--radius-sm)' }}>
          <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '8px' }}>
            TIMING BREAKDOWN
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Start Time:</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{event.start_ms.toFixed(3)} ms</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>End Time:</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{event.end_ms.toFixed(3)} ms</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Duration:</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--brand-primary)' }}>
                {event.duration_ms.toFixed(3)} ms
              </span>
            </div>
            {event.token_wait_ms !== undefined && event.token_wait_ms > 0 && (
              <div style={{ display: 'flex', justifyContent: 'space-between', color: '#FB923C' }}>
                <span>Token Wait:</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{event.token_wait_ms.toFixed(3)} ms</span>
              </div>
            )}
            {event.resource_wait_ms !== undefined && event.resource_wait_ms > 0 && (
              <div style={{ display: 'flex', justifyContent: 'space-between', color: '#FBBF24' }}>
                <span>Resource Wait:</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{event.resource_wait_ms.toFixed(3)} ms</span>
              </div>
            )}
            {event.slack_ms !== undefined && (
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Slack vs Deadline:</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: isViolated ? 'var(--status-error)' : 'var(--status-success)' }}>
                  {event.slack_ms.toFixed(3)} ms
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Statistical Digest (if SW task from Perfetto) */}
        {swTiming && (
          <div style={{ background: 'var(--bg-surface-raised)', padding: '12px', borderRadius: 'var(--radius-sm)' }}>
            <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '8px' }}>
              PERFETTO STATISTICAL DIGEST
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Mean / p50:</span>
                <span style={{ fontFamily: 'var(--font-mono)' }}>{swTiming.mean_ms?.toFixed(2)} ms / {swTiming.p50_ms?.toFixed(2)} ms</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>p95 / Max:</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--status-warning)' }}>
                  {swTiming.p95_ms?.toFixed(2)} ms / {swTiming.max_ms?.toFixed(2)} ms
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Calls / Frame:</span>
                <span style={{ fontFamily: 'var(--font-mono)' }}>{swTiming.count_per_frame?.toFixed(2) || '1.0'}</span>
              </div>
            </div>
          </div>
        )}

        {/* Resource & Hardware Details */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-secondary)' }}>
            <Cpu size={14} />
            <span>Resource ID: <b>{event.resource_id || '-'}</b></span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-secondary)' }}>
            <Layers size={14} />
            <span>OTF Group: <b>{event.otf_group_id || '-'}</b></span>
          </div>
          {event.bottleneck_reason && (
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', color: '#F87171', background: 'rgba(239,68,68,0.1)', padding: '8px', borderRadius: '4px' }}>
              <AlertTriangle size={14} style={{ marginTop: '2px', flexShrink: 0 }} />
              <span>Bottleneck: {event.bottleneck_reason}</span>
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}
