# Authoring layers 병합 리뷰

대상: c1dc6bd, c2f1954, 1967d36, cfd35cb, 09f104a, 131b5f6, 7b2ec73.
최종 의도는 Exynos2600 전체 reference 보존, Exynos2700 후면 녹화 KPI 범위 제한이다.

| 등급 | 위치 | 문제와 수정 |
| --- | --- | --- |
| P1 | authoring/cli.py | compile이 검증 전에 파일을 기록하고 sync가 검증 없이 덮어씀. 스키마/참조 검증 후에만 기록·prune |
| P1 | authoring/tree.py:decompile_fixture | 없는/잘못된 fixture나 상속 target에도 기존 docs부터 삭제함. source와 root target 사전 검증 |
| P2 | authoring/tree.py:write_docs | 중복 output path 발견 전에 일부 파일이 덮어써짐. 전체 경로 중복/범위 검사를 기록 전에 수행 |
| P2 | authoring/pipeline_ops.py | 제거한 부모를 patch로 교체해도 사전 dangling 검사에서 거부됨. patch 적용 후 검사 |
| P2 | 같은 파일 apply_overlay | scenario_patch의 $unset이 null 필드로 복원됨. 삭제한 key를 복원하지 않음 |
| P1 | etl/rename_ids.py | generated column까지 UPDATE에 포함하면 PostgreSQL이 이관을 거부함. generated column 제외 |
| P2 | 같은 파일 plan_renames | 여러 source가 없는 동일 target으로 수렴하면 적용 중 PK 충돌. 계획 단계에서 명시적으로 거부 |
| P1 | etl/rename_ids.py, retire.py | FK trigger를 끈 후 복구해도 기존 orphan은 재검증되지 않음. 모든 선언된 FK를 확인하고 오류 시 transaction rollback |
| P2 | ui/src/App.tsx | 서로 다른 variant 집합의 project 전환에서 source-only variant 또는 고정 preferred ID를 사용해 404. 대상 catalog의 실제 default 사용 |
| P2 | ui/src/lib/compare.ts | 기준 0인 KPI/DMA를 변화 0%로 표시. 비율 미정 표시 |
| P2 | ui/src/pages/Compare.tsx | flex 축소로 분석 요약과 출처 경고가 20px 정도로 잘림. 콘텐츠 높이를 유지 |
| P2 | ui/src/pages/Home.tsx | 프로젝트 선택이 table row로만 노출됨. 이름을 native button으로 제공해 키보드·보조기기 동작 보장 |

검증:
- React 79개, typecheck/build 및 API/브라우저 프로젝트 전환 회귀.
- PostgreSQL maintenance 회귀 4개: runtime evidence/derived column 보존, 멱등성, FK orphan 거부/rollback, variant별 retirement, 계획 충돌 거부.
- 별도 PostgreSQL: 이전 main fixture 로딩 → ID 변경 → retirement → 최신 strict ETL. 기존 evidence 92건 보존, 오류/경고 0.
- Exynos2600 13 scenarios / 212 variants (camera recording 75), Exynos2700 1 scenario / 19 variants.
- Playwright: 1280x600 Home 겹침 없음, 2600→2700 Pipeline 전환, cross-project Compare와 bcrop 즉석 simulation 성공, 분석 패널 전체 표시.
- 전체 단위/coverage와 quality/integration/react-ui/web CI는 최종 PR 커밋에서 확인 후 병합.

한계:
- 기존 runtime DB에는 이 리뷰에서 이관/retirement를 수행하지 않았다. 검증 DB와 서버는 임시이며 종료한다.
- rename/retire는 백업을 요구하는 관리 명령이고 자동 복원 도구가 아니다. rename 후 strict ETL로 canonical hash/fixture 정합성을 회복해야 한다.
- simulation 입력에는 sample/synthetic 값이 포함된다. 과제 간 수치 차이를 실리콘 실측 또는 조건을 통제한 인과 효과로 해석하지 않는다.
