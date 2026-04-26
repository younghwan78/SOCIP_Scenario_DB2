# API Naming Conventions — ScenarioDB

## URL 구조 원칙

| 규칙 | 예시 | 비고 |
|------|------|------|
| 복수형 + hyphen | `/soc-platforms`, `/sw-profiles` | 모든 리소스 |
| Mass noun 예외 | `/evidence` | 단수 유지 |
| Variant composite key | `/scenarios/{sid}/variants/{vid}` | sid 없이 단독 접근 금지 |
| Global variant 조회 | `/variants` | 필터 전용 (sid 없음) |
| Cross-scenario 비교 | `/compare/variants?ref1={sid}::{vid}&ref2=...` | `::` 구분자 |

## 필터 파라미터

| 패턴 | 예시 | 의미 |
|------|------|------|
| 단순 일치 | `?severity=critical` | = 연산 |
| feature_flag | `?feature_flag=LLC_per_ip_partition:enabled` | JSONB 쿼리 |
| 만료 기간 | `?expiring_within_days=90` | 오늘부터 N일 이내 |
| 페이지네이션 | `?limit=50&offset=0` | 기본 50, 최대 1000 |

## 페이지네이션

모든 목록 엔드포인트는 `PagedResponse` 반환:

```json
{
  "items": [...],
  "total": 42,
  "limit": 50,
  "offset": 0,
  "has_next": false
}
```

- 기본 `limit`: 50
- 최대 `limit`: 1000 (초과 시 자동 클램핑)

## 엔드포인트 전체 목록

### Capability (`/api/v1/`)
```
GET  /soc-platforms
GET  /soc-platforms/{id}
GET  /ip-catalog           ?category=ISP|MFC|DPU|GPU|LLC
GET  /ip-catalog/{id}
GET  /sw-profiles          ?feature_flag=name:value
GET  /sw-profiles/{id}
GET  /sw-components        ?category=hal|kernel|firmware
```

### Definition (`/api/v1/`)
```
GET  /projects
GET  /projects/{id}
GET  /scenarios
GET  /scenarios/{id}
GET  /scenarios/{sid}/variants
GET  /scenarios/{sid}/variants/{vid}
GET  /variants/{sid}/{vid}/matched-issues       ← P1 핵심
GET  /variants                                  ?project=&severity=&tag=
```

### Evidence (`/api/v1/`)
```
GET  /evidence/summary     ?groupby=sw_version_hint,overall_feasibility
GET  /evidence             ?scenario_ref=&variant_ref=&sw_version=&feasibility=
GET  /evidence/{id}
GET  /compare/evidence     ?variant=&sw1=&sw2=
GET  /compare/variants     ?ref1={sid}::{vid}&ref2={sid}::{vid}
```

### Decision (`/api/v1/`)
```
GET  /reviews
GET  /reviews/{id}
GET  /issues               (캐시 우선)
GET  /issues/{id}
GET  /waivers              ?expiring_within_days=90
GET  /waivers/{id}
GET  /gate-rules           (캐시 우선)
```

### Utility
```
GET  /health
POST /api/v1/admin/cache/refresh
POST /api/v1/variants/generate-yaml            → 501 (Week 4)
POST /api/v1/scenarios/{sid}/variants          → 501 (Week 4)
POST /api/v1/scenarios/{sid}/variants/{vid}/review → 501 (Week 5)
POST /api/v1/admin/etl/trigger                 → 501 (Week 4)
```
