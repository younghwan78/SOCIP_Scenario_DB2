# ScenarioDB API Naming Conventions

| Field | Value |
| --- | --- |
| Status | Current |
| Last verified | 2026-08-26 |
| Source | `src/scenario_db/api/routers/` |

## URL rules

- Resource collections use plural, hyphenated nouns: `/soc-platforms`, `/ip-catalogs`.
- Mass nouns may remain singular: `/evidence`.
- Scenario-local variants use `/scenarios/{scenario_id}/variants/{variant_id}`.
- Global variant lookup uses `/variants` with explicit filters.
- Cross-variant references use `{scenario_id}::{variant_id}` where the endpoint contract requires it.
- Health endpoints are unversioned: `/health/live`, `/health/ready`.
- Versioned application endpoints use `/api/v1`.

## Query and pagination

- Collection defaults are endpoint-specific but use `limit` and `offset`.
- `sort_by` is validated against allowed model columns; callers cannot supply raw SQL.
- `sort_dir` is `asc` or `desc`.
- Board-aware reads use explicit `soc_ref`, `project_ref`, and `board_type` filters.
- Variant matrix axis keys describe the full filtered set, not one page.

Paged responses use:

```json
{
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0,
  "has_next": false
}
```

## Errors

Handled application errors use a stable machine-readable error and detail payload. Validation
errors may carry structured detail. Authentication status distinguishes missing/invalid identity
from insufficient role. Do not expose secrets, raw exception internals, or server paths.

## Source of endpoint inventory

Do not maintain a duplicated Week-based endpoint list here. Use the running FastAPI
`/openapi.json` or `/docs`, then consult [API Contract Index](../contracts/api/README.md) for
semantic contracts.
