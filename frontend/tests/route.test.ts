import {describe,it,expect} from 'vitest'
import {routeAround,crossesBox} from '../src/diagram/route'

describe('diagram obstacle routing',()=>{
  it('avoids intermediate blocks for forward, reverse and side connections',()=>{
    const boxes=[{x:100,y:10,width:104,height:22},{x:100,y:55,width:104,height:22},
      {x:100,y:100,width:104,height:22},{x:220,y:55,width:104,height:22}]
    for(const [a,b] of [[boxes[0],boxes[2]],[boxes[2],boxes[0]],[boxes[0],boxes[3]]]) {
      const path=routeAround(a,b,boxes)
      expect(path.length).toBeGreaterThan(1)
      for(let i=1;i<path.length;i++) {
        expect(path[i].x===path[i-1].x||path[i].y===path[i-1].y).toBe(true)
        for(const box of boxes) expect(crossesBox(path[i-1],path[i],box,0)).toBe(false)
      }
    }
  })
})
