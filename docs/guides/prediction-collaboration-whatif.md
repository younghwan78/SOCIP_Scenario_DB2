# 예측 설명·댓글과 자연어 What-if

Status: Current. Last verified: 2026-10-16.
Source: `ui/src/pages/ScenarioWhatIf.tsx`, `ui/src/components/MeasurePopover.tsx`, `ui/src/components/PredictionCollaboration.tsx`,
`src/scenario_db/api/services/scenario_whatif.py`, `whatif_conditions.py`, `whatif_levers.py`,
`whatif_query.py`, `prediction_discussion.py`.

## 질문으로 조건 비교하기

1. 과제, scenario, variant를 선택하고 **What-if**를 엽니다.
2. **조건 바꿔보기**, **레버 조합 비교**, **어디까지 낮출 수 있나**, **병목 찾기** 중 질문 종류를 고릅니다.
3. 레버 팔레트에서 바꿀 항목을 담습니다. 팔레트는 과제 상용화 검토 순서로 묶여 있습니다.
   - 센서: 다른 sensor · DT mode (readout · 크기가 다르면 RT chain · pyramid 재계산)
   - 크기: IP crop · downscale (BYRP bayer crop, YUVSC YUV downscale, −5~25% / EIS 25→15% preset), MCSC 출력 크기
   - Temporal: power option (bayer crop 전략, MTNR L0 skip), previous DMA 빈도 (N frame에 1회)
   - DVFS · clock: domain level (±1·±2 step), IP clock 하한, FPS
   - IP mode, SBWC 압축 (끔 · lossless · lossy · catalog의 footprint mode, IP 미지원 mode는 선택 불가)
   한계 탐색은 domain을 선택하고, 병목 진단은 현재 기준을 사용합니다.
   레버 조합 비교는 레버 2개 이상을 각각 · 함께(또는 모든 조합, 5개 이하) 계산해 fps 충족 최저 전력 조합(★)과
   레버 간 상호작용(모두 적용 − 단독 합)을 표시합니다. **추천 레버 담기**는 이 variant에서 가능한 power option ·
   previous DMA · SBWC lossless · DVFS −1을 담습니다. IQ 평가가 필요한 레버는 표시되며, 전력 이득은 화질 평가 후 채택합니다.
4. 계산을 실행해 엔진이 산출한 timing·전력·BW와 구간별 여유를 확인합니다.
5. 제목, 목적, 상세 설명, 가정, 결론을 입력하고 개인 또는 공유 실험으로 저장합니다.

자연어 질문은 사내 LLM을 설정한 경우 사용할 수 있습니다. 질문과 선택한 variant의
대상 목록을 전달해 조건으로 해석하며, 계산 결과는 Timing Budget 엔진이 산출합니다.
모호한 질문은 선택지를 표시하고, 지원하지 않거나 잘못된 응답은 이유와 함께 알립니다.
사내 LLM이 없거나 응답하지 않으면 조건 편집기로 계산할 수 있습니다.
불러온 실험은 해당 모델 설정을 사용하며, 허용 범위를 벗어난 값과 알 수 없는
domain은 적용하지 않습니다. codec·EIS on/off·LLC 변경은 지원하지 않습니다.

DVFS level은 domain의 OPP를 고정하는 조건입니다. IP clock 하한과 달리 적용
clock을 낮출 수 있으며, 요구 clock보다 낮으면 timing 미달로 판정합니다.
한계 탐색은 각 domain을 독립적으로 한 단계씩 낮추며 첫 미달에서 멈춥니다.

선택한 scenario에 따라 변경 가능한 조건을 표시합니다. 크기 기준점이 없는
재생 등의 scenario는 같은 크기로 정의된 스트림 surface를 함께 변경하며
패널·표시 목적지 크기는 유지합니다. 모델에 반영되지 않는 설정은 제공하지
않으며, 공통 모델로 계산하는 플랫폼에는 검증 범위 안내를 표시합니다.

질문 해석과 임시 조건 적용은 API service에서 처리하고 기존 Timing Budget 엔진을
호출합니다. 기존 simulation 계산 모듈과 scenario 데이터는 수정하지 않습니다.

수동 clock 입력은 하한입니다. 요구 clock은 workload 계산값이고 적용 clock은 DVFS 단계·공유 domain 등을 반영한
값입니다. 크기를 줄여도 적용 clock이 유지될 수 있으므로 함께 확인합니다.
CPU·IP·메모리 BW power와 timing 결과도 기준 대비 변화로 표시합니다.

모델 합계는 포함한 성분의 합입니다. 빠진 성분과 고정한 가정이 표시되며, 전체
시스템 전력을 계산할 수 없으면 그 값을 비웁니다. 실측 SW runtime·clock·CPU profile을
다른 크기/FPS로 그대로 외삽하지 않습니다.

실험 저장은 공식 예측을 대체하지 않습니다. **조건 불러오기 · 재실행**으로 조건과
설명을 불러와 현재 입력으로 다시 비교할 수 있습니다.

## 예측에 설명과 검토 의견 남기기

**예측 현황**에서 결과를 선택하면 **실험 기록 · 검토 의견**에 제목, 검토 목적,
상세 설명, 가정·제약, 결론, 태그를 저장할 수 있습니다. 작성자·수정자·시각이
표시되고 댓글과 같은 예측에 대한 답글을 남길 수 있습니다. 설명 수정으로 계산
snapshot은 바뀌지 않습니다.

다른 사람이 설명을 먼저 수정하면 현재 초안을 유지한 채 최신 내용과 비교하도록
안내합니다. 최신 버전을 확인한 뒤 초안을 유지하거나 최신 내용으로 교체합니다.
예측 등록 화면도 검토한 기준 예측을 확인합니다. 다른 사용자가 먼저 등록했다면
새 예측과 비교하고 기준을 다시 확인한 뒤 등록합니다. 입력이 바뀌면 다시 계산합니다.

## 공유 환경에서 사용하기

**설정**에서 서버에 등록된 Key ID와 API 키를 입력하면 현재 화면 세션의 요청에
사용합니다. 키는 URL이나 브라우저 저장소에 저장하지 않습니다. 개인 실험은 해당
Key ID만 열람할 수 있고 공유 실험은 인증된 사용자에게 표시됩니다. 서버 역할에
따라 계산·댓글·설명 수정·예측 등록 권한이 적용됩니다.

새 테이블은 `alembic upgrade head`로 적용합니다. 검증은 격리된 PostgreSQL 테스트
DB에서 수행하며 운영 DB 반영은 기존 배포 절차를 따릅니다.

API 계약: [Scenario What-if](../contracts/api/scenario-whatif-contract.md),
[Architecture Analysis](../contracts/api/architecture-analysis-contract.md).

## 실측 · 예측 power popover

- Scenario 표의 **실측** 셀(날짜 · mW)을 클릭하면 측정 상세가 열립니다: 출처(실측 / 합성), 조건, total ± std · n · mA,
  fps · latency, CPU · IP · BW · 기타의 실측 대비 등록 예측 · 최신 simulation Δ, 비교 조건 동등성, rail 상위, SW task 상위.
  **예측 ↔ 실측 페이지에서 전체 보기**로 해당 측정이 선택된 Evidence 화면으로 이동합니다.
- Pipeline toolbar의 **⚡ 예측 · 실측 mW** chip은 등록 예측(구성 · BW · DVFS · timing 판정)과 대표 측정을 한 popover로 보여 줍니다.
