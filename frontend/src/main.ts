import { initBridge, setComponentValue, setFrameHeight } from './bridge/streamlitBridge'
import { DiagramPane } from './diagram/DiagramPane'
import type { DiagramGraph } from './diagram/mapping'
import { eventsForDiagramNode, matchDiagramNode } from './diagram/mapping'
import type { BrushRange, HoverHit } from './engine/TimelineEngine'
import { TimelineEngine } from './engine/TimelineEngine'
import { formatMs } from './engine/format'
import type { DiagramExpandRequest, SelectionState, TimelineEvent, WorkbenchOptions } from './engine/types'
import { themeByName } from './theme'
import {outputMetrics} from './engine/pilotMetrics'
import {sliceColor} from './engine/colors'

const MIN_HEIGHT = 420
const MAX_HEIGHT = 900
const CHROME_HEIGHT = 74 // toolbar + footer + borders

const canvas = document.getElementById('wb-canvas') as HTMLCanvasElement
const canvasWrap = document.getElementById('wb-canvas-wrap') as HTMLDivElement
const tooltip = document.getElementById('wb-tooltip') as HTMLDivElement
const footer = document.getElementById('wb-footer') as HTMLDivElement

let themeName = 'light'
let pilot = false
let pilotKey = ''
let pilotView = 'split'
let pilotEvents: TimelineEvent[] = []
let pilotOptions: WorkbenchOptions
let selectedFrame = ''
let onlyFrame = false
let selectedGroup = ''
const engine = new TimelineEngine(themeByName(themeName))
engine.attach(canvas)

const selection: SelectionState = {
  selectedTaskId: null,
  rangeStartMs: null,
  rangeEndMs: null,
  rangeStats: null,
}

let diagramExpand: DiagramExpandRequest = { node: null, seq: 0 }

function reportSelection(): void {
  if (pilot) { savePilot(); return }
  setComponentValue({ ...selection, diagramExpand: { ...diagramExpand } })
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

// --- Diagram pane (cross-probe) --------------------------------------------
const diagramContainer = document.getElementById('wb-diagram') as HTMLDivElement
const diagramToggle = document.getElementById('wb-diagram-toggle') as HTMLButtonElement | null
const diagramPane = new DiagramPane(diagramContainer, themeByName(themeName))
let diagramGraph: DiagramGraph = { nodes: [], edges: [] }
let diagramOpen = false
let diagramLoaded = false

function openDiagram(open: boolean): void {
  diagramOpen = open
  diagramContainer.classList.toggle('wb-open', open)
  diagramToggle?.classList.toggle('wb-active', open)
  if (open && !diagramLoaded) {
    diagramLoaded = true
    void diagramPane.setGraph(diagramGraph, drillNode)
  }
  engine.resize()
}

diagramToggle?.addEventListener('click', () => openDiagram(!diagramOpen))

diagramPane.onNodeClick = (node) => {
  const events = eventsForDiagramNode(engine.getEvents(), node.id, node.label)
  engine.setHighlightedTaskIds(new Set(events.map((event) => event.task_id)))
  diagramPane.highlightNode(node.id)
  if (events.length && !pilot) engine.jumpToEvent(events[0])
  if (pilot) {
    selection.selectedTaskId = events[0]?.task_id ?? null
    footer.textContent = events.length ? `${node.label} · ${events.length} events · 선택에 맞춤으로 이동` : `${node.label} · 이 시간창에 대응 이벤트 없음`
    savePilot()
  }
}

// Semantic zoom: double-click drills into the block's module detail
// (fulfilled by Python on the next rerun); Back returns to the topology.
let drillNode: string | null = null
diagramPane.onNodeDblClick = (node) => {
  if (pilot) return
  if (drillNode || node.type === 'buffer') return
  diagramExpand = { node: node.id, seq: Date.now() }
  reportSelection()
}
diagramPane.onBack = () => {
  diagramExpand = { node: null, seq: Date.now() }
  reportSelection()
}

engine.onSelect = (taskId: string | null) => {
  selection.selectedTaskId = taskId
  footer.innerHTML = describeSelection()
  reportSelection()
  // Timeline -> diagram probe: light up the node the slice runs on.
  if (!taskId) {
    diagramPane.highlightNode(null)
    engine.setHighlightedTaskIds(null)
  } else {
    const event = engine.getEvents().find((item) => item.task_id === taskId)
    diagramPane.highlightNode(event ? matchDiagramNode(diagramGraph.nodes, event) : null)
    if (pilot && event) {
      selectedFrame = String(event.frame_index ?? '')
      const frameControl = document.getElementById('pilot-frame') as HTMLSelectElement
      frameControl.value = selectedFrame
      engine.setHighlightedTaskIds(new Set(engine.getEvents().filter(e => e.frame_index === event.frame_index).map(e => e.task_id)))
      footer.textContent = `${event.display_name || event.task_id} · ${formatMs(event.start_ms)} → ${formatMs(event.end_ms)} · duration ${formatMs(event.duration_ms)}${event.observation_only ? ' · 관측 전용 (구조도 매핑 없음)' : ''}`
      savePilot()
    }
  }
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
  const baseline = engine.getBaselineFor(e.task_id)
  if (baseline) {
    const deltaStart = (e.start_ms ?? 0) - baseline.start
    const currentDuration = (e.end_ms ?? e.start_ms ?? 0) - (e.start_ms ?? 0)
    const deltaDuration = currentDuration - (baseline.end - baseline.start)
    lines.push(`baseline: ${formatMs(baseline.start)} - ${formatMs(baseline.end)}`)
    lines.push(`Δstart: ${deltaStart >= 0 ? '+' : ''}${deltaStart.toFixed(3)} ms · Δdur: ${deltaDuration >= 0 ? '+' : ''}${deltaDuration.toFixed(3)} ms`)
  }
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

document.getElementById('wb-fit')?.addEventListener('click', () => {engine.fitAll(); if(pilot) diagramPane.fit()})
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
  pilot = args.pilot === true
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
    pilot,
    showWaits: rawOptions.showWaits ?? true,
    showDeadlines: rawOptions.showDeadlines ?? true,
    theme: nextTheme === 'dark' ? 'dark' : 'light',
    frameIntervalMs: Number(rawOptions.frameIntervalMs) > 0 ? Number(rawOptions.frameIntervalMs) : 33.333,
  }
  const events = (Array.isArray(args.events) ? args.events : []) as TimelineEvent[]
  exportName = String(args.exportName || 'timeline')
  engine.setData(events, options)
  const baselineEvents = (Array.isArray(args.baselineEvents) ? args.baselineEvents : null) as TimelineEvent[] | null
  engine.setBaseline(baselineEvents)
  const hint = document.getElementById('wb-hint')
  if (hint) {
    const baselineName = String(args.baselineName || '')
    hint.textContent = baselineName
      ? `A/B vs ${baselineName} (ghost bars = baseline)`
      : 'drag pan · wheel zoom · shift+drag select · click slice = flows · F fit · Esc clear'
  }

  const rawGraph = args.graph as DiagramGraph | undefined
  diagramGraph = rawGraph && Array.isArray(rawGraph.nodes) ? rawGraph : { nodes: [], edges: [] }
  if (pilot) diagramGraph = {...diagramGraph, interactionHint:'휠 확대·축소 · 빈 공간 드래그 이동 · 클릭 상세', nodes: diagramGraph.nodes.map(node => {
    const event = eventsForDiagramNode(events,node.id,node.label)[0]
    return {...node,color:event ? sliceColor(event) : undefined}
  })}
  drillNode = typeof args.drillNode === 'string' && args.drillNode ? args.drillNode : null
  if (drillNode) {
    diagramExpand = { node: drillNode, seq: diagramExpand.seq }
    if (!diagramOpen) openDiagram(true)
  }
  if (diagramToggle) diagramToggle.hidden = !diagramGraph.nodes.length
  diagramPane.setTheme(themeByName(themeName))
  if (diagramLoaded) {
    void diagramPane.setGraph(diagramGraph, drillNode)
  }
  if (pilot) configurePilot(args, events, options)

  // Data change resets client selection; keep footer in sync.
  const current = engine.getSelection()
  selection.selectedTaskId = current.selectedTaskId
  selection.rangeStartMs = current.brush ? current.brush.startMs : null
  selection.rangeEndMs = current.brush ? current.brush.endMs : null
  selection.rangeStats = current.brush ? current.brush.stats : null
  footer.innerHTML = describeSelection()

  const desired = pilot ? 940 : Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, engine.contentHeight() + CHROME_HEIGHT))
  setFrameHeight(desired)
  requestAnimationFrame(() => engine.resize())
})

function savePilot(): void {
  if (!pilotKey) return
  try { localStorage.setItem(pilotKey, JSON.stringify({view: pilotView, frame: selectedFrame,
    viewport: engine.viewport(), task: selection.selectedTaskId, only: onlyFrame, group: selectedGroup,
    width: diagramContainer.style.flexBasis})) } catch { /* storage may be disabled */ }
}
function setPilotView(view: string): void {
  pilotView = ['split','diagram','timing'].includes(view) ? view : 'split'
  document.getElementById('wb-body')!.dataset.view = pilotView
  openDiagram(pilotView !== 'timing')
  canvasWrap.hidden = pilotView === 'diagram'
  document.querySelectorAll<HTMLButtonElement>('[data-pilot-view]').forEach(b => {
    const active = b.dataset.pilotView === pilotView
    b.classList.toggle('wb-active',active); b.setAttribute('aria-pressed',String(active))
  })
  engine.resize(); savePilot()
}
function filterPilot(): void {
  const filtered = pilotEvents.filter(e => (!onlyFrame || !selectedFrame || String(e.frame_index) === selectedFrame)
    && (!selectedGroup || e.track_name?.includes(` / ${selectedGroup} / `)))
  engine.setData(filtered,pilotOptions)
  engine.setHighlightedTaskIds(selectedFrame ? new Set(filtered.filter(e => String(e.frame_index) === selectedFrame).map(e=>e.task_id)) : null)
  if (selectedFrame) {
    const candidates=filtered.filter(e=>String(e.frame_index)===selectedFrame)
    const target=candidates.find(e=>e.task_id===selection.selectedTaskId) || candidates.find(e=>e.node_id==='sensor_rear') || candidates[0]
    engine.selectTask(target?.task_id ?? null)
  } else engine.selectTask(null)
  savePilot()
}
function configurePilot(args: Record<string, unknown>, events: TimelineEvent[], options: WorkbenchOptions): void {
  document.getElementById('workbench-root')!.classList.add('pilot')
  pilotEvents = events; pilotOptions = options
  const key = String(args.stateKey)
  if (document.getElementById('pilot-controls') === null) {
    const controls = document.createElement('div'); controls.id = 'pilot-controls'
    controls.innerHTML = `<button data-pilot-view="diagram">구조도</button><button data-pilot-view="timing">Timing</button><button data-pilot-view="split">나란히</button><button id="pilot-close">Timing 닫기 ×</button><label>Frame <select id="pilot-frame" aria-label="Frame"><option value="">전체</option></select></label><label><input type="checkbox" id="pilot-only">선택 frame만</label><label>Track <select id="pilot-group" aria-label="Track 그룹"><option value="">전체</option>${['SW','SENSOR','RT','NRT','M2M'].map(g=>`<option>${g}</option>`).join('')}</select></label><button id="pilot-fit">선택에 맞춤</button><label>출력 <select id="pilot-output" aria-label="출력 기준"><option value="gdc_o">Video GDC</option><option value="gdc_m">Preview GDC</option></select></label><span id="pilot-metrics"></span>`
    document.getElementById('workbench-root')!.prepend(controls)
    controls.querySelectorAll<HTMLButtonElement>('[data-pilot-view]').forEach(b => b.onclick = () => setPilotView(b.dataset.pilotView!))
    document.getElementById('pilot-close')!.onclick = () => setPilotView('diagram')
    document.getElementById('pilot-fit')!.onclick = () => {
      const event = engine.getEvents().find(e=>e.task_id===selection.selectedTaskId) || engine.getEvents().find(e=>String(e.frame_index)===selectedFrame)
      if (event) engine.jumpToEvent(event); else engine.fitAll()
      savePilot()
    }
    const frame = document.getElementById('pilot-frame') as HTMLSelectElement
    frame.onchange = () => {selectedFrame=frame.value; filterPilot()}
    const only = document.getElementById('pilot-only') as HTMLInputElement
    only.onchange = () => {onlyFrame=only.checked; filterPilot()}
    const group = document.getElementById('pilot-group') as HTMLSelectElement
    group.onchange = () => {selectedGroup=group.value; filterPilot()}
    document.getElementById('pilot-output')!.onchange = updatePilotMetrics
    canvas.addEventListener('pointerup',()=>setTimeout(savePilot,0))
    canvas.addEventListener('wheel',()=>setTimeout(savePilot,100),{passive:true})
    document.getElementById('wb-toolbar')!.addEventListener('click',()=>setTimeout(savePilot,0))
    const splitter = document.createElement('div'); splitter.id = 'pilot-splitter'; splitter.tabIndex=0
    splitter.setAttribute('role','separator'); splitter.setAttribute('aria-label','구조도 폭'); splitter.setAttribute('aria-orientation','vertical')
    document.getElementById('wb-body')!.append(splitter)
    const width = (percent:number) => {diagramContainer.style.flexBasis=`${Math.max(25,Math.min(65,percent))}%`; engine.resize();savePilot()}
    splitter.onpointerdown = e => {splitter.setPointerCapture(e.pointerId); splitter.onpointermove=move=> {
      const r=document.getElementById('wb-body')!.getBoundingClientRect(); width((move.clientX-r.left)/r.width*100)
    }}
    splitter.onpointerup = () => {splitter.onpointermove=null}
    splitter.onkeydown = e => {if(e.key==='ArrowLeft'||e.key==='ArrowRight') {e.preventDefault();width(parseFloat(diagramContainer.style.flexBasis||'40')+(e.key==='ArrowLeft'?-5:5))}}
  }
  if (key !== pilotKey) {
    pilotKey=key; selectedFrame=''; onlyFrame=false; selectedGroup=''; pilotView='split'
    const frame=document.getElementById('pilot-frame') as HTMLSelectElement
    frame.replaceChildren(new Option('전체',''),... [...new Set(events.map(e=>e.frame_index).filter(f=>f!==undefined))].sort((a,b)=>a!-b!).map(f=>new Option(`f${String(f).padStart(4,'0')}`,String(f))))
    let saved: Record<string, any> = {}
    try {saved=JSON.parse(localStorage.getItem(key)||'{}')} catch { /* fresh state */ }
    selectedFrame=String(saved.frame||''); onlyFrame=Boolean(saved.only); selectedGroup=String(saved.group||'')
    frame.value=selectedFrame
    ;(document.getElementById('pilot-only') as HTMLInputElement).checked=onlyFrame
    ;(document.getElementById('pilot-group') as HTMLSelectElement).value=selectedGroup
    diagramContainer.style.flexBasis=saved.width||'40%'
    filterPilot(); setPilotView(saved.view||'split')
    if(saved.viewport) engine.restoreViewport(saved.viewport)
    selection.selectedTaskId=saved.task||null
    const selected=events.find(e=>e.task_id===selection.selectedTaskId)
    diagramPane.highlightNode(selected?matchDiagramNode(diagramGraph.nodes,selected):null)
    if (selected) engine.selectTask(selected.task_id)
  }
  updatePilotMetrics()
}
function updatePilotMetrics(): void {
  const node=(document.getElementById('pilot-output') as HTMLSelectElement).value
  const m=outputMetrics(pilotEvents,node)
  document.getElementById('pilot-metrics')!.textContent=`출력 간격 ${formatMs(m.interval)} · Frame latency ${formatMs(m.latency)} · 완료 ${m.outputs} · 미대응 ${m.unpaired} (창 경계 포함, drop 판정 아님)`
}
