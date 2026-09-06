import ELK from 'elkjs/lib/elk-api.js'
import workerUrl from 'elkjs/lib/elk-worker.min.js?url'
import type { NodeElement, ViewResponse } from '../../types'

export interface LayoutedNode {
  id: string
  x: number
  y: number
  width: number
  height: number
  label: string
  type: string
  layer?: string
  color: string
  stroke: string
  textColor: string
  submoduleKind?: string
  badges?: string[]
}

export interface LayoutedEdge {
  id: string
  source: string
  target: string
  flowType: string
  sections: Array<{
    startPoint: { x: number; y: number }
    endPoint: { x: number; y: number }
    bendPoints?: Array<{ x: number; y: number }>
  }>
  strokeColor: string
}

export interface LayoutGraphResult {
  width: number
  height: number
  nodes: LayoutedNode[]
  edges: LayoutedEdge[]
}

export class PipelineGraphEngine {
  private elk: any

  constructor() {
    this.elk = new ELK({ workerFactory: () => new Worker(workerUrl) })
  }

  public dispose(): void { this.elk.terminateWorker() }

  public async layoutView(view: ViewResponse): Promise<LayoutGraphResult> {
    if (!view || !view.nodes) {
      return { width: 800, height: 600, nodes: [], edges: [] }
    }

    const elkChildren = view.nodes.map((n) => ({
      id: n.data.id,
      width: n.data.type === 'buffer' ? 160 : 180,
      height: 48,
    }))

    const elkEdges = view.edges.map((e) => ({
      id: e.data.id,
      sources: [e.data.source],
      targets: [e.data.target],
    }))

    const elkGraph = {
      id: 'root',
      layoutOptions: {
        'elk.algorithm': 'layered',
        'elk.direction': 'RIGHT',
        'elk.layered.spacing.nodeNodeBetweenLayers': '60',
        'elk.spacing.nodeNode': '30',
        'elk.edgeRouting': 'ORTHOGONAL',
      },
      children: elkChildren,
      edges: elkEdges,
    }

    const nodeById = new Map(view.nodes.map(node => [node.data.id, node]))
    const edgeById = new Map(view.edges.map(edge => [edge.data.id, edge]))
    const layouted = await this.elk.layout(elkGraph)
    const nodes: LayoutedNode[] = (layouted.children || []).map((cn: any) => {
      const rawNode = nodeById.get(cn.id)
      const style = this.getNodeStyle(rawNode)
      return {
        id: cn.id,
        x: cn.x,
        y: cn.y,
        width: cn.width,
        height: cn.height,
        label: rawNode?.data.label || cn.id,
        type: rawNode?.data.type || 'ip',
        layer: rawNode?.data.layer,
        color: style.fill,
        stroke: style.stroke,
        textColor: style.text,
        submoduleKind: rawNode?.data.module_kind,
        badges: rawNode?.data.summary_badges,
      }
    })

    const edges: LayoutedEdge[] = (layouted.edges || []).map((ce: any) => {
      const rawEdge = edgeById.get(ce.id)
      return {
        id: ce.id,
        source: ce.sources[0],
        target: ce.targets[0],
        flowType: rawEdge?.data.flow_type || 'OTF',
        sections: ce.sections || [],
        strokeColor: this.getEdgeColor(rawEdge?.data.flow_type || 'OTF'),
      }
    })

    return {
      width: layouted.width || 1200,
      height: layouted.height || 800,
      nodes,
      edges,
    }
  }

  private getNodeStyle(node?: NodeElement): { fill: string; stroke: string; text: string } {
    if (!node) return { fill: '#1E293B', stroke: '#475569', text: '#F8FAFC' }
    const type = node.data.type
    const layer = node.data.layer

    if (layer === 'app') return { fill: '#312E81', stroke: '#6366F1', text: '#EEF2FF' }
    if (layer === 'framework') return { fill: '#1E3A8A', stroke: '#3B82F6', text: '#EFF6FF' }
    if (layer === 'hal') return { fill: '#134E4A', stroke: '#14B8A6', text: '#F0FDFA' }
    if (type === 'isp') return { fill: '#7C2D12', stroke: '#F97316', text: '#FFEDD5' }
    if (type === 'codec') return { fill: '#4C1D95', stroke: '#8B5CF6', text: '#F5F3FF' }
    if (type === 'display') return { fill: '#0C4A6E', stroke: '#0EA5E9', text: '#E0F2FE' }
    if (type === 'buffer') return { fill: '#064E3B', stroke: '#10B981', text: '#D1FAE5' }

    return { fill: '#1E293B', stroke: '#475569', text: '#F8FAFC' }
  }

  private getEdgeColor(flowType: string): string {
    switch (flowType) {
      case 'OTF': return '#14B8A6'
      case 'vOTF': return '#2DD4BF'
      case 'M2M': return '#F97316'
      case 'control': return '#8B5CF6'
      case 'risk': return '#EF4444'
      default: return '#64748B'
    }
  }
}
