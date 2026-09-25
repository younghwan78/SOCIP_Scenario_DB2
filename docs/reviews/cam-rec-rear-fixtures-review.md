# Rear camera fixture 리뷰

원본 `356cf39`와 `6c8b85a`의 생성기, simulation/measurement YAML, UI 합성 표시와 Home canvas 수정을 검토했다.
선행 Home PR의 리뷰 수정도 유지한다.

| 등급 | 위치 | 영향과 수정 |
| --- | --- | --- |
| P1 | `scripts/generate_rear_recording_evidence.py:main` | 첫 실행에서 제외한 infeasible simulation을 재실행하면 합성 실측 생성 가능. 저장된 feasibility/accepted 결과도 검사 |
| P2 | 같은 파일 `find_sim` | 파일 이름 순으로 소스를 선택. run_info.timestamp로 최신 소스 선택 |
| P2 | 같은 파일 `main` | variant별 생성 실패를 출력하고 exit 0. 오류가 있으면 exit 1 |
| P2 | 생성기 및 합성 YAML 33건 | 측정 시간은 3×30초인데 task/latency 표본은 180초 분량. 90초로 통일 |
| P1 | `api/services/library.py`, `ui/src/pages/Library.tsx` | 합성 SW timing을 실측 표에 provenance 없이 노출. API synthetic flag와 눈에 보이는 합성 badge 추가 |
| P2 | `ui/src/pages/Calibration.tsx` | URL의 측정 선택이 현재 범위/실제 측정 필터 밖이어도 남음. 현재 표시 목록 안에서만 선택 |

검증: 관련 Python 23개와 React 64개, typecheck/build 통과.
새 PostgreSQL에 전체 fixture strict ETL 성공(오류·경고·skip 0).
API에서 합성 33건과 SW timing provenance/표본 수 전달을 확인했다.
총 simulation 58건, measurement 34건(실측 1 + 합성 33)을 적재했다.

합성 데이터는 silicon 검증 근거가 아니며 기존 실제 측정을 덮어쓰지 않는다.
전력/clock과 고속 batch 모델의 기존 가정은 유지한다. 최종 4개 CI 성공 후 병합한다.
