/** U-11: the spec verdict of an exploration combination reads 충족 / 미달 everywhere (the timing verdict is OK / Fail). */
export const specLabel = (ok: boolean) => (ok ? '충족' : '미달')
export function SpecBadge({ ok }: { ok: boolean }) {
  return <span className={`badge ${ok ? 'v-ok' : 'v-fail'}`}>{specLabel(ok)}</span>
}
