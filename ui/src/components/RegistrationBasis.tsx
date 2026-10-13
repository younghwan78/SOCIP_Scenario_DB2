export function RegistrationBasis({ guard }: { guard: { expected?: { prediction_id: string | null }[]; ready: boolean; error?: string; conflict: boolean; refresh: () => void } }) {
  return <div className="registration-basis">
    <span className={guard.error || guard.conflict ? 'err' : 'faint'}>{guard.error ?? (guard.conflict ? '새 기준 예측을 비교한 후 다시 확인하세요.' : guard.expected ? `검토 기준: ${guard.expected.map((row) => row.prediction_id ?? '첫 등록').join(' · ')}` : '등록 기준 확인 중…')}</span>
    {(guard.error || guard.conflict) && <><a className="btn tb-mini" href="#/predictions">예측 비교</a><button className="btn tb-mini" onClick={guard.refresh}>기준 다시 확인</button></>}
  </div>
}
