import { describe, expect, it } from 'vitest'
import { cameraOf, changedKeys, kpiLabel, matrixColumns, medoidId, recordingMode, shortLabels, stabOf, varyingKeys, evidenceSource } from '../src/lib/conditions'
import type { VariantRow } from '../src/lib/api'

const row = (id: string, dc: Record<string, unknown>, extra: Partial<VariantRow> = {}): VariantRow =>
  ({ project_id: 'p', scenario_id: 'uc-camera-recording', variant_id: id, design_conditions: dc, ...extra })

describe('recording mode & KPI', () => {
  it('classifies KPI, slow, portrait, pro and capture', () => {
    expect(kpiLabel({ resolution: 'UHD', fps: 30 })).toBe('UHD30')
    expect(kpiLabel({ fps: 30 })).toBeNull()
    expect(recordingMode(row('cam-rec-r1-uhd30-sdr', { resolution: 'UHD', fps: 30 }))).toBe('kpi')
    expect(recordingMode(row('cam-rec-r1-fhd240', { resolution: 'FHD', fps: 240 }))).toBe('slow')
    expect(recordingMode(row('cam-rec-r1-fhd30-portrait', { resolution: 'FHD', fps: 30, portrait: 1 }))).toBe('portrait')
    expect(recordingMode(row('cam-rec-r1-sf-pro', { subscenario: 'STILL_PRO_SF_CAPTURE' }, { scenario_id: 'uc-camera-capture' }))).toBe('none')
    // ids never supply a missing KPI
    expect(recordingMode(row('cam-rec-r1-uhd30-vdis-explored-max', {}))).toBe('none')
  })
  it('maps camera and stabilization facets', () => {
    expect(cameraOf({ sensor_place: 'rear' })).toBe('rear_wide')
    expect(cameraOf({ sensor_place: 'front' })).toBe('front')
    expect(cameraOf({ camera_mode: 'dual_sync' })).toBe('dual')
    expect(cameraOf({ sensor_place: 'rear_and_front' })).toBe('dual')
    expect(cameraOf({})).toBeNull()
    expect(stabOf({ stabilization: 0 })).toBe('None')
    expect(stabOf({ stabilization: 'SWVDIS' })).toBe('SWVDIS')
  })
})

describe('reference diff', () => {
  const rows = [
    row('a-fhd', { resolution: 'FHD', fps: 30, hdr: 'HDR10' }),
    row('uhd30', { resolution: 'UHD', fps: 30, hdr: 'SDR' }),
    row('uhd30-sdr', { resolution: 'UHD', fps: 30, hdr: 'SDR', bitrate_source: 'assumed' }),
    row('uhd60', { resolution: 'UHD', fps: 60, hdr: 'SDR' }),
    row('uhd30-x', { resolution: 'UHD', fps: 30, hdr: 'SDR', clock: 400 }, { derived_from_variant: 'uhd30', own_condition_keys: ['clock'] }),
  ]
  const byId = new Map(rows.map((r) => [r.variant_id, r]))
  it('picks the medoid instead of the alphabetical first', () => {
    expect(['uhd30', 'uhd30-sdr']).toContain(medoidId(rows))
  })
  it('compares derived variants with their parent', () => {
    expect(changedKeys(rows[4], byId.get('uhd60'), byId)).toEqual(['clock'])
    expect(changedKeys(rows[3], byId.get('uhd30'), byId)).toEqual(['fps'])
    expect(changedKeys(rows[1], byId.get('uhd30'), byId)).toEqual([])
  })
  it('orders varying keys by priority and hides *_source', () => {
    const { varying, constant } = varyingKeys(rows)
    expect(varying.slice(0, 3)).toEqual(['resolution', 'fps', 'hdr'])
    expect(varying).not.toContain('bitrate_source')
    expect(constant).toEqual({})
  })
})

describe('labels and matrix columns', () => {
  it('strips the shared id prefix', () => {
    expect(shortLabels(['cam-rec-r1-uhd30-sdr', 'cam-rec-r1-uhd30-vdis'])).toEqual({ 'cam-rec-r1-uhd30-sdr': 'sdr', 'cam-rec-r1-uhd30-vdis': 'vdis' })
    expect(shortLabels(['a-x', 'a-x-y'])).toEqual({ 'a-x': 'x', 'a-x-y': 'x-y' })
  })
  it('normalizes audio and camera rows to shared columns', () => {
    expect(matrixColumns({ format: 'MP3', output: 'speaker', screen_on: 0, offload: 1 })).toMatchObject({ 'Mode · Format': 'MP3', 'Output · HDR': 'speaker', Screen: 'off · offload' })
    expect(matrixColumns({ resolution: '8K', fps: 30, hdr: 'SDR', record_bitrate_mbps: 120, sensor_place: 'rear' })).toMatchObject({ 'Res · fps': '8K · 30fps', Camera: 'Rear wide', 'Codec · Rate': '120 Mbps' })
  })
  it('flags synthetic measurement evidence', () => {
    expect(evidenceSource({ id: 'meas-synthetic-x', kind: 'evidence.measurement' })).toBe('synthetic')
    expect(evidenceSource({ id: 'm', kind: 'evidence.measurement', provenance: { collection_method: 'power_monitor' } })).toBe('measured')
    expect(evidenceSource({ id: 's', kind: 'evidence.simulation' })).toBe('calculated')
  })
})
