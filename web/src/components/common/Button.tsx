import React from 'react'

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  icon?: React.ReactNode
}

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'secondary',
  size = 'md',
  icon,
  style,
  disabled,
  ...props
}) => {
  const variantStyles: Record<string, React.CSSProperties> = {
    primary: {
      background: 'var(--brand-primary)',
      color: '#FFFFFF',
      border: '1px solid var(--brand-primary-hover)',
    },
    secondary: {
      background: 'var(--bg-surface-raised)',
      color: 'var(--text-primary)',
      border: '1px solid var(--border-default)',
    },
    ghost: {
      background: 'transparent',
      color: 'var(--text-secondary)',
      border: '1px solid transparent',
    },
    danger: {
      background: 'var(--status-error-subtle)',
      color: 'var(--status-error)',
      border: '1px solid rgba(239, 68, 68, 0.4)',
    },
  }

  const sizeStyles: Record<string, React.CSSProperties> = {
    sm: { padding: '4px 8px', fontSize: 'var(--text-xs)', gap: '4px' },
    md: { padding: '6px 12px', fontSize: 'var(--text-sm)', gap: '6px' },
    lg: { padding: '8px 16px', fontSize: 'var(--text-base)', gap: '8px' },
  }

  return (
    <button
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontWeight: 600,
        borderRadius: 'var(--radius-sm)',
        transition: 'all var(--transition-fast)',
        opacity: disabled ? 0.5 : 1,
        cursor: disabled ? 'not-allowed' : 'pointer',
        ...variantStyles[variant],
        ...sizeStyles[size],
        ...style,
      }}
      disabled={disabled}
      {...props}
    >
      {icon && <span style={{ display: 'flex', alignItems: 'center' }}>{icon}</span>}
      {children}
    </button>
  )
}
