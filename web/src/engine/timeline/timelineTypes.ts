import type { TimelineEvent } from '../../types'

export interface TrackDefinition {
  id: string
  title: string
  category: 'sync' | 'hw_otf' | 'hw_m2m' | 'sw' | 'system'
  color: string
  height: number
  events: TimelineEvent[]
  collapsed?: boolean
  stats?: {
    totalDurationMs: number
    maxSlackMs?: number
    tightestSlackMs?: number
    p95Ms?: number
  }
}

export interface ViewportTransform {
  startMs: number
  endMs: number
  scale: number // pixels per ms
  offsetY: number // vertical scroll in px
}

export interface HoverHitInfo {
  event: TimelineEvent
  track: TrackDefinition
  canvasX: number
  canvasY: number
  screenX: number
  screenY: number
}

export interface TimelineThemeColors {
  bgApp: string
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
  deadlinePassed: string
  deadlineViolated: string
  criticalBorder: string
  tokenWait: string
  resourceWait: string
}
