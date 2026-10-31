import { describe, expect, it } from 'vitest'
import type { ViewNodeData } from './api'
import { chains, LANE_LABEL, LANE_ORDER, laneOf } from './model'
import { placeOf } from './topology'

const node = (id: string, ipRef: string, type = 'ip'): ViewNodeData => ({ id: `ip-${id}`, label: id.toUpperCase(), type, ip_ref: ipRef })

describe('Audio lane', () => {
  const ch = chains(null)
  it('ABOX and the ABOX-hosted audio nodes get their own Audio lane, not M2M accel', () => {
    expect(laneOf(node('abox', 'ip-abox-s5e9965'), ch)).toBe('audio')
    expect(laneOf(node('speaker', 'ip-abox-s5e9965'), ch)).toBe('audio')
    expect(laneOf(node('vps_od', 'ip-vps-s5e9965'), ch)).toBe('m2m')
    expect(LANE_LABEL.audio).toBe('Audio')
    expect(LANE_ORDER.indexOf('audio')).toBe(LANE_ORDER.indexOf('display') + 1)
  })

  it('IP overview places it in an Audio column', () => {
    const ip = { lane: 'audio', pid: 'abox', ipRef: 'ip-abox-s5e9965' } as Parameters<typeof placeOf>[0]
    expect(placeOf(ip, 0, 2)).toEqual({ column: 'audio', section: 'main' })
  })
})
