// Compact topology pane for the Scenario Workbench: lays the pipeline graph
// out with ELK (loaded from the Streamlit static route) and renders it as
// SVG with click/highlight hooks for timeline cross-probing.
//
// This is deliberately a minimal renderer — the full-featured diagram stays
// in the Pipeline Viewer; this pane exists so time and topology can be read
// side by side with a shared selection.
import type { WorkbenchTheme } from '../theme'
import type { DiagramGraph, DiagramNode } from './mapping'
import { pilotLayout } from './pilotLayout'

declare global {
  interface Window {
    ELK?: new () => { layout(graph: object): Promise<LayoutNode> }
  }
}

interface LayoutNode {
  id: string
  x?: number
  y?: number
  width?: number
  height?: number
  children?: LayoutNode[]
  edges?: LayoutEdge[]
}

interface LayoutEdge {
  id: string
  sections?: Array<{
    startPoint: { x: number; y: number }
    bendPoints?: Array<{ x: number; y: number }>
    endPoint: { x: number; y: number }
  }>
}

const NODE_FILLS: Record<string, [string, string]> = {
  buffer: ['#E8F1EF', '#2F6F68'],
  sw: ['#EDE9FE', '#7C3AED'],
  ip: ['#FEF3E8', '#EA580C'],
  default: ['#F1F5F9', '#64748B'],
}

const EDGE_COLORS: Record<string, string> = {
  OTF: '#2563EB',
  vOTF: '#0D9488',
  M2M: '#F97316',
  control: '#CA8A04',
  risk: '#EF4444',
}

const SVG_NS = 'http://www.w3.org/2000/svg'

export class DiagramPane {
  private container: HTMLElement
  private graph: DiagramGraph = { nodes: [], edges: [] }
  private nodeRects = new Map<string, SVGRectElement>()
  private highlightedId: string | null = null
  private theme: WorkbenchTheme
  private svg: SVGSVGElement | null = null
  private fullBox = {x:0,y:0,width:1,height:1}

  public onNodeClick?: (node: DiagramNode) => void
  public onNodeDblClick?: (node: DiagramNode) => void
  public onBack?: () => void
  private drillLabel: string | null = null

  constructor(container: HTMLElement, theme: WorkbenchTheme) {
    this.container = container
    this.theme = theme
  }

  public setTheme(theme: WorkbenchTheme): void {
    this.theme = theme
  }

  public available(): boolean {
    return typeof window.ELK === 'function'
  }

  public async setGraph(graph: DiagramGraph, drillLabel: string | null = null): Promise<void> {
    this.graph = graph
    this.drillLabel = drillLabel
    this.container.innerHTML = ''
    this.nodeRects.clear()
    this.renderHeader()
    if (!graph.nodes.length) {
      this.showMessage('No topology data for this evidence.')
      return
    }
    if (graph.pilotLayout) {
      this.renderLayout(pilotLayout(graph))
      return
    }
    if (!this.available()) {
      this.showMessage('Diagram runtime unavailable (elk.bundled.js not served).')
      return
    }
    try {
      const layout = await new window.ELK!().layout(this.buildElkGraph(graph))
      this.renderLayout(layout)
    } catch (err) {
      this.showMessage(`Diagram layout failed: ${err instanceof Error ? err.message : err}`)
    }
  }

  // Semantic-zoom breadcrumb: shows where we are and offers the way back.
  private renderHeader(): void {
    const header = document.createElement('div')
    header.className = 'wb-diagram-header'
    if (this.drillLabel) {
      const back = document.createElement('button')
      back.className = 'wb-diagram-back'
      back.textContent = '← Topology'
      back.addEventListener('click', () => this.onBack?.())
      header.appendChild(back)
      const crumb = document.createElement('span')
      crumb.textContent = this.drillLabel
      header.appendChild(crumb)
    } else {
      const hint = document.createElement('span')
      hint.textContent = this.graph.interactionHint || 'Topology · double-click a block for module detail'
      header.appendChild(hint)
    }
    if (this.graph.pilotLayout) {
      for (const [label, factor] of [['−',1.25],['+',0.8],['전체',0]] as const) {
        const button=document.createElement('button')
        button.textContent=label; button.type='button'
        button.setAttribute('aria-label', factor===0 ? '구조도 전체 맞춤' : factor<1 ? '구조도 확대' : '구조도 축소')
        button.onclick=()=>factor===0 ? this.fit() : this.zoom(factor)
        header.append(button)
      }
    }
    this.container.appendChild(header)
  }

  public fit(): void {
    if (this.svg) this.svg.setAttribute('viewBox', `${this.fullBox.x} ${this.fullBox.y} ${this.fullBox.width} ${this.fullBox.height}`)
  }

  private zoom(factor:number, anchor?:DOMPoint): void {
    if (!this.svg) return
    const v=this.svg.viewBox.baseVal
    const width=Math.max(this.fullBox.width/8,Math.min(this.fullBox.width*1.5,v.width*factor))
    const ratio=width/v.width, p=anchor || new DOMPoint(v.x+v.width/2,v.y+v.height/2)
    this.svg.setAttribute('viewBox',`${p.x-(p.x-v.x)*ratio} ${p.y-(p.y-v.y)*ratio} ${width} ${v.height*ratio}`)
  }

  private showMessage(text: string): void {
    const message = document.createElement('div')
    message.className = 'wb-diagram-message'
    message.textContent = text
    this.container.appendChild(message)
  }

  private buildElkGraph(graph: DiagramGraph) {
    return {
      id: 'root',
      layoutOptions: {
        'elk.algorithm': 'layered',
        'elk.direction': 'DOWN',
        'elk.edgeRouting': 'ORTHOGONAL',
        'elk.spacing.nodeNode': '18',
        'elk.layered.spacing.nodeNodeBetweenLayers': '26',
      },
      children: graph.nodes.map((node) => ({
        id: node.id,
        width: Math.max(84, node.label.length * 6.4 + 22),
        height: node.type === 'buffer' ? 30 : 34,
      })),
      edges: graph.edges.map((edge) => ({
        id: edge.id,
        sources: [edge.source],
        targets: [edge.target],
      })),
    }
  }

  private renderLayout(layout: LayoutNode): void {
    const width = Math.ceil((layout.width ?? 300) + 24)
    const height = Math.ceil((layout.height ?? 300) + 24)
    const svg = document.createElementNS(SVG_NS, 'svg')
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`)
    svg.setAttribute('class', 'wb-diagram-svg')
    this.svg=svg; this.fullBox={x:0,y:0,width,height}
    if (this.graph.pilotLayout) {
      svg.style.touchAction='none'
      svg.addEventListener('wheel', e=>{
        e.preventDefault()
        const matrix=svg.getScreenCTM()
        if(matrix) this.zoom(e.deltaY>0?1.18:0.85,new DOMPoint(e.clientX,e.clientY).matrixTransform(matrix.inverse()))
      },{passive:false})
      let drag: {x:number;y:number;box:{x:number;y:number;width:number;height:number};scaleX:number;scaleY:number} | null=null
      svg.addEventListener('pointerdown',e=>{
        if(e.button!==0 || (e.target as Element).closest('.wb-diagram-node')) return
        const v=svg.viewBox.baseVal, m=svg.getScreenCTM()
        if(!m) return
        drag={x:e.clientX,y:e.clientY,box:{x:v.x,y:v.y,width:v.width,height:v.height},scaleX:m.a,scaleY:m.d}
        svg.setPointerCapture(e.pointerId);svg.style.cursor='grabbing'
      })
      svg.addEventListener('pointermove',e=>{
        if(!drag) return
        const {box}=drag
        svg.setAttribute('viewBox',`${box.x-(e.clientX-drag.x)/drag.scaleX} ${box.y-(e.clientY-drag.y)/drag.scaleY} ${box.width} ${box.height}`)
      })
      const stop=()=>{drag=null;svg.style.cursor='grab'}
      svg.addEventListener('pointerup',stop);svg.addEventListener('pointercancel',stop)
      svg.style.cursor='grab'
    }

    const root = document.createElementNS(SVG_NS, 'g')
    root.setAttribute('transform', 'translate(12,12)')
    svg.appendChild(root)
    if (this.graph.pilotLayout) {
      for (const [x, y, text] of [[240, 15, 'SW'], [360, 15, 'HW'], [40, 110, 'RT · OTF'], [500, 238, 'RT → NRT buffers'], [40, 450, 'NRT · OTF'], [500, 518, 'NRT output buffers']] as const) {
        const label = document.createElementNS(SVG_NS, 'text')
        label.setAttribute('x', String(x)); label.setAttribute('y', String(y*1.16))
        label.setAttribute('fill', '#607d8b'); label.setAttribute('font-size', '11')
        label.textContent = text; root.appendChild(label)
      }
    }

    const edgeById = new Map(this.graph.edges.map((edge) => [edge.id, edge]))
    for (const edge of layout.edges ?? []) {
      const data = edgeById.get(edge.id)
      const color = EDGE_COLORS[data?.flow_type ?? ''] ?? '#94A3B8'
      for (const section of edge.sections ?? []) {
        const points = [section.startPoint, ...(section.bendPoints ?? []), section.endPoint]
        const path = document.createElementNS(SVG_NS, 'path')
        path.setAttribute('data-edge-id', edge.id)
        path.setAttribute('d', points.map((p, i) => `${i ? 'L' : 'M'}${p.x},${p.y}`).join(' '))
        path.setAttribute('fill', 'none')
        path.setAttribute('stroke', color)
        path.setAttribute('stroke-width', data?.flow_type === 'OTF' ? '2' : '1.6')
        if (data?.flow_type === 'M2M' || data?.flow_type === 'control') {
          path.setAttribute('stroke-dasharray', '5 3')
        }
        root.appendChild(path)
        const last = points[points.length - 1]
        const previous = points[points.length - 2] ?? last
        const angle = Math.atan2(last.y - previous.y, last.x - previous.x)
        const head = document.createElementNS(SVG_NS, 'polygon')
        const size = 5
        head.setAttribute(
          'points',
          `${last.x},${last.y} ` +
            `${last.x - size * Math.cos(angle - 0.45)},${last.y - size * Math.sin(angle - 0.45)} ` +
            `${last.x - size * Math.cos(angle + 0.45)},${last.y - size * Math.sin(angle + 0.45)}`,
        )
        head.setAttribute('fill', color)
        root.appendChild(head)
      }
    }

    const nodeById = new Map(this.graph.nodes.map((node) => [node.id, node]))
    for (const child of layout.children ?? []) {
      const data = nodeById.get(child.id)
      if (!data) continue
      const [fill, stroke] = NODE_FILLS[data.type] ?? NODE_FILLS.default
      const group = document.createElementNS(SVG_NS, 'g')
      group.setAttribute('class', 'wb-diagram-node')
      group.setAttribute('data-node-id', data.id)
      group.setAttribute('role', 'button')
      group.setAttribute('tabindex', '0')
      group.setAttribute('aria-label', data.label)
      const select = () => { this.onNodeClick?.(data); if (this.graph.pilotLayout) this.showDetails(data, group) }
      group.addEventListener('keydown', (e) => {if (e.key === 'Enter' || e.key === ' ') {e.preventDefault(); select()}})

      const rect = document.createElementNS(SVG_NS, 'rect')
      rect.setAttribute('x', String(child.x ?? 0))
      rect.setAttribute('y', String(child.y ?? 0))
      rect.setAttribute('width', String(child.width ?? 84))
      rect.setAttribute('height', String(child.height ?? 34))
      rect.setAttribute('rx', data.type === 'buffer' ? '13' : '7')
      rect.setAttribute('fill', data.color ? `color-mix(in srgb, ${data.color} 19%, white)` : fill)
      rect.setAttribute('stroke', stroke)
      rect.setAttribute('stroke-width', '1.5')
      group.appendChild(rect)
      this.nodeRects.set(data.id, rect)

      const label = document.createElementNS(SVG_NS, 'text')
      label.setAttribute('x', String((child.x ?? 0) + (child.width ?? 84) / 2))
      label.setAttribute('y', String((child.y ?? 0) + (child.height ?? 34) / 2 + 3.5))
      label.setAttribute('text-anchor', 'middle')
      label.setAttribute('font-size', '10')
      label.setAttribute('font-weight', '600')
      label.setAttribute('fill', '#1F2937')
      label.textContent = data.label
      group.appendChild(label)

      group.style.cursor = 'pointer'
      group.addEventListener('click', select)
      group.addEventListener('dblclick', () => this.onNodeDblClick?.(data))
      root.appendChild(group)
    }

    this.container.appendChild(svg)
    this.applyHighlight()
  }

  public highlightNode(nodeId: string | null): void {
    this.highlightedId = nodeId
    this.applyHighlight()
  }

  private showDetails(node: DiagramNode, anchor: SVGElement): void {
    this.container.querySelector('.wb-node-details')?.remove()
    const panel = document.createElement('section')
    panel.className = 'wb-node-details'; panel.setAttribute('role', 'dialog')
    panel.setAttribute('aria-label', `${node.label} 상세 속성`)
    const close = document.createElement('button'); close.textContent = '닫기 ×'
    const dismiss = () => {panel.remove(); anchor.focus()}
    close.onclick = dismiss
    panel.addEventListener('keydown', e => {if (e.key === 'Escape') dismiss()})
    const title = document.createElement('strong'); title.textContent = node.label
    panel.append(close, title)
    const list = document.createElement('dl')
    const properties = node.properties || {id:node.id, type:node.type, layer:node.layer}
    for (const [key, value] of Object.entries(properties)) {
      if (value == null || value === '' || (Array.isArray(value) && !value.length) || key === 'view_hints') continue
      const term = document.createElement('dt'); term.textContent = key
      const detail = document.createElement('dd')
      detail.textContent = typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)
      list.append(term, detail)
    }
    panel.append(list); this.container.append(panel); close.focus()
  }

  private applyHighlight(): void {
    for (const [id, rect] of this.nodeRects) {
      if (this.highlightedId && id === this.highlightedId) {
        rect.setAttribute('stroke', this.theme.selectionBorder)
        rect.setAttribute('stroke-width', '3')
        rect.setAttribute('filter', 'drop-shadow(0 0 4px rgba(47,111,104,.5))')
      } else {
        const data = this.graph.nodes.find((node) => node.id === id)
        const [, stroke] = NODE_FILLS[data?.type ?? ''] ?? NODE_FILLS.default
        rect.setAttribute('stroke', stroke)
        rect.setAttribute('stroke-width', '1.5')
        rect.removeAttribute('filter')
      }
      rect.setAttribute('opacity', this.highlightedId && id !== this.highlightedId ? '0.55' : '1')
    }
  }
}
