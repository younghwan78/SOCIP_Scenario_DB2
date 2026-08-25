# ScenarioDB Internal Implementation Documents

| Field | Value |
| --- | --- |
| Status | Historical and internal working material |
| Last organized | 2026-08-26 |
| Current public-safe contract | `../docs/` |

이 디렉터리는 실제 구현 과정의 계획, 설계 판단, 조사, 검증 결과와 release
체크리스트를 보존한다. 여기에 있는 날짜별 문서는 현재 코드 동작의 정본이
아니다. 현재 계약은 `docs`와 테스트를 우선한다.

## Structure

- `design_notes/`: 구현 선택의 배경, rollout 경계, deferred decision
- `implementation_history/YYYY-MM/`: 날짜별 계획과 완료 기록
- `investigations/`: read-only 조사와 후보 분석
- `validation/`: 과거 benchmark와 검증 증적
- `release_checklists/`: staging, merge, rollback 승인 양식

## Current internal design notes

- [Measurement Comparison Internal Design](design_notes/measurement-comparison-design.md)
- [Production Hardening Design](design_notes/production-hardening-design.md)

안정된 현재 동작은 다음 정본으로도 반영되어 있다.

- [Simulation and Evidence](../docs/design/simulation-and-evidence.md)
- [Security and Write Lifecycle](../docs/design/security-and-write-lifecycle.md)

## Handling rules

- 실제 사용자, 조직, ACL, 사내 URL, 인증서, 토큰, 비밀번호를 기록하지 않는다.
- 로컬 검증은 synthetic fixture를 사용한다.
- 과거 문서의 당시 경로·커밋·체크박스는 역사적 증거로 보존할 수 있다.
- 현재 동작을 설명해야 한다면 과거 계획을 수정하지 말고 `docs` 정본을 갱신한다.
- 장기 실행 로그와 binary evidence는 저장소가 아닌 승인된 증적 저장소에 둔다.
