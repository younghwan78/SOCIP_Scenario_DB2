# ScenarioDB Production Hardening Design

## Scope and boundary

This design describes the current code contract for API authorization,
synchronous compute admission, and local simulation-report artifacts. The
repository and its tests use synthetic fixtures and public-code-derived data.
No company identity provider, object store, secret, ACL, or internal URL is
embedded here. SSO/OIDC, deployment-wide distributed quotas, and company object
storage remain environment-specific integration work.

## Authentication and authorization

`SCENARIO_DB_API_PRINCIPALS` is the preferred server-side JSON configuration:

```json
{
  "analyst@example.com": {"secret": "...", "roles": ["analyst"]},
  "architect@example.com": {"secret": "...", "roles": ["writer"]},
  "operator@example.com": {"secret": "...", "roles": ["admin"]}
}
```

Secrets are parsed as `SecretStr` and compared in constant time. Authentication
failures return 401, missing server configuration returns 503, and an
authenticated principal without a required role receives 403.

| Operation | Minimum accepted role |
| --- | --- |
| Simulation and Exploration execution | `analyst`, `writer`, or `admin` |
| Write staging/validation/diff/apply | `writer` or `admin` |
| Artifact export | `writer` or `admin` |
| Simulation evidence deletion | `admin` |
| Admin cache refresh | `admin` |

Read endpoints remain unauthenticated by the application and require
reverse-proxy/network policy. `reader` is reserved for that future integration.
`SCENARIO_DB_MUTATION_API_KEYS` remains a deprecated, availability-preserving
migration path and grants all protected-operation roles. The explicit local
authentication bypass grants all roles and must not be enabled on a shared
host.

## Compute resource controls

Simulation and Exploration use per-process, non-blocking admission semaphores.
When a worker is full, the API returns 429 with `Retry-After: 1`; requests do
not wait while holding a web worker indefinitely. Because admission is
per-process, deployment capacity is the configured limit multiplied by the
worker count.

The API rejects oversized Exploration request serialization, excessive
timeline frame counts, and simulation graphs exceeding configured workload,
transfer, task, or edge counts. Sweep compilers calculate the Cartesian
product before materializing cases and reject expansion beyond the case limit.
All bounds are positive startup-validated settings. These controls protect a
synchronous service; a durable distributed queue is still required if future
workloads need long-running or cross-worker scheduling.

## Artifact lifecycle

An export has one unique `generation_id`. Files are fully written and flushed
inside `.scenariodb-staging-{generation_id}`, then the directory is atomically
renamed to `{prefix}/{generation_id}`. Readers therefore see either no
generation or the complete three-file bundle.

Each DB metadata item contains:

- a generation-scoped `artifact_id`;
- a report-root-relative POSIX path;
- SHA-256, byte length, MIME type, creation time, prefix, and generator.

No API response or DB metadata created by this flow contains a host absolute
path. A DB commit failure rolls back the session and removes only the new unique
generation. A process crash between filesystem publication and DB commit can
leave an orphan; it cannot create metadata pointing to a partially published
bundle.

`scenario-db-reconcile-artifacts` compares simulation evidence metadata with
the configured local report root. Dry-run is the default and reports invalid
paths, missing files, checksum mismatches, orphan HTML, and stale staging
directories. Apply mode is deliberately limited to stale staging directories;
it never automatically deletes orphan reports or mutates DB metadata.

Custom report directories are an explicit trusted-local escape hatch. Their
paths are still hidden from metadata, but they are outside configured-root
reconciliation and should remain disabled in production.

## Verification contract

Every hardening stage is committed independently. The release gate runs the
full unit and PostgreSQL integration suites, Ruff, configured mypy targets,
coverage, dependency audit, build, and repository diff checks. GitHub branch
protection requires the `quality` and `integration` checks before merge.

사내 환경 검증과 최종 승인 기록은
[사내 Staging 검증 및 Main Merge 체크리스트](internal-staging-merge-checklist-ko.md)를
사용한다.
