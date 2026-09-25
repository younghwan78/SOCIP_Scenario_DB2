# Home / navigation / Library 리뷰

원본 `5a4fdcd`의 25개 파일을 API, DB 소유권, React 탐색, 접근성과 성능 관점에서 검토했다.

| 등급 | 발견 위치 | 영향과 수정 |
| --- | --- | --- |
| P1 | `api/services/calibration.py:_rail_map` | project 없는 실측이 다른 project의 최신 profile을 사용. scenario 소유 project로 복원하고 불명확한 경우 이름 규칙만 사용 |
| P2 | `api/services/calibration.py:_sim_evidence` | ID 사전순을 최신 simulation으로 표시. measured_at 우선, null은 가장 오래된 순으로 변경 |
| P2 | `api/services/calibration.py:list_measurements` | 실측 N개당 DB 쿼리 2N개 추가. 복합 scenario/variant 키를 유지하는 3회 일괄 조회로 변경 |
| P2 | `comparison/calibration.py:rail_category` | 명시적 GPU/NPU/ICPU 등 domain이 IP로 오분류. 기타 bucket 유지 |
| P2 | `ui/src/pages/Calibration.tsx` | 예측 링크가 variant ID를 넘겨 선택 실패. 실제 prediction ID 사용 |
| P2 | `ui/src/lib/library.ts` | IP/DVFS/SoC/Sensor 첫 페이지만 표시. 모든 페이지를 이어 읽도록 수정 |
| P2 | `ui/src/components/PipelineTunnel.tsx` | 정지·숨김 상태에서도 canvas를 매 프레임 다시 그림. 불필요한 drawing 제거 및 reduced-motion 설정 변경 반영 |
| P2 | `ui/src/styles.css` | 좁은 Home에서 절대 위치 카드들이 겹침. 실제 컨테이너 폭 기준으로 세로 배치 및 스크롤 허용 |

검증: 관련 Python 17개(PostgreSQL 포함), React 64개, typecheck/build, npm audit,
Ruff 및 mypy 통과. 전체 단위/통합/Workbench 검증은 PR의 최종 CI로 확인한다.
기존 runtime DB는 리뷰 테스트에서 변경하지 않았다.

한계: 전력 비교는 동일 scenario/variant의 모델 추정과 rail bucket 비교다.
서로 다른 SW/온도/측정 조건을 통제한 인과 추정이 아니다. 프로필 선택은 project의 최신 버전이며 draft도 포함한다.
