import {eventEnd, eventStart, type TimelineEvent} from './types'

export function outputMetrics(events: TimelineEvent[], node: string) {
  const starts = new Map<number, number>()
  for (const e of events) if (e.frame_index !== undefined && (e.node_id === 'sensor_rear' || e.constraint_type === 'source')) {
    starts.set(e.frame_index, Math.min(starts.get(e.frame_index) ?? Infinity, eventStart(e)))
  }
  const outputs = events.filter(e => e.node_id === node && e.frame_index !== undefined).sort((a,b) => eventEnd(a)-eventEnd(b))
  const intervals = outputs.slice(1).map((e,i) => eventEnd(e)-eventEnd(outputs[i]))
  const latencies = outputs.flatMap(e => starts.has(e.frame_index!) ? [eventEnd(e)-starts.get(e.frame_index!)!] : [])
  const mean = (v: number[]) => v.length ? v.reduce((a,b)=>a+b,0)/v.length : null
  return {interval: mean(intervals), latency: mean(latencies), outputs: outputs.length,
    unpaired: [...starts.keys()].filter(f => !outputs.some(e => e.frame_index === f)).length}
}
