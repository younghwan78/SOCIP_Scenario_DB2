# UX review 6 리뷰

원본 `0d509c3`의 Home 현황, scenario 분류, Pre/Post-NRT 연결도를 검토했다.

- P2 `ui/src/lib/topology.ts`: 병렬 경로의 전역 rank 비교로 NRT 선행 작업이 Post-NRT로 오분류됨. 실제 의존 관계를 탐색하도록 수정하고 길이가 다른 분기 회귀 테스트 추가.
- P2 `ui/src/styles.css`: 높이가 작은 넓은 화면에서 절대 배치된 Home 카드와 확장된 현황 dock이 겹침. 문서 흐름과 스크롤을 사용하도록 수정.
- coverage-summary는 evidence 건수 대신 variant 수를 반환하는지 PostgreSQL에서 중복 simulation 및 실측/합성 분리 검증.

검증: React 70개 및 typecheck, PostgreSQL calibration 통합 1개 통과. 최종 quality/integration/react-ui/web CI가 통과한 커밋만 병합한다.
