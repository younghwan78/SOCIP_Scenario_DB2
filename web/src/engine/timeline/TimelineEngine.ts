import type { SwTaskTiming, TimelineEvent } from '../../types'
import type { HoverHitInfo, TimelineThemeColors, TrackDefinition, ViewportTransform } from './timelineTypes'

const DEFAULT_THEME: TimelineThemeColors = {
  bgApp: '#0B0F19',
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
  deadlinePassed: '#10B981',
  deadlineViolated: '#EF4444',
  criticalBorder: '#DC2626',
  tokenWait: '#FDBA74',
  resourceWait: '#94A3B8',
}

const RULER_HEIGHT = 32
const HEADER_WIDTH = 220
const TRACK_ROW_HEIGHT = 36
const TRACK_GAP = 6
const SLICE_PADDING_Y = 4

export class TimelineEngine {
  private canvas: HTMLCanvasElement | null = null
  private ctx: CanvasRenderingContext2D | null = null
  
  private events: TimelineEvent[] = []
  private swTimings: SwTaskTiming[] = []
  private tracks: TrackDefinition[] = []
  
  private transform: ViewportTransform = {
    startMs: 0,
    endMs: 66.6,
    scale: 20, // px per ms
    offsetY: 0,
  }

  private theme: TimelineThemeColors = DEFAULT_THEME
  private selectedTaskId: string | null = null
  private hoveredHit: HoverHitInfo | null = null
  
  private isDragging = false
  private dragStartX = 0
  private dragStartY = 0
  private dragStartMs = 0
  private dragSpanMs = 0
  private frameIntervalMs: number | null = null
  private resizeObserver: ResizeObserver | null = null
  private dragStartOffsetY = 0
  
  private animFrameId: number | null = null

  // Callbacks
  public onSelectSlice?: (taskId: string | null) => void
  public onHoverSlice?: (hit: HoverHitInfo | null) => void
  public onViewportChange?: (transform: ViewportTransform) => void

  constructor(themeOverride?: Partial<TimelineThemeColors>) {
    if (themeOverride) {
      this.theme = { ...DEFAULT_THEME, ...themeOverride }
    }
  }

  public attach(canvas: HTMLCanvasElement): void {
    this.canvas = canvas
    this.ctx = canvas.getContext('2d', { alpha: false })
    this.bindEvents()
    this.resizeObserver = new ResizeObserver(() => this.resize())
    this.resizeObserver.observe(canvas)
    this.resize()
    this.requestRender()
  }

  public detach(): void {
    this.unbindEvents()
    this.resizeObserver?.disconnect()
    this.resizeObserver = null
    if (this.animFrameId) {
      cancelAnimationFrame(this.animFrameId)
      this.animFrameId = null
    }
    this.canvas = null
    this.ctx = null
  }

  public setData(events: TimelineEvent[], swTimings: SwTaskTiming[] = []): void {
    this.events = events || []
    this.hoveredHit = null
    this.selectedTaskId = null
    this.onHoverSlice?.(null)
    const sourceFps = events.find(event => event.source_fps && event.source_fps > 0)?.source_fps
    this.frameIntervalMs = sourceFps ? 1000 / sourceFps : null
    this.swTimings = swTimings || []
    this.buildTracks()
    this.fitAll()
  }

  public getSwTimings(): SwTaskTiming[] {
    return this.swTimings
  }

  public setSelectedTaskId(taskId: string | null): void {
    this.selectedTaskId = taskId
    this.requestRender()
  }

  public fitAll(): void {
    if (!this.events.length) {
      this.transform.startMs = 0
      this.transform.endMs = 66.6
      this.updateScale()
      this.requestRender()
      return
    }

    const minStart = this.events.reduce((value, event) => Math.min(value, event.start_ms ?? 0), Infinity)
    const maxEnd = this.events.reduce((value, event) => Math.max(value, event.end_ms ?? (event.start_ms + (event.duration_ms ?? 0))), 0)
    const paddingMs = Math.max(2, (maxEnd - minStart) * 0.08)

    this.transform.startMs = Math.max(0, minStart - paddingMs)
    this.transform.endMs = maxEnd + paddingMs
    this.transform.offsetY = 0
    this.updateScale()
    this.requestRender()
  }

  public zoomBy(factor: number, centerMs?: number): void {
    if (!this.canvas) return
    const currentSpan = this.transform.endMs - this.transform.startMs
    const targetSpan = Math.max(1, currentSpan * factor)
    const focalMs = centerMs ?? (this.transform.startMs + currentSpan / 2)
    const ratio = (focalMs - this.transform.startMs) / currentSpan

    this.transform.startMs = Math.max(-5, focalMs - targetSpan * ratio)
    this.transform.endMs = this.transform.startMs + targetSpan
    this.updateScale()
    this.requestRender()
  }

  public panBy(deltaMs: number): void {
    this.transform.startMs += deltaMs
    this.transform.endMs += deltaMs
    this.requestRender()
  }

  public resize(): void {
    if (!this.canvas) return
    const rect = this.canvas.getBoundingClientRect()
    const dpr = window.devicePixelRatio || 1
    
    this.canvas.width = Math.floor(rect.width * dpr)
    this.canvas.height = Math.floor(rect.height * dpr)
    
    if (this.ctx) {
      this.ctx.scale(dpr, dpr)
    }
    this.updateScale()
    this.requestRender()
  }

  private updateScale(): void {
    if (!this.canvas) return
    const width = this.canvas.getBoundingClientRect().width - HEADER_WIDTH
    const span = Math.max(0.001, this.transform.endMs - this.transform.startMs)
    this.transform.scale = width / span
    this.onViewportChange?.(this.transform)
  }

  // --- Track Building --------------------------------------------------------

  private buildTracks(): void {
    const trackMap = new Map<string, TrackDefinition>()

    for (const event of this.events) {
      let trackId = 'misc'
      let trackTitle = 'Tasks'
      let category: TrackDefinition['category'] = 'sw'
      let color = '#64748B'

      if (event.constraint_type === 'source' || event.task_id?.includes('sensor')) {
        trackId = 'track_source'
        trackTitle = 'Sensor In (V-Valid)'
        category = 'sync'
        color = '#22C55E'
      } else if (event.constraint_type === 'sink' || event.task_id?.includes('display')) {
        trackId = 'track_sink'
        trackTitle = 'Display Output'
        category = 'sync'
        color = '#0EA5E9'
      } else if (event.otf_group_id || event.edge_type?.toLowerCase().includes('otf')) {
        const group = event.otf_group_id || 'Group'
        trackId = `track_otf_${group}`
        trackTitle = `OTF: ${group}`
        category = 'hw_otf'
        color = '#0F766E'
      } else if (event.task_type === 'sw' || event.task_id?.startsWith('sw_') || event.hw_name?.toLowerCase().includes('sw')) {
        const res = event.resource_id || 'CPU'
        trackId = `track_sw_${res}`
        trackTitle = `SW: ${res}`
        category = 'sw'
        color = '#9333EA'
      } else {
        const res = event.resource_id || event.node_id || 'HW'
        trackId = `track_m2m_${res}`
        trackTitle = `HW M2M: ${res}`
        category = 'hw_m2m'
        color = '#EA580C'
      }

      if (!trackMap.has(trackId)) {
        trackMap.set(trackId, {
          id: trackId,
          title: trackTitle,
          category,
          color,
          height: TRACK_ROW_HEIGHT,
          events: [],
        })
      }
      trackMap.get(trackId)!.events.push(event)
    }

    // Sort tracks logically: Sync -> OTF -> M2M -> SW
    const order: Record<TrackDefinition['category'], number> = {
      sync: 0,
      hw_otf: 1,
      hw_m2m: 2,
      sw: 3,
      system: 4,
    }

    this.tracks = Array.from(trackMap.values()).sort((a, b) => {
      if (order[a.category] !== order[b.category]) {
        return order[a.category] - order[b.category]
      }
      return a.title.localeCompare(b.title)
    })
  }

  // --- Rendering -------------------------------------------------------------

  public requestRender(): void {
    if (this.animFrameId) return
    this.animFrameId = requestAnimationFrame(() => {
      this.animFrameId = null
      this.render()
    })
  }

  private render(): void {
    if (!this.canvas || !this.ctx) return
    const rect = this.canvas.getBoundingClientRect()
    const width = rect.width
    const height = rect.height

    const ctx = this.ctx
    ctx.save()

    // 1. Clear background
    ctx.fillStyle = this.theme.bgCanvas
    ctx.fillRect(0, 0, width, height)

    // 2. Render Frame Background Bands
    this.renderFrameBands(ctx, width, height)

    // 3. Render Tracks and Slices
    this.renderTracks(ctx, width, height)

    // 4. Render Time Ruler on Top
    this.renderTimeRuler(ctx, width)

    // 5. Render Track Headers (Left sidebar)
    this.renderTrackHeaders(ctx, height)

    // 6. Render Selection and Hover Indicators
    this.renderHoverAndSelection(ctx, height)

    ctx.restore()
  }

  private timeToX(timeMs: number): number {
    return HEADER_WIDTH + (timeMs - this.transform.startMs) * this.transform.scale
  }

  private xToTime(x: number): number {
    return this.transform.startMs + (x - HEADER_WIDTH) / this.transform.scale
  }

  private renderFrameBands(ctx: CanvasRenderingContext2D, width: number, height: number): void {
    const frameIntervalMs = this.frameIntervalMs
    if (!frameIntervalMs) return
    const firstFrame = Math.floor(this.transform.startMs / frameIntervalMs)
    const lastFrame = Math.ceil(this.transform.endMs / frameIntervalMs)

    for (let f = firstFrame; f <= lastFrame; f++) {
      const x0 = Math.max(HEADER_WIDTH, this.timeToX(f * frameIntervalMs))
      const x1 = Math.min(width, this.timeToX((f + 1) * frameIntervalMs))
      if (x1 <= HEADER_WIDTH || x0 >= width) continue

      ctx.fillStyle = f % 2 === 0 ? this.theme.frameBandEven : this.theme.frameBandOdd
      ctx.fillRect(x0, RULER_HEIGHT, x1 - x0, height - RULER_HEIGHT)

      // Frame Boundary Line
      ctx.strokeStyle = this.theme.borderSubtle
      ctx.lineWidth = 1
      ctx.setLineDash([4, 4])
      ctx.beginPath()
      ctx.moveTo(x0, RULER_HEIGHT)
      ctx.lineTo(x0, height)
      ctx.stroke()
      ctx.setLineDash([])

      // Frame Label at Top
      ctx.fillStyle = this.theme.textMuted
      ctx.font = '10px Inter, sans-serif'
      ctx.fillText(`Frame ${f}`, x0 + 6, RULER_HEIGHT + 14)
    }
  }

  private renderTracks(ctx: CanvasRenderingContext2D, width: number, height: number): void {
    let currentY = RULER_HEIGHT + this.transform.offsetY

    for (const track of this.tracks) {
      if (currentY + track.height >= RULER_HEIGHT && currentY <= height) {
        // Track row background & separator
        ctx.fillStyle = 'rgba(255, 255, 255, 0.01)'
        ctx.fillRect(HEADER_WIDTH, currentY, width - HEADER_WIDTH, track.height)

        ctx.strokeStyle = this.theme.borderSubtle
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.moveTo(HEADER_WIDTH, currentY + track.height)
        ctx.lineTo(width, currentY + track.height)
        ctx.stroke()

        // Render Slices in this Track
        this.renderSlices(ctx, track, currentY, width)
      }
      currentY += track.height + TRACK_GAP
    }
  }

  private renderSlices(ctx: CanvasRenderingContext2D, track: TrackDefinition, trackY: number, canvasWidth: number): void {
    const sliceY = trackY + SLICE_PADDING_Y
    const sliceH = track.height - SLICE_PADDING_Y * 2

    for (const event of track.events) {
      const startMs = event.start_ms || 0
      const endMs = event.end_ms || startMs + (event.duration_ms || 0)
      const x0 = this.timeToX(startMs)
      const x1 = this.timeToX(endMs)
      const sliceW = Math.max(2, x1 - x0)

      if (x1 < HEADER_WIDTH || x0 > canvasWidth) continue

      const isSelected = this.selectedTaskId === event.task_id
      const isCritical = Boolean(event.critical)

      // 1. Draw Slice Box
      ctx.fillStyle = track.color
      ctx.beginPath()
      ctx.roundRect(x0, sliceY, sliceW, sliceH, 4)
      ctx.fill()

      // Critical Path Border or Selection Border
      if (isSelected) {
        ctx.strokeStyle = '#FFFFFF'
        ctx.lineWidth = 2
        ctx.stroke()
      } else if (isCritical) {
        ctx.strokeStyle = this.theme.criticalBorder
        ctx.lineWidth = 2
        ctx.stroke()
      }

      // 2. Token Wait / Resource Wait Hatching
      if (event.token_wait_ms && event.token_wait_ms > 0) {
        const waitW = event.token_wait_ms * this.transform.scale
        ctx.fillStyle = this.theme.tokenWait
        ctx.globalAlpha = 0.4
        ctx.fillRect(x0 - waitW, sliceY, waitW, sliceH)
        ctx.globalAlpha = 1.0
      }

      // 3. Slice Label
      if (sliceW > 24) {
        ctx.fillStyle = '#FFFFFF'
        ctx.font = '11px Inter, sans-serif'
        ctx.save()
        ctx.beginPath()
        ctx.rect(x0 + 4, sliceY, sliceW - 8, sliceH)
        ctx.clip()
        const label = event.hw_name || event.task_id
        ctx.fillText(label, x0 + 6, sliceY + sliceH / 2 + 4)
        ctx.restore()
      }

      // 4. Deadline Marker (if any)
      if (event.deadline_ms !== undefined && event.deadline_ms !== null) {
        const deadlineX = this.timeToX(event.deadline_ms)
        const isViolated = event.slack_ms !== undefined && event.slack_ms < 0
        ctx.fillStyle = isViolated ? this.theme.deadlineViolated : this.theme.deadlinePassed
        ctx.strokeStyle = isViolated ? this.theme.deadlineViolated : this.theme.deadlinePassed
        ctx.lineWidth = 2
        
        // Draw cross marker 'X'
        ctx.beginPath()
        ctx.moveTo(deadlineX - 4, sliceY)
        ctx.lineTo(deadlineX + 4, sliceY + sliceH)
        ctx.moveTo(deadlineX + 4, sliceY)
        ctx.lineTo(deadlineX - 4, sliceY + sliceH)
        ctx.stroke()
      }
    }
  }

  private renderTimeRuler(ctx: CanvasRenderingContext2D, width: number): void {
    // Ruler background
    ctx.fillStyle = this.theme.rulerBg
    ctx.fillRect(0, 0, width, RULER_HEIGHT)

    ctx.strokeStyle = this.theme.borderDefault
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(0, RULER_HEIGHT)
    ctx.lineTo(width, RULER_HEIGHT)
    ctx.stroke()

    // Determine Tick Interval based on current scale
    const spanMs = this.transform.endMs - this.transform.startMs
    let tickIntervalMs = 10
    if (spanMs < 10) tickIntervalMs = 1
    else if (spanMs < 30) tickIntervalMs = 5
    else if (spanMs < 100) tickIntervalMs = 10
    else if (spanMs < 300) tickIntervalMs = 25
    else tickIntervalMs = 50

    const firstTick = Math.floor(this.transform.startMs / tickIntervalMs) * tickIntervalMs
    const lastTick = Math.ceil(this.transform.endMs / tickIntervalMs) * tickIntervalMs

    ctx.fillStyle = this.theme.textSecondary
    ctx.font = '11px JetBrains Mono, monospace'

    for (let t = firstTick; t <= lastTick; t += tickIntervalMs) {
      const x = this.timeToX(t)
      if (x < HEADER_WIDTH || x > width) continue

      // Major Tick
      ctx.strokeStyle = this.theme.rulerTick
      ctx.beginPath()
      ctx.moveTo(x, RULER_HEIGHT - 8)
      ctx.lineTo(x, RULER_HEIGHT)
      ctx.stroke()

      // Time Text
      ctx.fillText(`${t.toFixed(1)} ms`, x + 4, RULER_HEIGHT - 10)
    }
  }

  private renderTrackHeaders(ctx: CanvasRenderingContext2D, height: number): void {
    // Header Column Background
    ctx.fillStyle = this.theme.bgTrackHeader
    ctx.fillRect(0, 0, HEADER_WIDTH, height)

    ctx.strokeStyle = this.theme.borderDefault
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(HEADER_WIDTH, 0)
    ctx.lineTo(HEADER_WIDTH, height)
    ctx.stroke()

    // Corner title
    ctx.fillStyle = this.theme.textPrimary
    ctx.font = 'bold 12px Inter, sans-serif'
    ctx.fillText('Timeline Tracks', 14, 20)

    let currentY = RULER_HEIGHT + this.transform.offsetY
    for (const track of this.tracks) {
      if (currentY + track.height >= RULER_HEIGHT && currentY <= height) {
        // Track color dot
        ctx.fillStyle = track.color
        ctx.beginPath()
        ctx.arc(18, currentY + track.height / 2, 4, 0, Math.PI * 2)
        ctx.fill()

        // Track title
        ctx.fillStyle = this.theme.textPrimary
        ctx.font = '500 12px Inter, sans-serif'
        ctx.fillText(track.title, 32, currentY + track.height / 2 + 4)
      }
      currentY += track.height + TRACK_GAP
    }
  }

  private renderHoverAndSelection(ctx: CanvasRenderingContext2D, height: number): void {
    if (!this.hoveredHit) return

    const { canvasX, canvasY } = this.hoveredHit
    if (canvasX < HEADER_WIDTH || canvasY < RULER_HEIGHT) return

    // Draw vertical time cursor line
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.4)'
    ctx.lineWidth = 1
    ctx.setLineDash([2, 2])
    ctx.beginPath()
    ctx.moveTo(canvasX, RULER_HEIGHT)
    ctx.lineTo(canvasX, height)
    ctx.stroke()
    ctx.setLineDash([])
  }

  // --- Interaction & Event Handling -----------------------------------------

  private bindEvents(): void {
    if (!this.canvas) return

    this.canvas.addEventListener('mousedown', this.onMouseDown)
    window.addEventListener('mousemove', this.onMouseMove)
    window.addEventListener('mouseup', this.onMouseUp)
    this.canvas.addEventListener('wheel', this.onWheel, { passive: false })
    window.addEventListener('keydown', this.onKeyDown)
    window.addEventListener('resize', this.onWindowResize)
  }

  private unbindEvents(): void {
    if (!this.canvas) return
    this.canvas.removeEventListener('mousedown', this.onMouseDown)
    window.removeEventListener('mousemove', this.onMouseMove)
    window.removeEventListener('mouseup', this.onMouseUp)
    this.canvas.removeEventListener('wheel', this.onWheel)
    window.removeEventListener('keydown', this.onKeyDown)
    window.removeEventListener('resize', this.onWindowResize)
  }

  private onMouseDown = (e: MouseEvent) => {
    if (e.button !== 0) return // Left click only
    this.isDragging = true
    this.dragStartX = e.clientX
    this.dragStartY = e.clientY
    this.dragStartMs = this.transform.startMs
    this.dragSpanMs = this.transform.endMs - this.transform.startMs
    this.dragStartOffsetY = this.transform.offsetY

    // Check hit slice
    const hit = this.hitTest(e.offsetX, e.offsetY)
    if (hit) {
      this.selectedTaskId = hit.event.task_id
      this.onSelectSlice?.(hit.event.task_id)
    } else if (e.offsetX > HEADER_WIDTH && e.offsetY > RULER_HEIGHT) {
      this.selectedTaskId = null
      this.onSelectSlice?.(null)
    }
    this.requestRender()
  }

  private onMouseMove = (e: MouseEvent) => {
    if (!this.canvas) return
    const rect = this.canvas.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top

    if (this.isDragging) {
      const deltaX = e.clientX - this.dragStartX
      const deltaY = e.clientY - this.dragStartY
      const deltaMs = -deltaX / this.transform.scale

      this.transform.startMs = this.dragStartMs + deltaMs
      this.transform.endMs = this.transform.startMs + this.dragSpanMs
      this.transform.offsetY = Math.min(0, this.dragStartOffsetY + deltaY)

      this.requestRender()
    } else {
      // Hover hit test
      const hit = this.hitTest(x, y)
      if (hit) {
        this.hoveredHit = {
          ...hit,
          screenX: e.clientX,
          screenY: e.clientY,
        }
        this.canvas.style.cursor = 'pointer'
      } else {
        this.hoveredHit = null
        this.canvas.style.cursor = x > HEADER_WIDTH ? 'crosshair' : 'default'
      }
      this.onHoverSlice?.(this.hoveredHit)
      this.requestRender()
    }
  }

  private onMouseUp = () => {
    this.isDragging = false
  }

  private onWheel = (e: WheelEvent) => {
    e.preventDefault()
    if (!this.canvas) return
    const rect = this.canvas.getBoundingClientRect()
    const mouseX = e.clientX - rect.left
    const centerMs = this.xToTime(mouseX)

    if (e.ctrlKey || e.metaKey || Math.abs(e.deltaY) > 0) {
      const zoomFactor = e.deltaY > 0 ? 1.15 : 0.85
      this.zoomBy(zoomFactor, centerMs)
    }
  }

  private onKeyDown = (e: KeyboardEvent) => {
    // Prevent interfering with inputs
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement)?.tagName)) {
      return
    }

    const span = this.transform.endMs - this.transform.startMs
    const panStep = span * 0.1

    switch (e.key.toLowerCase()) {
      case 'w':
        this.zoomBy(0.8)
        break
      case 's':
        this.zoomBy(1.25)
        break
      case 'a':
        this.panBy(-panStep)
        break
      case 'd':
        this.panBy(panStep)
        break
      case 'f':
        this.fitAll()
        break
    }
  }

  private onWindowResize = () => {
    this.resize()
  }

  private hitTest(x: number, y: number): { event: TimelineEvent; track: TrackDefinition; canvasX: number; canvasY: number } | null {
    if (x < HEADER_WIDTH || y < RULER_HEIGHT) return null

    let currentY = RULER_HEIGHT + this.transform.offsetY
    for (const track of this.tracks) {
      if (y >= currentY && y <= currentY + track.height) {
        for (const event of track.events) {
          const startMs = event.start_ms || 0
          const endMs = event.end_ms || startMs + (event.duration_ms || 0)
          const x0 = this.timeToX(startMs)
          const x1 = this.timeToX(endMs)
          if (x >= x0 && x <= x1) {
            return { event, track, canvasX: x, canvasY: y }
          }
        }
      }
      currentY += track.height + TRACK_GAP
    }
    return null
  }
}
