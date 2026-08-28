# ScenarioDB API Status Codes

| Field | Value |
| --- | --- |
| Status | Current |
| Last verified | 2026-08-26 |
| Source | API routers, auth, exceptions, and operational guard tests |

| Status | Meaning in ScenarioDB |
| --- | --- |
| `200` | Successful read, validation, diff, run, or operation with response body |
| `201` | Resource or staged state created where declared by the route |
| `204` | Successful deletion with no body |
| `400` | Invalid cross-field request semantics or malformed composite reference |
| `401` | Protected endpoint has missing or invalid credentials |
| `403` | Authenticated principal lacks the required role |
| `404` | Requested entity or route is not present |
| `409` | State conflict, stale reviewed batch, or integrity conflict |
| `422` | Request/schema validation failed |
| `429` | Per-worker Simulation/Exploration admission capacity is full |
| `500` | Unexpected server failure; details must not leak secrets |
| `503` | Required DB/cache/config/dependency readiness is unavailable |

`501` is not used as a roadmap stub. Unimplemented routes are absent and therefore return `404`.
Future endpoints become part of the contract only when router code and tests are present.

## Health semantics

- `/health/live`: process liveness; it should not depend on optional business data.
- `/health/ready`: DB/cache and required runtime dependency readiness; returns `503` when the
  instance should not receive traffic.

For endpoint-specific error bodies, see the corresponding contract and tests.
