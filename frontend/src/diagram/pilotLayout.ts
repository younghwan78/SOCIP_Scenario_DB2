import {routeAround} from './route'
import type { DiagramGraph } from './mapping'

// Presentation coordinates for the UHD30 pilot; edges remain the source topology.
export function pilotLayout(graph: DiagramGraph) {
  const rows: Record<string, number> = {
    sensor_rear:30, csis:60, pdp:90, byrp:120, rgbp:150, yuvsc:180, mlsc:210,
    post_crta:260, pre_me_rta:290, lme:290, vps_od:320, post_irta:350,
    mtnr:400, msnr:430, yuvp:460, mcsc:490, eis:550,
    gdc_m:590, gdc_o:620, dpu:660, mfc_enc:690, panel:720,
    mpeg_writer:690, storage_write:730,
  }
  const buffers = ['pyramid-l0','pyramid-l1','pyramid-l2','pyramid-l3','pyramid-l4',
    'lme-input','od-input','rgbp-drc','mlsc-svhist']
  const outputs = ['mcsc-preview','mcsc-video','gdc-preview','gdc-video']
  let extra = 0
  const children = graph.nodes.map(node => {
    const id = node.id.replace(/^ip-/, '')
    let x = node.type === 'sw' ? 240 : 360
    let y = rows[id]
    if (node.type === 'buffer') {
      const key = node.id.replace(/^buf-/, '')
      const i = buffers.indexOf(key), j = outputs.indexOf(key)
      if (i >= 0) { x = 500 + (i % 2) * 115; y = 250 + Math.floor(i / 2) * 27 }
      else if (j >= 0) { x = 500 + (j % 2) * 115; y = j < 2 ? 530 : 645 }
    }
    if (y === undefined) { x = 70; y = 30 + extra++ * 30 }
    return {id:node.id, x:x - 52, y:y*1.16, width:104, height:22}
  })
  const byId = new Map(children.map(n => [n.id,n]))
  const edges = graph.edges.flatMap(edge => {
    const a = byId.get(edge.source), b = byId.get(edge.target)
    if (!a || !b) return []
    const points = routeAround(a, b, children)
    return [{id:edge.id, sections:[{startPoint:points[0], endPoint:points[points.length-1], bendPoints:points.slice(1,-1)}]}]
  })
  return {id:'root', width:720, height:770*1.16, children, edges}
}
