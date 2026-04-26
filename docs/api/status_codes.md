# HTTP Status Code 정책 — ScenarioDB API

## 응답 코드

| Code | 의미 | 발생 상황 |
|------|------|---------|
| **200** | OK | GET 성공 |
| **201** | Created | POST 성공 (Week 2+) |
| **204** | No Content | DELETE 성공 (Week 3+) |
| **400** | Bad Request | 파라미터 형식 오류, whitelist 위반 |
| **404** | Not Found | 리소스 없음 (`NoResultFound`) |
| **409** | Conflict | 중복 키 충돌 (`IntegrityError`) |
| **422** | Unprocessable Entity | Pydantic/FastAPI 스키마 검증 실패 |
| **500** | Internal Server Error | 예상치 못한 서버 오류 |
| **501** | Not Implemented | Week 4/5 예약 stub |
| **503** | Service Unavailable | DB 연결 불가 (`/health` degraded 상태) |

## Error Response 표준 포맷

모든 오류 응답은 아래 구조를 따릅니다:

```json
{
  "error": "not_found",
  "detail": "Variant 'uc-camera/UHD60' not found"
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `error` | `string` | 오류 코드 (스네이크 케이스) |
| `detail` | `string \| list` | 사람이 읽을 수 있는 설명 (422는 list) |

## 오류 코드 목록

| `error` 값 | HTTP Code | 원인 |
|-----------|-----------|------|
| `not_found` | 404 | DB에 해당 ID 없음 |
| `conflict` | 409 | 유니크 키 중복 |
| `validation_error` | 422 | 요청 파라미터/바디 스키마 오류 |
| `bad_request` | 400 | whitelist 위반, 잘못된 형식 |

## `/health` 상태 필드

```json
{
  "status": "ok | degraded",
  "version": "0.1.0",
  "uptime_s": 12.5,
  "db": "connected | unreachable",
  "rule_cache": {
    "loaded": true,
    "issues": 3,
    "gate_rules": 2,
    "error": null
  }
}
```

`status: "degraded"` 시 서버는 계속 동작하나 DB 의존 엔드포인트는 503 반환 가능.
