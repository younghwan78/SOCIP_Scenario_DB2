import {describe,it,expect} from 'vitest'
import {connectedFlows,buildFlowEdges} from '../src/engine/flows'
import {outputMetrics} from '../src/engine/pilotMetrics'
import {matchDiagramNode} from '../src/diagram/mapping'
import {sliceColor} from '../src/engine/colors'
import {buildTracks} from '../src/engine/tracks'

describe('L0 timing pilot',()=>{
  it('follows both output branches without linking adjacent frames',()=>{
    const events=[{task_id:'s0',start_ms:0},{task_id:'e0',start_ms:20,predecessors:['s0']},
      {task_id:'p0',start_ms:25,predecessors:['e0']},{task_id:'v0',start_ms:25,predecessors:['e0']},
      {task_id:'s1',start_ms:33},{task_id:'v1',start_ms:60,predecessors:['s1']}]
    expect(connectedFlows(buildFlowEdges(events),'s0').map(e=>e.toId)).toEqual(['e0','p0','v0'])
  })
  it('preserves start-to-start anchors for overlapping OTF stages',()=>{
    expect(buildFlowEdges([{task_id:'a',start_ms:0},{task_id:'b',start_ms:0,predecessors:['a'],predecessor_anchors:{a:'start'}}])[0].sourceAnchor).toBe('start')
  })
  it('separates 39ms frame latency from 33.33ms output period and window exclusions',()=>{
    const events=[0,1,2].map(f=>({task_id:`s${f}`,node_id:'sensor_rear',frame_index:f,start_ms:f*100/3}))
    const outputs=[0,1].map(f=>({task_id:`v${f}`,node_id:'gdc_o',frame_index:f,start_ms:f*100/3+30,end_ms:f*100/3+39}))
    const m=outputMetrics([...events,...outputs],'gdc_o')
    expect(m.latency).toBeCloseTo(39);expect(m.interval).toBeCloseTo(100/3)
    expect(m.unpaired).toBe(1);expect(m.outputs).toBe(2)
  })
  it('never maps an observation-only task through a resource alias',()=>{
    expect(matchDiagramNode([{id:'ICPU',label:'ICPU',type:'sw',layer:'SW'}],
      {task_id:'crta',resource_id:'ICPU',observation_only:true,start_ms:0})).toBeNull()
  })
  it('keeps task colors across frames and declared camera track order',()=>{
    const e={task_id:'s0',start_ms:0,track_name:'Scenario / SENSOR / SENSOR',logical_task_id:'sensor_readout'}
    expect(sliceColor(e)).toBe(sliceColor({...e,task_id:'s1',frame_index:1}))
    expect(buildTracks([e,{...e,task_id:'sw',track_name:'Scenario / SW / ICPU'}]).map(t=>t.title)).toEqual(['SW / ICPU','SENSOR / SENSOR'])
  })
})
