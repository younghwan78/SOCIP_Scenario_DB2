import React from 'react'

export interface BadgeProps {
  children: React.ReactNode
  variant?: 'default' | 'success' | 'warning' | 'error' | 'info' | 'purple' | 'teal'
  size?: 'sm' | 'md'
  className?: string
}

export const Badge: React.FC<BadgeProps> = ({
  children,
  variant = 'default',
  size = 'md',
  className = '',
}) => {
  const variantStyles: Record<string, React.CSSProperties> = {
    default: { background: 'var(--bg-surface-active)', color: 'var(--text-secondary)', border: '1px solid var(--border-default)' },
    success: { background: 'var(--status-success-subtle)', color: 'var(--status-success)', border: '1px solid rgba(16, 185, 129, 0.3)' },
    warning: { background: 'var(--status-warning-subtle)', color: 'var(--status-warning)', border: '1px solid rgba(245, 158, 11, 0.3)' },
    error: { background: 'var(--status-error-subtle)', color: 'var(--status-error)', border: '1px solid rgba(239, 68, 68, 0.3)' },
    info: { background: 'var(--status-info-subtle)', color: 'var(--status-info)', border: '1px solid rgba(14, 165, 233, 0.3)' },
    purple: { background: 'var(--brand-purple-subtle)', color: 'var(--brand-purple)', border: '1px solid rgba(139, 92, 246, 0.3)' },
    teal: { background: 'var(--brand-teal-subtle)', color: 'var(--brand-teal)', border: '1px solid rgba(20, 184, 166, 0.3)' },
  }

  return (
    <span
      className={className}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        fontWeight: 600,
        borderRadius: 'var(--radius-full)',
        padding: size === 'sm' ? '1px 6px' : '2px 8px',
        fontSize: size === 'sm' ? '11px' : '12px',
        lineHeight: 1.3,
        whiteSpace: 'nowrap',
        ...variantStyles[variant],
      }}
    >
      {children}
    </span>
  )
}
