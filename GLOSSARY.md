# ScenarioDB

SoC multimedia 동작 조건, 계산 결과와 측정 근거를 연결해 프로젝트의 성능·전력 검토를 지원한다.
같은 variant 이름도 scenario가 다르면 별개의 대상이다.

## Language

**Project**:
보드와 제품 조건을 공유하는 검토 범위. Scenario의 소유 프로젝트와 측정·비교 근거의 프로젝트를 구분한다.

**Scenario**:
특정 use case를 수행하는 처리 흐름과 공통 조건.

**Variant**:
Scenario에 속한 구체적인 동작 조건. 식별은 scenario와 variant의 쌍으로 이루어진다.

**Evidence**:
측정 또는 simulation의 결과와 출처를 연결한 근거. 합성 측정이나 모델 예측을 물리 측정의 검증 결과로 간주하지 않는다.

**Prediction**:
Variant의 검토 기준으로 등록한 계산 결과. 탐색 과정의 추천값과 구분한다.
_Avoid_: 미등록 추천값을 prediction이라고 부르기

**Report snapshot**:
검토보고서 생성 당시의 근거, 판정과 설명을 고정한 기록. 이후 현재 prediction이나 측정 자료가 바뀌어도 기존 보고서의 내용을 바꾸지 않는다.
_Avoid_: 현재 상태 조회

**Representative measurement**:
정해진 범위의 여러 capture 중 비교에 사용하는 하나의 측정 근거. 선택되었다는 사실이 모든 KPI의 완결성이나 silicon 검증을 뜻하지는 않는다.
_Avoid_: 항상 최신 측정, 항상 물리 측정

**CPU analysis run**:
계산 당시 조건에 따라 수행한 CPU 분석과 이에 연결된 비교·SW growth 계산. 이후 편집한 조건과 이미 계산된 결과의 조건을 구분한다.

**What-if baseline**:
한 What-if 요청에서 변경 후보를 해석하고 비교하는 기준 조건과 계산 결과. 저장 요청에서는 당시의 현재 입력으로 다시 확인한다.
