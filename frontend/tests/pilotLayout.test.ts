import {describe, it, expect, vi} from 'vitest'
import {pilotLayout} from '../src/diagram/pilotLayout'
import {TimelineEngine} from '../src/engine/TimelineEngine'
import {LIGHT_THEME} from '../src/theme'

describe('pilot layout', () => {
  it('fits all timing lanes into the available height after resize and restores without Y offset', () => {
    const engine = new TimelineEngine(LIGHT_THEME)
    vi.spyOn(engine, 'requestRender').mockImplementation(() => {})
    let height = 600
    Object.assign(engine, {canvas:{getBoundingClientRect:()=>({height,width:800})}})
    const events = Array.from({length:20}, (_,i)=>({task_id:`t${i}`,start_ms:0,end_ms:10,track_name:`track${i}`}))
    engine.setData(events, {pilot:true,showWaits:false,showDeadlines:false,theme:'light',frameIntervalMs:33.333})
    expect(engine.contentHeight()).toBeLessThanOrEqual(height+0.001)
    height = 300
    expect(engine.contentHeight()).toBeLessThanOrEqual(height+0.001)
    engine.restoreViewport({startMs:0,endMs:100,offsetY:-500})
    expect(engine.viewport().offsetY).toBe(0)
  })
  it('places SW at one third, HW at center, and buffers between their stages', () => {
    const ids = ['ip-mlsc','ip-post_crta','ip-mtnr','ip-mcsc','buf-pyramid-l0','buf-mcsc-video','buf-gdc-video','ip-new']
    const nodes = ids.map(id => ({id,label:id,type:id.startsWith('buf') ? 'buffer' : id==='ip-post_crta' ? 'sw' : 'ip',layer:''}))
    const edges = [{id:'e',source:'ip-mlsc',target:'buf-pyramid-l0',flow_type:'M2M'}]
    const layout = pilotLayout({nodes,edges})
    const get = (id:string) => layout.children.find(n=>n.id===id)!
    expect(get('ip-post_crta').x+52).toBe(layout.width/3)
    expect(get('ip-mtnr').x+52).toBe(layout.width/2)
    expect(get('buf-pyramid-l0').y).toBeGreaterThan(get('ip-mlsc').y)
    expect(get('buf-pyramid-l0').y).toBeLessThan(get('ip-mtnr').y)
    expect(get('buf-mcsc-video').y).toBeGreaterThan(get('ip-mcsc').y)
    expect(layout.children).toHaveLength(nodes.length)
    expect(layout.edges.map(e=>e.id)).toEqual(['e'])
    for (const node of layout.children) {
      expect(node.y+node.height).toBeLessThanOrEqual(layout.height)
      expect(node.x+node.width).toBeLessThanOrEqual(layout.width)
    }
  })
})
