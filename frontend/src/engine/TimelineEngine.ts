// Canvas timeline renderer for the Scenario Workbench.
// Ported from the feat/modern-web-spa SPA engine and extended with per-slice
// colors matching timing_chart.py, lane-resolved tracks, wait hatching,
// deadline markers, and brush range selection.
import type { WorkbenchTheme } from '../theme'
import { rangeStats } from './aggregate'
import { sliceColor } from './colors'
import type {
  PlacedEvent,
  RangeStats,
  TimelineEvent,
  TrackDefinition,
  ViewportTransform,
  WorkbenchOptions,
} from './types'
import { eventEnd, eventStart } from './types'
import { buildTracks } from './tracks'

const RULER_HEIGHT = 30
const HEADER_WIDTH = 200
const LANE_HEIGHT = 26
const TRACK_PADDING_Y = 5
const TRACK_GAP = 4
const SLICE_PADDING_Y = 3
const MIN_SLICE_WIDTH = 2

export interface HoverHit {
  event: TimelineEvent
  track: TrackDefinition
  clientX: number
  clientY: number
}

export interface BrushRange {
  startMs: number
  endMs: number
  stats: RangeStats
}

export class TimelineEngine {
  private canvas: HTMLCanvasElement | null = null
  private ctx: CanvasRenderingContext2D | null = null

  private events: TimelineEvent[] = []
  private tracks: TrackDefinition[] = []
  private options: WorkbenchOptions = { showWaits: true, showDeadlines: true, theme: 'light', frameIntervalMs: 33.333 }
  private dataFingerprint = ''

  private transform: ViewportTransform = { startMs: 0, endMs: 66.6, scale: 20, offsetY: 0 }

  private theme: WorkbenchTheme
  private selectedTaskId: string | null = null
  private hovered: HoverHit | null = null

  private isPanning = false
  private isBrushing = false
  private brushMode = false
  private brushAnchorMs = 0
  private brushCursorMs = 0
  private brush: BrushRange | null = null
  private dragStartX = 0
  private dragStartY = 0
  private dragStartMs = 0
  private dragStartOffsetY = 0
  private dragMoved = false

  private animFrameId: number | null = null

  public onSelect?: (taskId: string | null) => void
  public onRange?: (range: BrushRange | null) => void
  public onHover?: (hit: HoverHit | null) => void

  constructor(theme: WorkbenchTheme) {
    this.theme = theme
  }

  public attach(canvas: HTMLCanvasElement): void {
    this.canvas = canvas
    this.ctx = canvas.getContext('2d', { alpha: false })
    this.bindEvents()
    this.resize()
  }

  public detach(): void {
    this.unbindEvents()
    if (this.animFrameId !== null) {
      cancelAnimationFrame(this.animFrameId)
      this.animFrameId = null
    }
    this.canvas = null
    this.ctx = null
  }

  public setTheme(theme: WorkbenchTheme): void {
    this.theme = theme
    this.requestRender()
  }

  public setData(events: TimelineEvent[], options: WorkbenchOptions): void {
    this.events = events ?? []
    this.options = options
    this.tracks = buildTracks(this.events)
    const fingerprint = this.fingerprint(this.events)
    const changed = fingerprint !== this.dataFingerprint
    this.dataFingerprint = fingerprint
    if (changed) {
      this.selectedTaskId = null
      this.brush = null
      this.fitAll()
    } else {
      this.requestRender()
    }
  }

  private fingerprint(events: TimelineEvent[]): string {
    if (!events.length) return 'empty'
    const first = events[0]
    const last = events[events.length - 1]
    const maxEnd = Math.max(...events.map(eventEnd))
    return `${events.length}|${first.task_id}|${last.task_id}|${maxEnd.toFixed(3)}`
  }

  public getSelection(): { selectedTaskId: string | null; brush: BrushRange | null } {
    return { selectedTaskId: this.selectedTaskId, brush: this.brush }
  }

  public contentHeight(): number {
    let height = RULER_HEIGHT
    for (const track of this.tracks) {
      height += this.trackHeight(track) + TRACK_GAP
    }
    return height + 8
  }

  private trackHeight(track: TrackDefinition): number {
    return track.laneCount * LANE_HEIGHT + TRACK_PADDING_Y * 2
  }

  public fitAll(): void {
    if (!this.events.length) {
      this.transform.startMs = 0
      this.transform.endMs = 66.6
    } else {
      const minStart = Math.min(...this.events.map(eventStart))
      let maxEnd = Math.max(...this.events.map(eventEnd))
      for (const event of this.events) {
        if (event.deadline_ms !== undefined && event.deadline_ms !== null) {
          maxEnd = Math.max(maxEnd, event.deadline_ms)
        }
      }
      const paddingMs = Math.max(1, (maxEnd - minStart) * 0.05)
      this.transform.startMs = Math.max(0, minStart - paddingMs)
      this.transform.endMs = maxEnd + paddingMs
    }
    this.transform.offsetY = 0
    this.updateScale()
    this.requestRender()
  }

  public zoomBy(factor: number, centerMs?: number): void {
    if (!this.canvas) return
    const currentSpan = this.transform.endMs - this.transform.startMs
    const targetSpan = Math.min(1e6, Math.max(0.05, currentSpan * factor))
    const focalMs = centerMs ?? this.transform.startMs + currentSpan / 2
    const ratio = (focalMs - this.transform.startMs) / currentSpan
    this.transform.startMs = focalMs - targetSpan * ratio
    this.transform.endMs = this.transform.startMs + targetSpan
    this.updateScale()
    this.requestRender()
  }

  public panBy(deltaMs: number): void {
    this.transform.startMs += deltaMs
    this.transform.endMs += deltaMs
    this.requestRender()
  }

  public setBrushMode(enabled: boolean): void {
    this.brushMode = enabled
  }

  public clearSelection(): void {
    const hadAny = this.selectedTaskId !== null || this.brush !== null
    this.selectedTaskId = null
    this.brush = null
    if (hadAny) {
      this.onSelect?.(null)
      this.onRange?.(null)
    }
    this.requestRender()
  }

  public resize(): void {
    if (!this.canvas) return
    const rect = this.canvas.getBoundingClientRect()
    const dpr = window.devicePixelRatio || 1
    this.canvas.width = Math.max(1, Math.floor(rect.width * dpr))
    this.canvas.height = Math.max(1, Math.floor(rect.height * dpr))
    this.ctx?.setTransform(dpr, 0, 0, dpr, 0, 0)
    this.updateScale()
    this.requestRender()
  }

  private updateScale(): void {
    if (!this.canvas) return
    const width = Math.max(10, this.canvas.getBoundingClientRect().width - HEADER_WIDTH)
    const span = Math.max(0.001, this.transform.endMs - this.transform.startMs)
    this.transform.scale = width / span
  }

  // --- Rendering -------------------------------------------------------------

  public requestRender(): void {
    if (this.animFrameId !== null) return
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

    ctx.fillStyle = this.theme.bgCanvas
    ctx.fillRect(0, 0, width, height)

    this.renderFrameBands(ctx, width, height)
    this.renderTracks(ctx, width, height)
    this.renderBrush(ctx, height)
    this.renderTimeRuler(ctx, width)
    this.renderTrackHeaders(ctx, height)
    this.renderHoverCursor(ctx, height)

    ctx.restore()
  }

  private timeToX(timeMs: number): number {
    return HEADER_WIDTH + (timeMs - this.transform.startMs) * this.transform.scale
  }

  private xToTime(x: number): number {
    return this.transform.startMs + (x - HEADER_WIDTH) / this.transform.scale
  }

  private renderFrameBands(ctx: CanvasRenderingContext2D, width: number, height: number): void {
    const interval = this.options.frameIntervalMs
    if (!interval || interval <= 0) return
    const firstFrame = Math.max(0, Math.floor(this.transform.startMs / interval))
    const lastFrame = Math.ceil(this.transform.endMs / interval)
    if (lastFrame - firstFrame > 400) return

    for (let f = firstFrame; f <= lastFrame; f++) {
      const bandX0 = this.timeToX(f * interval)
      const x0 = Math.max(HEADER_WIDTH, bandX0)
      const x1 = Math.min(width, this.timeToX((f + 1) * interval))
      if (x1 <= HEADER_WIDTH || x0 >= width) continue

      ctx.fillStyle = f % 2 === 0 ? this.theme.frameBandEven : this.theme.frameBandOdd
      ctx.fillRect(x0, RULER_HEIGHT, x1 - x0, height - RULER_HEIGHT)

      if (bandX0 >= HEADER_WIDTH && bandX0 <= width) {
        ctx.strokeStyle = this.theme.borderSubtle
        ctx.lineWidth = 1
        ctx.setLineDash([4, 4])
        ctx.beginPath()
        ctx.moveTo(bandX0, RULER_HEIGHT)
        ctx.lineTo(bandX0, height)
        ctx.stroke()
        ctx.setLineDash([])

        ctx.fillStyle = this.theme.textMuted
        ctx.font = '10px "Segoe UI", sans-serif'
        ctx.fillText(`F${f}`, bandX0 + 5, RULER_HEIGHT + 12)
      }
    }
  }

  private renderTracks(ctx: CanvasRenderingContext2D, width: number, height: number): void {
    let currentY = RULER_HEIGHT + this.transform.offsetY
    for (const track of this.tracks) {
      const trackH = this.trackHeight(track)
      if (currentY + trackH >= RULER_HEIGHT && currentY <= height) {
        ctx.strokeStyle = this.theme.borderSubtle
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.moveTo(HEADER_WIDTH, currentY + trackH)
        ctx.lineTo(width, currentY + trackH)
        ctx.stroke()

        for (const placed of track.placed) {
          this.renderSlice(ctx, placed, currentY, width)
        }
      }
      currentY += trackH + TRACK_GAP
    }
  }

  private renderSlice(
    ctx: CanvasRenderingContext2D,
    placed: PlacedEvent,
    trackY: number,
    canvasWidth: number,
  ): void {
    const event = placed.event
    const sliceY = trackY + TRACK_PADDING_Y + placed.lane * LANE_HEIGHT + SLICE_PADDING_Y
    const sliceH = LANE_HEIGHT - SLICE_PADDING_Y * 2

    const startMs = eventStart(event)
    const endMs = eventEnd(event)
    const x0 = this.timeToX(startMs)
    const x1 = this.timeToX(endMs)
    const sliceW = Math.max(MIN_SLICE_WIDTH, x1 - x0)
    if (x0 > canvasWidth) return

    // Wait segments render before the slice, mirroring the Plotly overlay:
    // token wait at [ready - token_wait, ready), resource wait at [ready, start).
    if (this.options.showWaits) {
      const ready = event.ready_ms
      if (ready !== undefined && ready !== null) {
        const tokenWait = event.token_wait_ms ?? 0
        if (tokenWait > 0) {
          this.renderWaitSegment(ctx, Math.max(0, ready - tokenWait), ready, sliceY, sliceH, this.theme.tokenWait, 'slash')
        }
        const resourceWait = event.resource_wait_ms ?? 0
        if (resourceWait > 0) {
          this.renderWaitSegment(ctx, ready, ready + resourceWait, sliceY, sliceH, this.theme.resourceWait, 'cross')
        }
      }
    }

    if (x1 >= HEADER_WIDTH) {
      const isSelected = this.selectedTaskId !== null && this.selectedTaskId === event.task_id
      ctx.fillStyle = sliceColor(event)
      ctx.beginPath()
      ctx.roundRect(x0, sliceY, sliceW, sliceH, 3)
      ctx.fill()

      if (isSelected) {
        ctx.strokeStyle = this.theme.selectionBorder
        ctx.lineWidth = 2.5
        ctx.stroke()
      } else if (event.critical) {
        ctx.strokeStyle = this.theme.criticalBorder
        ctx.lineWidth = 2
        ctx.stroke()
      }

      if (sliceW > 28) {
        ctx.fillStyle = '#FFFFFF'
        ctx.font = '11px "Segoe UI", sans-serif'
        ctx.save()
        ctx.beginPath()
        ctx.rect(Math.max(HEADER_WIDTH, x0 + 4), sliceY, sliceW - 8, sliceH)
        ctx.clip()
        const label = event.hw_name || event.task_id
        ctx.fillText(label, Math.max(HEADER_WIDTH + 2, x0 + 6), sliceY + sliceH / 2 + 4)
        ctx.restore()
      }
    }

    if (this.options.showDeadlines && event.deadline_ms !== undefined && event.deadline_ms !== null) {
      const deadlineX = this.timeToX(event.deadline_ms)
      if (deadlineX >= HEADER_WIDTH && deadlineX <= canvasWidth) {
        const effectiveSlack = event.cadence_slack_ms ?? event.slack_ms
        const ok = effectiveSlack === undefined || effectiveSlack === null || effectiveSlack >= 0
        ctx.strokeStyle = ok ? this.theme.deadlineMet : this.theme.deadlineViolated
        ctx.lineWidth = 2
        ctx.beginPath()
        ctx.moveTo(deadlineX - 4, sliceY)
        ctx.lineTo(deadlineX + 4, sliceY + sliceH)
        ctx.moveTo(deadlineX + 4, sliceY)
        ctx.lineTo(deadlineX - 4, sliceY + sliceH)
        ctx.stroke()
      }
    }
  }

  private renderWaitSegment(
    ctx: CanvasRenderingContext2D,
    fromMs: number,
    toMs: number,
    sliceY: number,
    sliceH: number,
    color: string,
    hatch: 'slash' | 'cross',
  ): void {
    const x0 = this.timeToX(fromMs)
    const x1 = this.timeToX(toMs)
    const w = x1 - x0
    if (w <= 0 || x1 < HEADER_WIDTH) return

    ctx.save()
    ctx.beginPath()
    ctx.rect(Math.max(HEADER_WIDTH, x0), sliceY, Math.min(x1, this.canvas!.getBoundingClientRect().width) - Math.max(HEADER_WIDTH, x0), sliceH)
    ctx.clip()

    ctx.globalAlpha = 0.35
    ctx.fillStyle = color
    ctx.fillRect(x0, sliceY, w, sliceH)
    ctx.globalAlpha = 0.8
    ctx.strokeStyle = color
    ctx.lineWidth = 1
    const step = 5
    ctx.beginPath()
    for (let x = x0 - sliceH; x < x1; x += step) {
      ctx.moveTo(x, sliceY + sliceH)
      ctx.lineTo(x + sliceH, sliceY)
      if (hatch === 'cross') {
        ctx.moveTo(x, sliceY)
        ctx.lineTo(x + sliceH, sliceY + sliceH)
      }
    }
    ctx.stroke()
    ctx.restore()
  }

  private renderBrush(ctx: CanvasRenderingContext2D, height: number): void {
    let lo: number | null = null
    let hi: number | null = null
    if (this.isBrushing) {
      lo = Math.min(this.brushAnchorMs, this.brushCursorMs)
      hi = Math.max(this.brushAnchorMs, this.brushCursorMs)
    } else if (this.brush) {
      lo = this.brush.startMs
      hi = this.brush.endMs
    }
    if (lo === null || hi === null || hi - lo <= 0) return

    const x0 = Math.max(HEADER_WIDTH, this.timeToX(lo))
    const x1 = this.timeToX(hi)
    if (x1 <= HEADER_WIDTH) return

    ctx.fillStyle = this.theme.brushFill
    ctx.fillRect(x0, RULER_HEIGHT, x1 - x0, height - RULER_HEIGHT)
    ctx.strokeStyle = this.theme.brushBorder
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(x0, RULER_HEIGHT)
    ctx.lineTo(x0, height)
    ctx.moveTo(x1, RULER_HEIGHT)
    ctx.lineTo(x1, height)
    ctx.stroke()
  }

  private renderTimeRuler(ctx: CanvasRenderingContext2D, width: number): void {
    ctx.fillStyle = this.theme.rulerBg
    ctx.fillRect(0, 0, width, RULER_HEIGHT)
    ctx.strokeStyle = this.theme.borderDefault
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(0, RULER_HEIGHT)
    ctx.lineTo(width, RULER_HEIGHT)
    ctx.stroke()

    const spanMs = this.transform.endMs - this.transform.startMs
    const targetTicks = Math.max(4, (width - HEADER_WIDTH) / 110)
    const rawInterval = spanMs / targetTicks
    const magnitude = Math.pow(10, Math.floor(Math.log10(rawInterval)))
    let tickIntervalMs = magnitude
    for (const mult of [1, 2, 2.5, 5, 10]) {
      if (magnitude * mult >= rawInterval) {
        tickIntervalMs = magnitude * mult
        break
      }
    }

    const firstTick = Math.floor(this.transform.startMs / tickIntervalMs) * tickIntervalMs
    ctx.fillStyle = this.theme.textSecondary
    ctx.font = '10px Consolas, monospace'
    for (let t = firstTick; t <= this.transform.endMs + tickIntervalMs; t += tickIntervalMs) {
      const x = this.timeToX(t)
      if (x < HEADER_WIDTH || x > width) continue
      ctx.strokeStyle = this.theme.rulerTick
      ctx.beginPath()
      ctx.moveTo(x, RULER_HEIGHT - 7)
      ctx.lineTo(x, RULER_HEIGHT)
      ctx.stroke()
      const decimals = tickIntervalMs < 1 ? 2 : tickIntervalMs < 10 ? 1 : 0
      ctx.fillText(`${t.toFixed(decimals)} ms`, x + 4, RULER_HEIGHT - 10)
    }
  }

  private renderTrackHeaders(ctx: CanvasRenderingContext2D, height: number): void {
    ctx.fillStyle = this.theme.bgTrackHeader
    ctx.fillRect(0, 0, HEADER_WIDTH, height)
    ctx.strokeStyle = this.theme.borderDefault
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(HEADER_WIDTH, 0)
    ctx.lineTo(HEADER_WIDTH, height)
    ctx.stroke()

    ctx.fillStyle = this.theme.textPrimary
    ctx.font = 'bold 11px "Segoe UI", sans-serif'
    ctx.fillText('Tracks', 12, 19)

    let currentY = RULER_HEIGHT + this.transform.offsetY
    for (const track of this.tracks) {
      const trackH = this.trackHeight(track)
      if (currentY + trackH >= RULER_HEIGHT && currentY <= height) {
        ctx.fillStyle = track.color
        ctx.beginPath()
        ctx.arc(15, currentY + trackH / 2, 4, 0, Math.PI * 2)
        ctx.fill()

        ctx.fillStyle = this.theme.textPrimary
        ctx.font = '500 11px "Segoe UI", sans-serif'
        ctx.save()
        ctx.beginPath()
        ctx.rect(0, currentY, HEADER_WIDTH - 4, trackH)
        ctx.clip()
        ctx.fillText(track.title, 27, currentY + trackH / 2 + 4)
        ctx.restore()

        ctx.fillStyle = this.theme.textMuted
        ctx.font = '10px "Segoe UI", sans-serif'
        const count = `${track.placed.length}`
        ctx.fillText(count, HEADER_WIDTH - 12 - ctx.measureText(count).width, currentY + trackH / 2 + 4)
      }
      currentY += trackH + TRACK_GAP
    }
  }

  private renderHoverCursor(ctx: CanvasRenderingContext2D, height: number): void {
    if (!this.hovered || !this.canvas) return
    const rect = this.canvas.getBoundingClientRect()
    const x = this.hovered.clientX - rect.left
    if (x < HEADER_WIDTH) return
    ctx.strokeStyle = this.theme.hoverCursor
    ctx.lineWidth = 1
    ctx.setLineDash([2, 2])
    ctx.beginPath()
    ctx.moveTo(x, RULER_HEIGHT)
    ctx.lineTo(x, height)
    ctx.stroke()
    ctx.setLineDash([])
  }

  // --- Interaction -----------------------------------------------------------

  private bindEvents(): void {
    if (!this.canvas) return
    this.canvas.addEventListener('mousedown', this.onMouseDown)
    window.addEventListener('mousemove', this.onMouseMove)
    window.addEventListener('mouseup', this.onMouseUp)
    this.canvas.addEventListener('wheel', this.onWheel, { passive: false })
    this.canvas.addEventListener('mouseleave', this.onMouseLeave)
    window.addEventListener('keydown', this.onKeyDown)
  }

  private unbindEvents(): void {
    if (!this.canvas) return
    this.canvas.removeEventListener('mousedown', this.onMouseDown)
    window.removeEventListener('mousemove', this.onMouseMove)
    window.removeEventListener('mouseup', this.onMouseUp)
    this.canvas.removeEventListener('wheel', this.onWheel)
    this.canvas.removeEventListener('mouseleave', this.onMouseLeave)
    window.removeEventListener('keydown', this.onKeyDown)
  }

  private localPos(e: MouseEvent): { x: number; y: number } {
    const rect = this.canvas!.getBoundingClientRect()
    return { x: e.clientX - rect.left, y: e.clientY - rect.top }
  }

  private onMouseDown = (e: MouseEvent): void => {
    if (e.button !== 0 || !this.canvas) return
    const { x, y } = this.localPos(e)
    if ((e.shiftKey || this.brushMode) && x > HEADER_WIDTH) {
      this.isBrushing = true
      this.brushAnchorMs = this.xToTime(x)
      this.brushCursorMs = this.brushAnchorMs
      this.requestRender()
      return
    }
    this.isPanning = true
    this.dragMoved = false
    this.dragStartX = e.clientX
    this.dragStartY = e.clientY
    this.dragStartMs = this.transform.startMs
    this.dragStartOffsetY = this.transform.offsetY
    void y
  }

  private onMouseMove = (e: MouseEvent): void => {
    if (!this.canvas) return
    const { x, y } = this.localPos(e)

    if (this.isBrushing) {
      this.brushCursorMs = this.xToTime(Math.max(HEADER_WIDTH, x))
      this.requestRender()
      return
    }

    if (this.isPanning) {
      const deltaX = e.clientX - this.dragStartX
      const deltaY = e.clientY - this.dragStartY
      if (Math.abs(deltaX) + Math.abs(deltaY) > 3) this.dragMoved = true
      const span = this.transform.endMs - this.transform.startMs
      this.transform.startMs = this.dragStartMs - deltaX / this.transform.scale
      this.transform.endMs = this.transform.startMs + span
      const viewH = this.canvas.getBoundingClientRect().height
      const minOffset = Math.min(0, viewH - this.contentHeight())
      this.transform.offsetY = Math.max(minOffset, Math.min(0, this.dragStartOffsetY + deltaY))
      this.requestRender()
      return
    }

    const hit = this.hitTest(x, y)
    if (hit) {
      this.hovered = { ...hit, clientX: e.clientX, clientY: e.clientY }
      this.canvas.style.cursor = 'pointer'
    } else {
      this.hovered = null
      this.canvas.style.cursor = x > HEADER_WIDTH && y > RULER_HEIGHT ? 'crosshair' : 'default'
    }
    this.onHover?.(this.hovered)
    this.requestRender()
  }

  private onMouseUp = (e: MouseEvent): void => {
    if (this.isBrushing) {
      this.isBrushing = false
      const lo = Math.min(this.brushAnchorMs, this.brushCursorMs)
      const hi = Math.max(this.brushAnchorMs, this.brushCursorMs)
      const spanPx = (hi - lo) * this.transform.scale
      if (spanPx >= 4) {
        this.brush = { startMs: lo, endMs: hi, stats: rangeStats(this.events, lo, hi) }
      } else {
        this.brush = null
      }
      this.onRange?.(this.brush)
      this.requestRender()
      return
    }
    if (this.isPanning) {
      this.isPanning = false
      if (!this.dragMoved && this.canvas) {
        const { x, y } = this.localPos(e)
        const hit = this.hitTest(x, y)
        const next = hit ? hit.event.task_id : null
        if (x > HEADER_WIDTH && y > RULER_HEIGHT && next !== this.selectedTaskId) {
          this.selectedTaskId = next
          this.onSelect?.(next)
        }
        this.requestRender()
      }
    }
  }

  private onMouseLeave = (): void => {
    this.hovered = null
    this.onHover?.(null)
    this.requestRender()
  }

  private onWheel = (e: WheelEvent): void => {
    e.preventDefault()
    if (!this.canvas) return
    const { x } = this.localPos(e)
    const centerMs = this.xToTime(Math.max(HEADER_WIDTH, x))
    const zoomFactor = e.deltaY > 0 ? 1.18 : 0.85
    this.zoomBy(zoomFactor, centerMs)
  }

  private onKeyDown = (e: KeyboardEvent): void => {
    const tag = (e.target as HTMLElement | null)?.tagName
    if (tag && ['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) return

    const span = this.transform.endMs - this.transform.startMs
    switch (e.key.toLowerCase()) {
      case 'w':
        this.zoomBy(0.8)
        break
      case 's':
        this.zoomBy(1.25)
        break
      case 'a':
        this.panBy(-span * 0.1)
        break
      case 'd':
        this.panBy(span * 0.1)
        break
      case 'f':
        this.fitAll()
        break
      case 'escape':
        this.clearSelection()
        break
    }
  }

  private hitTest(x: number, y: number): { event: TimelineEvent; track: TrackDefinition } | null {
    if (x < HEADER_WIDTH || y < RULER_HEIGHT) return null
    let currentY = RULER_HEIGHT + this.transform.offsetY
    for (const track of this.tracks) {
      const trackH = this.trackHeight(track)
      if (y >= currentY && y <= currentY + trackH) {
        const lane = Math.floor((y - currentY - TRACK_PADDING_Y) / LANE_HEIGHT)
        for (const placed of track.placed) {
          if (placed.lane !== lane) continue
          const x0 = this.timeToX(eventStart(placed.event))
          const x1 = Math.max(x0 + MIN_SLICE_WIDTH, this.timeToX(eventEnd(placed.event)))
          if (x >= x0 && x <= x1) {
            return { event: placed.event, track }
          }
        }
        return null
      }
      currentY += trackH + TRACK_GAP
    }
    return null
  }
}
