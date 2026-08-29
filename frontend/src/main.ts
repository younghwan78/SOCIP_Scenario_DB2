import { initBridge, setComponentValue, setFrameHeight } from './bridge/streamlitBridge'
import type { BrushRange, HoverHit } from './engine/TimelineEngine'
import { TimelineEngine } from './engine/TimelineEngine'
import { formatMs } from './engine/format'
import type { SelectionState, TimelineEvent, WorkbenchOptions } from './engine/types'
import { themeByName } from './theme'

const MIN_HEIGHT = 420
const MAX_HEIGHT = 900
const CHROME_HEIGHT = 74 // toolbar + footer + borders

const canvas = document.getElementById('wb-canvas') as HTMLCanvasElement
const canvasWrap = document.getElementById('wb-canvas-wrap') as HTMLDivElement
const tooltip = document.getElementById('wb-tooltip') as HTMLDivElement
const footer = document.getElementById('wb-footer') as HTMLDivElement

let themeName = 'light'
const engine = new TimelineEngine(themeByName(themeName))
engine.attach(canvas)

const selection: SelectionState = {
  selectedTaskId: null,
  rangeStartMs: null,
  rangeEndMs: null,
  rangeStats: null,
}

function reportSelection(): void {
  setComponentValue({ ...selection })
}

function describeSelection(): string {
  const parts: string[] = []
  if (selection.selectedTaskId) {
    parts.push(`task <span class="wb-stat">${escapeHtml(selection.selectedTaskId)}</span>`)
  }
  if (selection.rangeStartMs !== null && selection.rangeEndMs !== null && selection.rangeStats) {
    const s = selection.rangeStats
    parts.push(
      `range <span class="wb-stat">${formatMs(selection.rangeStartMs)} - ${formatMs(selection.rangeEndMs)}</span>` +
        ` &middot; ${s.eventCount} events` +
        ` &middot; busy <span class="wb-stat">${formatMs(s.busyMs)}</span>` +
        ` &middot; res wait ${formatMs(s.resourceWaitMs)}` +
        ` &middot; token wait ${formatMs(s.tokenWaitMs)}` +
        ` &middot; ${s.criticalCount} critical`,
    )
  }
  return parts.length ? parts.join(' &nbsp;|&nbsp; ') : 'No selection'
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

engine.onSelect = (taskId: string | null) => {
  selection.selectedTaskId = taskId
  footer.innerHTML = describeSelection()
  reportSelection()
}

engine.onRange = (range: BrushRange | null) => {
  selection.rangeStartMs = range ? range.startMs : null
  selection.rangeEndMs = range ? range.endMs : null
  selection.rangeStats = range ? range.stats : null
  footer.innerHTML = describeSelection()
  reportSelection()
}

engine.onHover = (hit: HoverHit | null) => {
  if (!hit) {
    tooltip.style.display = 'none'
    return
  }
  const e = hit.event
  const lines = [
    `task: ${e.task_id}`,
    `node: ${e.node_id ?? '-'}`,
    `type: ${e.task_type ?? e.constraint_type ?? '-'}`,
    `edge: ${e.edge_type ?? '-'}`,
    `otf_group: ${e.otf_group_id ?? '-'}`,
    `frame: ${e.frame_index ?? '-'}`,
    `start: ${formatMs(e.start_ms)}`,
    `end: ${formatMs(e.end_ms)}`,
    `duration: ${formatMs(e.duration_ms)}`,
    `ready: ${formatMs(e.ready_ms)}`,
    `resource_wait: ${formatMs(e.resource_wait_ms)}`,
    `token_wait: ${formatMs(e.token_wait_ms)}`,
    `deadline: ${formatMs(e.deadline_ms)}`,
    `slack: ${formatMs(e.slack_ms)}`,
    `cadence_avg: ${formatMs(e.cadence_avg_interval_ms)}`,
    `cadence_budget: ${formatMs(e.cadence_budget_ms)}`,
    `cadence_slack: ${formatMs(e.cadence_slack_ms)}`,
    `bottleneck: ${e.bottleneck_reason ?? '-'}`,
  ]
  tooltip.textContent = lines.join('\n')
  tooltip.style.display = 'block'

  const wrapRect = canvasWrap.getBoundingClientRect()
  const tipRect = tooltip.getBoundingClientRect()
  let left = hit.clientX - wrapRect.left + 14
  let top = hit.clientY - wrapRect.top + 14
  if (left + tipRect.width > wrapRect.width - 8) left = Math.max(8, hit.clientX - wrapRect.left - tipRect.width - 14)
  if (top + tipRect.height > wrapRect.height - 8) top = Math.max(8, wrapRect.height - tipRect.height - 8)
  tooltip.style.left = `${left}px`
  tooltip.style.top = `${top}px`
}

document.getElementById('wb-fit')?.addEventListener('click', () => engine.fitAll())
document.getElementById('wb-zoom-in')?.addEventListener('click', () => engine.zoomBy(0.8))
document.getElementById('wb-zoom-out')?.addEventListener('click', () => engine.zoomBy(1.25))

const selectButton = document.getElementById('wb-select')
let brushMode = false
selectButton?.addEventListener('click', () => {
  brushMode = !brushMode
  engine.setBrushMode(brushMode)
  selectButton.classList.toggle('wb-active', brushMode)
})

const flowsButton = document.getElementById('wb-flows')
let showFlows = false
flowsButton?.addEventListener('click', () => {
  showFlows = !showFlows
  engine.setShowCriticalFlows(showFlows)
  flowsButton.classList.toggle('wb-active', showFlows)
})

let exportName = 'timeline'
document.getElementById('wb-png')?.addEventListener('click', () => {
  // The backing store is devicePixelRatio-scaled, so the PNG comes out at
  // full rendering resolution.
  const link = document.createElement('a')
  link.href = canvas.toDataURL('image/png')
  link.download = `${exportName}.png`
  link.click()
})

const searchInput = document.getElementById('wb-search') as HTMLInputElement | null
const searchCount = document.getElementById('wb-search-count')
searchInput?.addEventListener('keydown', (evt) => {
  if (evt.key !== 'Enter') return
  evt.preventDefault()
  const result = engine.searchJump(searchInput.value)
  if (searchCount) {
    searchCount.textContent = result.total ? `${result.index + 1}/${result.total}` : searchInput.value.trim() ? '0/0' : ''
  }
})

new ResizeObserver(() => engine.resize()).observe(canvasWrap)

initBridge((args) => {
  const nextTheme = String((args.options as Record<string, unknown> | undefined)?.theme ?? 'light')
  if (nextTheme !== themeName) {
    themeName = nextTheme
  }
  const theme = themeByName(themeName)
  engine.setTheme(theme)
  for (const [name, value] of Object.entries(theme.cssVars)) {
    document.documentElement.style.setProperty(name, value)
  }

  const rawOptions = (args.options ?? {}) as Partial<WorkbenchOptions>
  const options: WorkbenchOptions = {
    showWaits: rawOptions.showWaits ?? true,
    showDeadlines: rawOptions.showDeadlines ?? true,
    theme: nextTheme === 'dark' ? 'dark' : 'light',
    frameIntervalMs: Number(rawOptions.frameIntervalMs) > 0 ? Number(rawOptions.frameIntervalMs) : 33.333,
  }
  const events = (Array.isArray(args.events) ? args.events : []) as TimelineEvent[]
  exportName = String(args.exportName || 'timeline')
  engine.setData(events, options)

  // Data change resets client selection; keep footer in sync.
  const current = engine.getSelection()
  selection.selectedTaskId = current.selectedTaskId
  selection.rangeStartMs = current.brush ? current.brush.startMs : null
  selection.rangeEndMs = current.brush ? current.brush.endMs : null
  selection.rangeStats = current.brush ? current.brush.stats : null
  footer.innerHTML = describeSelection()

  const desired = Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, engine.contentHeight() + CHROME_HEIGHT))
  setFrameHeight(desired)
  requestAnimationFrame(() => engine.resize())
})
