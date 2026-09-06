import React from 'react'
import { Activity, Layers, Database, Search, Cpu, Sparkles } from 'lucide-react'
import { useScenarioStore, type ActiveTab } from '../../store/scenarioStore'

export const Header: React.FC = () => {
  const { activeTab, setActiveTab } = useScenarioStore()

  const navItems: Array<{ key: ActiveTab; label: string; icon: React.ReactNode }> = [
    { key: 'timeline', label: 'Perfetto Timeline', icon: <Activity size={15} /> },
    { key: 'pipeline', label: 'Pipeline Viewer', icon: <Layers size={15} /> },
    { key: 'evidence', label: 'Evidence Dashboard', icon: <Sparkles size={15} /> },
    { key: 'explorer', label: 'DB Explorer', icon: <Database size={15} /> },
    { key: 'query', label: 'Architecture Query', icon: <Search size={15} /> },
  ]

  return (
    <header
      style={{
        height: 'var(--header-height)',
        background: 'var(--bg-surface)',
        borderBottom: '1px solid var(--border-subtle)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 16px',
        userSelect: 'none',
        zIndex: 10,
      }}
    >
      {/* Brand Logo & Title */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <div
          style={{
            width: '28px',
            height: '28px',
            borderRadius: 'var(--radius-sm)',
            background: 'linear-gradient(135deg, var(--brand-primary), var(--brand-teal))',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#FFFFFF',
            boxShadow: '0 2px 8px rgba(59, 130, 246, 0.4)',
          }}
        >
          <Cpu size={16} />
        </div>
        <div>
          <span style={{ fontWeight: 800, fontSize: '15px', letterSpacing: '-0.02em', color: 'var(--text-primary)' }}>
            SOCIP Scenario DB
          </span>
          <span
            style={{
              marginLeft: '8px',
              fontSize: '10px',
              fontWeight: 700,
              padding: '1px 6px',
              borderRadius: 'var(--radius-xs)',
              background: 'var(--brand-primary-subtle)',
              color: 'var(--brand-primary)',
            }}
          >
            SPA 2.0
          </span>
        </div>
      </div>

      {/* Main Navigation Tabs */}
      <nav style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
        {navItems.map((item) => {
          const isActive = activeTab === item.key
          return (
            <button
              key={item.key}
              onClick={() => setActiveTab(item.key)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 12px',
                borderRadius: 'var(--radius-sm)',
                fontSize: 'var(--text-sm)',
                fontWeight: isActive ? 700 : 500,
                color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                background: isActive ? 'var(--bg-surface-raised)' : 'transparent',
                border: isActive ? '1px solid var(--border-default)' : '1px solid transparent',
                transition: 'background var(--transition-fast), border-color var(--transition-fast)',
              }}
            >
              {item.icon}
              {item.label}
            </button>
          )
        })}
      </nav>

      {/* Status Indicators */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: 'var(--text-muted)' }}>
          <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'var(--text-muted)' }} />
          <span>Scenario workspace</span>
        </div>
      </div>
    </header>
  )
}
