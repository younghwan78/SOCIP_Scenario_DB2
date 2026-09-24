# feat/react-ui 병합 전 리뷰

리뷰 기준: `origin/main`의 `c7c7333`부터 `feat/react-ui`의 `c2fbadd`까지 11개 커밋, 96개 파일. React UI 외에도 Streamlit 비교 화면, 카메라 Perfetto import, Workbench 변경을 포함한다.

## 발견 및 수정

| 우선순위 | 재현 조건과 영향 | 반영한 수정 |
|---|---|---|
| P1 | variant를 바꾼 뒤 요청이 끝나기 전 이전 view/evidence가 새 선택에 표시됨 | 비동기 결과를 요청 의존성과 결합하고 이전 요청 결과를 즉시 숨김. Pipeline 상태도 선택별로 초기화 |
| P1 | 다른 scenario를 Compare에 추가하거나 존재하지 않는 ID를 앞에 놓으면 비교 열이 잘못 연결됨 | scenario 변경 시 비교 목록 초기화, 중복 제거, 누락된 ID의 열 위치 보존과 오류 표시 |
| P2 | `ui/`가 기존 `web` CI에 포함되지 않고 Vite/Vitest 개발 의존성 감사에서 5건이 검출됨 | 별도 React CI 추가, 개발 도구 업데이트, 전체 npm audit 0건 확인 |
| P2 | variant/catalog/evidence가 한 페이지 한도를 넘으면 검색·비교·타이밍 목록에서 조용히 누락됨 | total/offset을 따라 모든 페이지 조회, evidence에 project 범위 전달, API 캐시 수명과 크기 제한 |
| P2 | variant 없는 scenario에서 Pipeline이 무조건 variant 선택 오류를 냄 | base scenario view endpoint 사용 |
| P2 | trace frame 번호가 100부터 시작하면 maxFrames 필터에서 모두 사라짐. 짧은 이벤트는 0.05ms로 변조됨 | frame ID 개수로 제한, 원본 duration 보존, 실제 시작 시각으로 표시 범위 초기화 |
| P2 | 같은 HW 이름의 GDC preview/video 이벤트가 한 트랙에서 겹침 | pipeline node ID를 우선한 트랙 구분 |
| P1 | 센서가 없어도 첫 이벤트를 센서 시작으로 간주하고 같은 frame 번호만으로 센서 지연을 계산함 | 실제 센서와 명시적인 predecessor 연결이 있는 경우만 지연 계산, 완료 시각 순으로 cadence 계산 |
| P1 | DMA의 MB 표시가 MiB였고 10/12비트 샘플을 일괄 16비트로 계산함. 압축을 무시함 | decimal MB, 선언된 비트 깊이와 P010/P210 컨테이너 크기 적용. 압축/정렬 바이트 크기를 모르면 계산에서 제외 |
| P2 | severity 필터와 pagination을 사용하면 파생 variant의 상속/override 축이 현재 페이지에 따라 달라짐 | 전체 필터 결과와 부모 체인의 조건 키를 좁은 열 조회로 계산. 깨진 상속은 422 오류로 표시 |
| P2 | Streamlit A/B 교체 버튼이 이미 생성된 widget session key를 수정하여 예외 발생 | widget 생성 전 실행되는 callback으로 교체, AppTest 클릭 회귀 테스트 추가 |
| P2 | scenario만 지정한 Streamlit 링크에서 이전 variant가 남음 | 상위 context 변경 시 하위 context 초기화 |
| P1 | 새 Perfetto 통합 테스트가 CI에서 `ModuleNotFoundError`로 실패함 | quality/integration의 sync와 run, 런타임 보안 감사에 profiling extra를 일관되게 적용 |

## 검증

- React 단위/DOM 회귀 테스트, TypeScript 검사, production build, 전체 npm audit.
- 기존 Workbench: 44개 테스트, 타입 검사, 재빌드 통과. 생성 자산 변경 없음.
- Python 전체 단위 테스트: profiling extra 포함 1,355개 통과 후 상속 오류 회귀 테스트 1개 추가 및 해당 파일 7개 재검증 통과.
- PostgreSQL testcontainers 통합 테스트: 183개 통과. 페이지 간 상속 축 불변성 검증 포함.
- Ruff, mypy, frozen dependency sync 및 CI와 동일한 런타임 의존성 export/pip-audit 통과.
- Playwright와 실행 중인 PostgreSQL API로 Explorer, Pipeline DMA/IP 내부, picker의 scenario 변경 및 다른 scenario 비교 추가를 확인. 상세 동작은 추가 회귀 테스트로 검증.
- 카메라 fixture 실제 Perfetto 파싱 및 SW projection 테스트는 profiling extra를 포함한 전체 단위 테스트에서 실행.

## 검토 범위와 한계

React UI의 API/라우팅/비교 정렬, 그래프·타이밍·DMA 모델과 표시, Streamlit context/비교 및 카메라 trace import·관측 전용 SW projection 경계를 검토했다. 기존 static ELK 자산을 포함한 Workbench 빌드도 검증했다.

브라우저 확인은 현재 로컬 데이터와 주요 화면 흐름을 대상으로 했다. 모든 variant와 모든 화면 크기에 대한 수동 검증은 수행하지 않았다. 브라우저 콘솔의 favicon 404는 기능 오류와 별개이며 남아 있다. DMA 합계는 크기를 알 수 있는 buffer의 모델 추정치이고 실제 DRAM 트래픽 측정값이 아니다. Python에서 기존 Starlette/httpx 사용 중단 예정 경고 1건이 남아 있다.

병합은 PR의 `quality`, `integration`, `web`, `react-ui`가 모두 성공한 뒤 수행한다. GitHub CI 결과와 최종 병합 커밋은 PR에서 확인한다.
