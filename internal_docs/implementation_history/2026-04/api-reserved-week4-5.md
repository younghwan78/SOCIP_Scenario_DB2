# 예약 엔드포인트 — Week 4/5 구현 예정

현재 모든 엔드포인트는 `501 Not Implemented`를 반환합니다.

## Week 4 예정

| Method | Path | 설명 |
|--------|------|------|
| `POST` | `/api/v1/variants/generate-yaml` | Variant 조건 → YAML 파일 export |
| `POST` | `/api/v1/scenarios/{sid}/variants` | Variant 신규 생성 (DB + YAML 동시) |
| `POST` | `/api/v1/admin/etl/trigger` | ETL 수동 트리거 (fixtures 재로딩) |

## Week 5 예정

| Method | Path | 설명 |
|--------|------|------|
| `POST` | `/api/v1/scenarios/{sid}/variants/{vid}/review` | Review gate 제출 — Triple-Track 서명 |

## 클라이언트 주의사항

- 현재 이 엔드포인트들을 호출하면 **501** 응답이 반환됩니다.
- 응답 바디: `{"error": "not_implemented", "detail": "Not implemented — scheduled for Week 4/5"}`
- 구현 완료 시 이 문서에서 해당 항목이 제거되고 `conventions.md`에 추가됩니다.
