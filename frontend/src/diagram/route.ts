export interface Box {x:number; y:number; width:number; height:number}
export interface Point {x:number; y:number}

export function crossesBox(a:Point, b:Point, r:Box, margin=3): boolean {
  const left=r.x-margin, right=r.x+r.width+margin, top=r.y-margin, bottom=r.y+r.height+margin
  return a.x===b.x
    ? a.x>left && a.x<right && Math.max(a.y,b.y)>top && Math.min(a.y,b.y)<bottom
    : a.y>top && a.y<bottom && Math.max(a.x,b.x)>left && Math.min(a.x,b.x)<right
}

// Route through the gutters around nodes. Source/target ports are on block boundaries.
export function routeAround(a:Box, b:Box, boxes:Box[]): Point[] {
  const ports=(r:Box)=>[
    [{x:r.x+r.width/2,y:r.y},{x:r.x+r.width/2,y:r.y-8}],
    [{x:r.x+r.width/2,y:r.y+r.height},{x:r.x+r.width/2,y:r.y+r.height+8}],
    [{x:r.x,y:r.y+r.height/2},{x:r.x-8,y:r.y+r.height/2}],
    [{x:r.x+r.width,y:r.y+r.height/2},{x:r.x+r.width+8,y:r.y+r.height/2}],
  ]
  const starts=ports(a), ends=ports(b)
  const xs=[...new Set(boxes.flatMap(r=>[r.x-8,r.x+r.width+8,r.x+r.width/2]))].sort((a,b)=>a-b)
  const ys=[...new Set(boxes.flatMap(r=>[r.y-8,r.y+r.height+8,r.y+r.height/2]))].sort((a,b)=>a-b)
  const index=(p:Point)=>ys.indexOf(p.y)*xs.length+xs.indexOf(p.x)
  const point=(i:number)=>({x:xs[i%xs.length],y:ys[Math.floor(i/xs.length)]})
  const previous=new Map<number,number>(), origins=new Map<number,Point>()
  const queue:number[]=[]
  for (const [port,stub] of starts) {
    if (boxes.some(r=>r!==a&&crossesBox(port,stub,r))) continue
    const id=index(stub); previous.set(id,-1); origins.set(id,port); queue.push(id)
  }
  const targets=new Map(ends.filter(([port,stub])=>!boxes.some(r=>r!==b&&crossesBox(port,stub,r))).map(([port,stub])=>[index(stub),port]))
  for(let cursor=0;cursor<queue.length;cursor++) {
    const id=queue[cursor], p=point(id)
    if(targets.has(id)) {
      const path=[targets.get(id)!,p]; let current=id
      while(previous.get(current)!>=0) {current=previous.get(current)!;path.push(point(current))}
      path.push(origins.get(current)!);path.reverse()
      return path.filter((p,i)=>i===0||i===path.length-1|| !((path[i-1].x===p.x&&p.x===path[i+1].x)||(path[i-1].y===p.y&&p.y===path[i+1].y)))
    }
    const col=id%xs.length, row=Math.floor(id/xs.length)
    const neighbors=[col>0?id-1:-1,col<xs.length-1?id+1:-1,row>0?id-xs.length:-1,row<ys.length-1?id+xs.length:-1]
    for(const next of neighbors) {
      if(next<0||previous.has(next)||boxes.some(r=>crossesBox(p,point(next),r))) continue
      previous.set(next,id);queue.push(next)
    }
  }
  throw new Error('No unobstructed route between diagram blocks')
}
