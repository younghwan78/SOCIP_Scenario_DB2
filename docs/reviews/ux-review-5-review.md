# UX review 5 병합 리뷰

원본 `ed29982`, `d285ec3`, `c725cf2`의 coverage, IP 연결도, Compare/Timing 표현과 보고서 의견을 검토했다.
앞선 Home/fixture PR의 리뷰 보완을 유지했다.

| 등급 | 위치 | 영향과 수정 |
| --- | --- | --- |
| P1 | `api/services/arch_exploration.py:create_report` | 예전 run 보고서가 현재 DB의 변경된 조건으로 분류됨. 저장된 run의 design_conditions 사용; 새 run은 severity도 저장 |
| P1 | `reporting/arch_opinions.py:build_opinions` | 같은 variant 이름의 다른 scenario DVFS headroom 혼입. scenario/variant 복합 키로 연결 |
| P2 | 같은 파일 `_share` | legacy bw_mw에 CPU BW를 다시 더해 구성비가 100% 초과. 총 BW 우선, 분해값은 fallback |
| P2 | 같은 파일 `_pair_delta` | 24/30fps나 다른 HDR·센서·clock 그룹의 평균 차이를 EIS/codec 단독 영향으로 설명. fps를 분리하고 비통제 그룹 평균임을 명시 |
| P2 | 같은 파일 `classify` | 비카메라 scenario도 recording, 명시 H264도 HEVC로 표시. 녹화 범위 제한 및 명시 codec 보존 |
| P2 | 의견 HTML/문구 | 등록 없이 추천만 있는 run도 등록 예측이라고 단정. 등록 또는 추천 출처를 정확히 표시 |
| P2 | `ui/src/lib/topology.ts:topoLayout` | 빈 IP 목록에서 SVG 폭이 음수. 최소 양수 크기 유지 |
| P2 | `ui/src/components/IpInternalView.tsx:IpTopology` | interactive SVG가 img로 노출되어 버튼 탐색을 막고 긴 IP 이름이 잘림. group 역할과 전체 accessible name 제공 |

검증:
- 보고서 unit/PostgreSQL 회귀 30개, calibration coverage PostgreSQL 회귀 1개 통과.
- React 68개, typecheck/build, Ruff/mypy 통과.
- 전체 Python 단위 테스트 1,438개, coverage 80.34% 통과 (80% 기준 유지).
- 별도 PostgreSQL의 runtime fixture strict ETL과 실제 2,048개 조합 탐색 → 등록 → HTML 보고서 생성 통과.
- Playwright에서 IP 연결도와 EIS 선택 상세 전환, 실제 측정 필터(합성 33건 분리), 보고서 iframe을 확인.
- 전체 단위 테스트 커버리지와 4개 CI 검사는 최종 PR 커밋 기준으로 확인 후 병합한다.

한계: 그룹 평균은 통제 실험이 아니며 model/입력 가정의 영향을 포함한다.
과거 run에서 저장하지 않은 severity는 미정으로 표시한다. 과거 저장 HTML은 변경하지 않는다.
기존 favicon 404와 Starlette/httpx deprecation은 이번 변경 범위 밖이다.
