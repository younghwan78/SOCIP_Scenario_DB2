export interface WorkbenchTheme {
  bgCanvas: string
  bgTrackHeader: string
  borderSubtle: string
  borderDefault: string
  textPrimary: string
  textSecondary: string
  textMuted: string
  rulerBg: string
  rulerTick: string
  frameBandEven: string
  frameBandOdd: string
  deadlineMet: string
  deadlineViolated: string
  criticalBorder: string
  selectionBorder: string
  tokenWait: string
  resourceWait: string
  brushFill: string
  brushBorder: string
  flowOut: string
  hoverCursor: string
  cssVars: Record<string, string>
}

// Matches the ScenarioDB "balanced engineering console" tokens in
// dashboard/components/ui_theme.py (light) so the workbench reads as part of
// the existing dashboard.
export const LIGHT_THEME: WorkbenchTheme = {
  bgCanvas: '#FBFAF7',
  bgTrackHeader: '#F1EDE6',
  borderSubtle: '#E8E0D6',
  borderDefault: '#DED8CF',
  textPrimary: '#111827',
  textSecondary: '#667085',
  textMuted: '#98A2B3',
  rulerBg: '#FFFFFF',
  rulerTick: '#CFC6BA',
  frameBandEven: 'rgba(17, 24, 39, 0.015)',
  frameBandOdd: 'rgba(47, 111, 104, 0.045)',
  deadlineMet: '#16A34A',
  deadlineViolated: '#DC2626',
  criticalBorder: '#B91C1C',
  selectionBorder: '#2F6F68',
  tokenWait: '#FDBA74',
  resourceWait: '#CBD5E1',
  brushFill: 'rgba(47, 111, 104, 0.12)',
  brushBorder: '#2F6F68',
  flowOut: '#D97706',
  hoverCursor: 'rgba(17, 24, 39, 0.35)',
  cssVars: {
    '--wb-border': '#DED8CF',
    '--wb-toolbar-bg': '#F1EDE6',
    '--wb-surface': '#FFFFFF',
    '--wb-text': '#111827',
    '--wb-muted': '#667085',
    '--wb-primary': '#2F6F68',
  },
}

export const DARK_THEME: WorkbenchTheme = {
  bgCanvas: '#111827',
  bgTrackHeader: '#161F30',
  borderSubtle: '#1F2937',
  borderDefault: '#374151',
  textPrimary: '#F9FAFB',
  textSecondary: '#9CA3AF',
  textMuted: '#6B7280',
  rulerBg: '#1A2333',
  rulerTick: '#4B5563',
  frameBandEven: 'rgba(255, 255, 255, 0.02)',
  frameBandOdd: 'rgba(59, 130, 246, 0.04)',
  deadlineMet: '#10B981',
  deadlineViolated: '#EF4444',
  criticalBorder: '#DC2626',
  selectionBorder: '#5EEAD4',
  tokenWait: '#FDBA74',
  resourceWait: '#94A3B8',
  brushFill: 'rgba(94, 234, 212, 0.10)',
  brushBorder: '#5EEAD4',
  flowOut: '#FDBA74',
  hoverCursor: 'rgba(255, 255, 255, 0.4)',
  cssVars: {
    '--wb-border': '#374151',
    '--wb-toolbar-bg': '#161F30',
    '--wb-surface': '#1F2937',
    '--wb-text': '#F9FAFB',
    '--wb-muted': '#9CA3AF',
    '--wb-primary': '#5EEAD4',
  },
}

export function themeByName(name: string | undefined): WorkbenchTheme {
  return name === 'dark' ? DARK_THEME : LIGHT_THEME
}
