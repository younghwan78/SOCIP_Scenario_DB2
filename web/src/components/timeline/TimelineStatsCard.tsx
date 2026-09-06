import React from 'react'
import type { TimelineEvent } from '../../types'

interface TimelineStatsCardProps {
  events: TimelineEvent[]
}

export const TimelineStatsCard = React.memo(function TimelineStatsCard({ events }: TimelineStatsCardProps) {
  if (!events || events.length === 0) return null

  const endMs = Math.max(...events.map((e) => e.end_ms || (e.start_ms + (e.duration_ms || 0))), 0)
  const criticalEvents = events.filter((e) => e.critical)
  const criticalCount = criticalEvents.length
  const criticalMs = criticalEvents.reduce((acc, e) => acc + (e.duration_ms || 0), 0)

  const maxResourceWait = Math.max(...events.map((e) => e.resource_wait_ms || 0), 0)
  const maxTokenWait = Math.max(...events.map((e) => e.token_wait_ms || 0), 0)

  const slackEvents = events.filter((e) => e.slack_ms !== undefined && e.slack_ms !== null)
  const tightestSlack = slackEvents.length > 0 ? Math.min(...slackEvents.map((e) => e.slack_ms!)) : null

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(5, 1fr)',
        gap: '10px',
        padding: '10px 16px',
        background: 'var(--bg-surface)',
        borderBottom: '1px solid var(--border-subtle)',
      }}
    >
      {/* Metric 1: Timeline End */}
      <div style={{ padding: '8px 12px', background: 'var(--bg-surface-raised)', borderRadius: 'var(--radius-sm)' }}>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 600 }}>Timeline End</div>
        <div style={{ fontSize: '16px', fontWeight: 800, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
          {endMs.toFixed(2)} ms
        </div>
      </div>

      {/* Metric 2: Critical Path */}
      <div style={{ padding: '8px 12px', background: 'var(--bg-surface-raised)', borderRadius: 'var(--radius-sm)' }}>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 600 }}>
          Critical Task Duration Sum ({criticalCount} tasks)
        </div>
        <div style={{ fontSize: '16px', fontWeight: 800, color: '#F87171', fontFamily: 'var(--font-mono)' }}>
          {criticalMs.toFixed(2)} ms
        </div>
      </div>

      {/* Metric 3: Max Resource Wait */}
      <div style={{ padding: '8px 12px', background: 'var(--bg-surface-raised)', borderRadius: 'var(--radius-sm)' }}>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 600 }}>Max Resource Wait</div>
        <div style={{ fontSize: '16px', fontWeight: 800, color: '#FBBF24', fontFamily: 'var(--font-mono)' }}>
          {maxResourceWait.toFixed(2)} ms
        </div>
      </div>

      {/* Metric 4: Max Token Wait */}
      <div style={{ padding: '8px 12px', background: 'var(--bg-surface-raised)', borderRadius: 'var(--radius-sm)' }}>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 600 }}>Max Token Wait</div>
        <div style={{ fontSize: '16px', fontWeight: 800, color: '#FB923C', fontFamily: 'var(--font-mono)' }}>
          {maxTokenWait.toFixed(2)} ms
        </div>
      </div>

      {/* Metric 5: Tightest Slack */}
      <div style={{ padding: '8px 12px', background: 'var(--bg-surface-raised)', borderRadius: 'var(--radius-sm)' }}>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 600 }}>Tightest Slack</div>
        <div
          style={{
            fontSize: '16px',
            fontWeight: 800,
            color: tightestSlack !== null && tightestSlack < 0 ? 'var(--status-error)' : 'var(--status-success)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {tightestSlack !== null ? `${tightestSlack.toFixed(2)} ms` : '-'}
        </div>
      </div>
    </div>
  )
})
