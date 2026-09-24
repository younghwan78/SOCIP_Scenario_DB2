// Operating-mode notes that change the HW/SW sequence or timing semantics.
// Derived from explicit conditions / active nodes only (no guessing from names alone).
import type { Dict } from './api'

export interface ModeNote { id: string; label: string; detail: string; tone: 'info' | 'warn' }

export function modeNotes(dc: Dict | null | undefined, activePids: Set<string>, disabled: string[] = []): ModeNote[] {
  const c = dc ?? {}
  const out: ModeNote[] = []
  const fps = Number(c.fps ?? NaN)
  const ext = String(c.extend_mode ?? '') + ' ' + String(c.is_scenario ?? '') + ' ' + String(c.subscenario ?? '')
  const batch = Number(c.batch_size ?? c.batch ?? c.hs_batch ?? NaN)
  if (Number.isFinite(batch) && batch > 1) out.push({ id: 'batch', label: `Batch ×${batch}`, detail: `High-speed batch mode: ${batch} frame을 묶어 NRT/M2M 처리 → 출력 간격이 burst + gap 형태`, tone: 'warn' })
  else if ((Number.isFinite(fps) && fps >= 120) || /HIGH_SPEED|DUALFPS|SSM/i.test(ext)) out.push({ id: 'hs', label: `High-speed ${Number.isFinite(fps) ? fps : ''}fps`, detail: 'High-speed recording: batch 처리 여부를 trace 간격 분포(bimodal)로 확인하세요. batch_size 조건 미등록.', tone: 'warn' })
  const hasLme = activePids.has('lme'), hasDof = activePids.has('vps_dof')
  if (hasDof && !hasLme) out.push({ id: 'dof', label: 'ME = VPS DOF', detail: 'LME 대신 VPS DOF(dense optical flow)로 motion 추정 → preME 구간이 VPS에서 실행', tone: 'info' })
  else if (hasDof && hasLme) out.push({ id: 'dof+lme', label: 'LME + VPS DOF', detail: 'LME와 VPS DOF가 모두 활성', tone: 'info' })
  const stab = String(c.stabilization ?? '')
  const hasGdc = [...activePids].some((p) => p.startsWith('gdc'))
  const eisOn = activePids.has('eis')
  if (c.power_saving_mode === true || c.power_saving_mode === 'true') {
    out.push({ id: 'psm', label: 'EIS power saving', detail: `power_saving_mode: ${hasGdc ? 'GDC 유지' : 'GDC 생략 → MCSC가 DPU/MFC로 직접 출력'}${eisOn ? '' : ', EIS SW 비활성'}`, tone: 'warn' })
  } else if (!hasGdc && disabled.some((d) => d.startsWith('gdc')) && stab && stab !== 'None' && stab !== '0') {
    out.push({ id: 'gdc-skip', label: 'GDC 생략', detail: `stabilization=${stab}인데 GDC 비활성 → warp 없이 MCSC 직결`, tone: 'warn' })
  } else if (!hasGdc && disabled.some((d) => d.startsWith('gdc'))) {
    out.push({ id: 'direct', label: 'MCSC 직결', detail: 'EIS/GDC 비활성 (recursive 또는 stabilization off) → MCSC WDMA가 DPU/MFC 입력', tone: 'info' })
  }
  if (eisOn && hasGdc) out.push({ id: 'eis', label: 'EIS → GDC', detail: 'MCSC 완료 후 EIS SW가 warp grid 계산 → GDC(preview/video) 시작 (NRT 이후 SW 직렬 구간)', tone: 'info' })
  return out
}
