// Home "pipeline tunnel": generic stage roles (IP names vary per SoC; examples only in `e`).
export type StageKind = 'rt' | 'm2m' | 'mem' | 'sw' | 'post' | 'out'
export interface Stage { n: string; s: string; i: string; k: StageKind; c: string; e: string }
export type Domain = 'camera' | 'video' | 'display'

export const DOMAINS: Record<Domain, Stage[]> = {
  camera: [
    { n: 'CAPTURE', s: 'Image sensor', i: 'RAW · fps · 해상도', k: 'rt', c: 'raw', e: 'Sensor' },
    { n: 'LINK RX', s: 'Camera serial link', i: 'RT · OTF', k: 'rt', c: 'raw', e: 'CSIS' },
    { n: 'RAW FRONT', s: 'Bayer 전처리 · 통계', i: 'RT · clock · DVFS level', k: 'rt', c: 'raw', e: 'PDP · BYRP' },
    { n: 'COLOR', s: 'Demosaic → RGB', i: 'RT · clock · DVFS level', k: 'rt', c: 'raw', e: 'RGBP' },
    { n: 'YUV · SCALE', s: 'Color space · scale', i: 'RT · 25% SW rule', k: 'rt', c: '#F3D9A4', e: 'YUVSC' },
    { n: 'MULTI-SCALE', s: 'Pyramid 생성', i: 'RT HW / budget ms', k: 'rt', c: '#F3D9A4', e: 'MLSC' },
    { n: 'MEMORY', s: 'Frame buffer · 압축', i: 'IP BW · MB/s', k: 'mem', c: '#F5EFE3', e: 'DRAM' },
    { n: 'TEMPORAL', s: 'Multi-frame 처리', i: 'NRT · clock · level', k: 'm2m', c: '#F5EFE3', e: 'MTNR' },
    { n: 'SPATIAL', s: 'Noise · detail', i: 'NRT HW ms', k: 'm2m', c: '#F5EFE3', e: 'MSNR · YUVP' },
    { n: 'OUTPUT SCALE', s: 'Preview · video', i: 'NRT SW ms', k: 'm2m', c: '#F5EFE3', e: 'MCSC' },
    { n: 'MEMORY', s: '1 frame latency', i: 'IP BW · MB/s', k: 'mem', c: '#F5EFE3', e: 'DRAM' },
    { n: 'SW TASK', s: 'Stabilization · AI', i: 'CPU runtime · latency', k: 'sw', c: '#F5EFE3', e: 'EIS' },
    { n: 'GEOMETRY', s: 'Warp · correction', i: 'Post HW ms', k: 'post', c: '#E4DDF8', e: 'GDC' },
    { n: 'DISPLAY', s: 'Preview', i: 'frame 간격 ±0.1%', k: 'out', c: '#9CC3FF', e: 'DPU' },
    { n: 'ENCODE', s: 'Video record', i: 'frame 간격 · clock', k: 'out', c: '#9CC3FF', e: 'MFC' },
  ],
  video: [
    { n: 'STORAGE', s: 'Container · bitstream', i: 'CPU BW · MB/s', k: 'sw', c: '#C9D7F2', e: 'Storage' },
    { n: 'DEMUX', s: 'SW task', i: 'CPU runtime', k: 'sw', c: '#C9D7F2', e: 'Extractor' },
    { n: 'MEMORY', s: 'Bitstream buffer', i: 'IP BW', k: 'mem', c: '#C9D7F2', e: 'DRAM' },
    { n: 'DECODE', s: 'Video decoder', i: 'clock · DVFS level', k: 'm2m', c: '#F5EFE3', e: 'MFD' },
    { n: 'MEMORY', s: 'Decoded frames', i: 'IP BW · 압축', k: 'mem', c: '#F5EFE3', e: 'DRAM' },
    { n: 'POST', s: 'Scale · tone', i: 'M2M HW ms', k: 'post', c: '#F5EFE3', e: 'MSCL · G2D' },
    { n: 'COMPOSE', s: 'Layer blend', i: 'frame 간격', k: 'out', c: '#9CC3FF', e: 'DPU' },
    { n: 'PANEL', s: 'Refresh', i: 'fps · 간격', k: 'out', c: '#9CC3FF', e: 'Panel' },
  ],
  display: [
    { n: 'APP', s: 'UI · render', i: 'CPU runtime', k: 'sw', c: '#C9D7F2', e: 'App' },
    { n: 'RENDER', s: 'GPU composition', i: 'clock · DVFS level', k: 'm2m', c: '#E4DDF8', e: 'GPU' },
    { n: 'MEMORY', s: 'Layer buffers', i: 'IP BW · 압축', k: 'mem', c: '#F5EFE3', e: 'DRAM' },
    { n: 'BLEND', s: 'Hardware composer', i: 'RT · 간격', k: 'rt', c: '#F5EFE3', e: 'DPU' },
    { n: 'PANEL', s: 'Refresh', i: 'fps · 간격', k: 'out', c: '#9CC3FF', e: 'Panel' },
  ],
}
export const DOMAIN_LABEL: Record<Domain, string> = { camera: 'Camera', video: 'Video playback', display: 'Display' }

/** Scenario categories → tunnel domain (camera by default). */
export function domainFor(categories: string[] | undefined): Domain {
  const c = (categories ?? []).map((x) => x.toLowerCase())
  if (c.some((x) => x.includes('camera'))) return 'camera'
  if (c.some((x) => x.includes('video'))) return 'video'
  if (c.some((x) => x.includes('display') || x.includes('game'))) return 'display'
  return 'camera'
}
