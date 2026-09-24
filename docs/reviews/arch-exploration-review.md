# feat/arch-exploration 병합 전 리뷰

기준: 원본 `8d5d866`까지 main 대비 8개 커밋, 42개 파일. SW timing margin,
stage timing budget, 조합 탐색, 예측 등록, 보고서, sample DVFS 및 React 화면을 검토했다.

## 발견 및 수정

| 우선순위 | 재현 조건 / 영향 | 수정 |
| --- | --- | --- |
| P1 | 서로 다른 scenario의 동일 variant ID가 등록 dictionary, 보고서, React 선택에서 충돌 | `(scenario_id, variant_id)` 식별자를 유지. 개별 등록의 모호한 ID는 scenario 지정 요구 |
| P1 | 여러 project를 한 번에 탐색하면 첫 project로 모든 예측이 저장됨 | run을 단일 project로 제한하고 scenario와 요청 SoC 일치 검사 |
| P1 | 같은 variant를 동시에 처음 등록하면 unique constraint 오류 또는 supersession 체인 경합 | 안정적인 variant 행을 순서대로 잠가 current 조회부터 등록까지 직렬화 |
| P2 | 밀리초 timestamp 기반 run/prediction/report ID 충돌 가능 | UUID 식별자 사용 |
| P1 | 요청이 variant 조합 상한을 임의로 높일 수 있고 objective slice만으로 비용을 계산함 | variant 상한 200k 고정, 실제 모든 slice 합산, run 상한 2M, 요청 byte 제한 |
| P2 | fleet의 암시적 전체 선택은 명시적 목록 200개 제한을 우회 | 암시적 선택도 제한, 중복 요청 제거 |
| P1 | 추천 재시뮬레이션 실패에도 spec OK 및 current 등록 가능 | 실패를 spec 미달로 표시하고 실패한 case 등록 거부 |
| P2 | lossy 금지 시 가능한 lossless 선택까지 사라지거나 IP가 해당 모드를 지원하지 않아도 선택됨 | 제약에 맞는 mode 후보를 먼저 걸러 ratio를 선택하고 endpoint별 mode 지원 검사 |
| P2 | SW DMA compression delta가 실제 fps 대신 기본 30 fps를 사용 | adapter가 해석한 fps 사용 |
| P2 | SW margin에서 IP overhead를 sw_ms 안팎으로 두 번 차감 | overhead를 포함한 sw_ms를 한 번만 차감 |
| P1 | 등록된 비압축 case가 보고서 압축 요약에서 추천값으로 대체됨. 대안에 추천 검증 결과가 붙음 | 실제 선택의 compression, lossy/assumed 및 verification 상태 보존 |
| P2 | input hash가 IP 모델 및 SoC compression catalog 변경을 반영하지 못함 | adapter inputs, IP capabilities, SoC catalog 포함; engine rev 3 |
| P2 | CPU coefficient 길이가 짧으면 IndexError, 비정상 계수로 잘못된 전력 계산 | 4개의 유한 양수 계수 검증, what-if 증가율 상한 검증 |
| P2 | 파생 variant를 이름으로만 거르면 사용자 이름의 파생 항목이 포함됨 | 실제 derived_from_variant 참조로 제외 |
| P2 | 다른 scenario/variant 예측끼리 변경 원인 API 호출 가능 | 동일 scenario/variant 이력 비교만 허용 |
| P2 | Timing Budget 옵션 변경마다 무거운 what-if가 다시 실행됨 | 최초 main 성공 이후 variant별 한 번 실행, React DOM 회귀 테스트 |

## 검증

- 전체 Python 단위 테스트: 1,409개 통과, coverage 80.70% (80% gate 유지).
  이후 SW DMA fps 회귀 테스트 1개 추가; architecture 계산 테스트 19개 재검증 통과.
- PostgreSQL testcontainers 전체 통합 테스트: 187개 통과. 새 회귀 테스트는
  동시 첫 등록, 복합 variant ID, 보고서 불변성/HTML escaping, 잘못된 비교 및 검증 실패 등록을 포함한다.
- React: 57개 테스트, TypeScript 검사, production build 통과. npm audit 0건.
- Ruff, mypy, frozen dependency sync, runtime export/pip-audit 통과.
- 새 PostgreSQL에서 migration 0020 및 runtime fixture strict ETL 통과.
  실제 UHD30 EIS variant의 2,048개 조합 탐색 → 재시뮬레이션 검증 → 예측 등록 → HTML 보고서 생성 통과.
- Playwright: 리뷰 UI에서 기존 run 차트와 표 렌더링, 예측/보고서 페이지의 빈 상태 확인.
  브라우저에서 기존 runtime DB를 변경하지 않았다. 저장 흐름은 임시 PostgreSQL에서 검증했다.

## 경계와 한계

- 원본 기능의 CPU 단일 cluster 가정, synthetic DVFS, 미모델 MIF DVFS 및 고 fps batch 한계는 유지한다.
- 추천만 재시뮬레이션하며 대안은 검증 여부를 그대로 표시한다. `verify=false`는 명시적인 미검증 분석이다.
- 저장된 과거 run/보고서는 자동 재계산하지 않는다. engine rev 3 결과가 필요하면 새 탐색/보고서를 생성한다.
- 보고서는 지정한 run의 snapshot이다. 다른 run에서 current가 바뀌면 새 run으로 보고서를 생성해야 한다.
- 브라우저의 기존 favicon 404, Python Starlette/httpx deprecation 경고는 남아 있다.
- 병합은 최종 PR 커밋의 quality, integration, react-ui, web 검사 성공 후 수행한다.
