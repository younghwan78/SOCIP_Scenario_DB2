import { expect, it } from 'vitest'
import { scenarioFocus, scenarioPurpose, shortVariantIds } from './guides'

it('prefers the scenario metadata purpose and focus over the built-in fallback', () => {
  expect(scenarioPurpose('uc-vid-youtube-e2600', { purpose: '데이터의 설명' })).toBe('데이터의 설명')
  expect(scenarioPurpose('uc-vid-youtube-e2600', { purpose: null })).toMatch(/^YouTube 재생/)
  expect(scenarioPurpose('uc-unknown-x')).toMatch(/등록된 설명이 없습니다/)
  expect(scenarioFocus({ review_focus: ['MFC decode'] }, [])).toEqual(['MFC decode'])
  expect(scenarioFocus({ review_focus: [] }, [])).toEqual([])
})

it('shortens variant ids by their shared prefix, not by a camera-only rule', () => {
  expect([...shortVariantIds(['cam-rec-r1-fhd30-sdr', 'cam-rec-r1-uhd60-sdr']).values()]).toEqual(['fhd30-sdr', 'uhd60-sdr'])
  expect([...shortVariantIds(['yt-1080p30-h264-sdr', 'yt-4k60-av1-hdr10']).values()]).toEqual(['1080p30-h264-sdr', '4k60-av1-hdr10'])
  expect(shortVariantIds(['voice-call-volte']).get('voice-call-volte')).toBe('voice-call-volte')
  expect(shortVariantIds(['abc', 'abd']).get('abc')).toBe('abc') // no shared '-' boundary
})
