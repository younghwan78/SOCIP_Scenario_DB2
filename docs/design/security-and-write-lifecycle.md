# Security and Write Lifecycle

| Field | Value |
| --- | --- |
| Status | Current |
| Last verified | 2026-08-26 |
| Primary code | `api/auth.py`, `api/resource_limits.py`, `write/service.py`, `reporting/` |
| Primary tests | `test_mutation_auth.py`, `test_operational_guards.py`, `test_write_state_safety.py` |

## 1. Security boundary

Mutation authentication is deny-by-default. `SCENARIO_DB_API_PRINCIPALS` configures server-side
principal secrets and roles. Secrets are represented as secret values and compared without
caller-controlled audit identity.

| Role | Accepted protected operations |
| --- | --- |
| `analyst` | Simulation and Exploration execution |
| `writer` | Analyst operations, Write flow, artifact export |
| `admin` | All protected operations, result deletion, admin cache refresh |
| `reader` | Reserved for deployments that authenticate reads at the proxy |

Read endpoints are not application-authenticated. A shared deployment must protect them with
network/reverse-proxy policy. The admin router is disabled unless explicitly enabled for a trusted
network. Local authentication bypass must never be enabled on a shared host.

## 2. Write state machine

```text
stage -> validate -> diff -> reviewed snapshot -> apply
```

- `stage` stores a proposed bundle or patch and a server-controlled actor.
- `validate` runs shape, graph, reference, identity, and surface-specific integrity checks.
- `diff` produces a semantic impact preview rather than trusting source file hashes alone.
- review records the exact validated/diffed snapshot.
- `apply` rejects a stale reviewed batch if payload, base state, or revision changed.
- apply uses canonical mappers and a DB transaction; it does not bypass ETL/write invariants.

Import Workbench uses this same flow. A UI button is not authorization and must not be the only
place where validation or confirmation is enforced.

## 3. Cache consistency

Decision-rule and query-facet caches are per process. Write apply invalidates the affected cache
state; rule-cache TTL bounds multi-worker staleness. A deployment with multiple workers must size
TTL and worker count together and must not assume process-local cache is globally synchronous.

## 4. Resource controls

Simulation and Exploration have per-worker, non-blocking admission semaphores. Architecture Query,
timeline, graph, transfer, workload, request serialization, and sweep case counts have positive,
startup-validated bounds. Rejection is explicit (`429` for admission pressure, validation errors
for oversized inputs) rather than silent truncation.

These controls protect the current synchronous API. Long-running or cross-worker workloads require
a durable queue and distributed quota design; that is not implemented by increasing current
limits.

## 5. Artifact safety

Report paths are resolved below the configured report root. Unique staging/generation directories,
atomic publication, checksums, relative metadata, and dry-run reconciliation prevent a caller from
turning report export or cleanup into arbitrary filesystem access.

Cleanup is intentionally narrow. It may remove an explicitly identified stale staging directory;
missing files, checksum mismatches, and orphans remain visible for operator review.

## 6. Deployment responsibilities

The repository does not embed a company IdP, object store, ACL, internal URL, certificate, or
production secret. Staging/production must supply those values, restrict network exposure, manage
backup/restore, and validate rollback. Use synthetic fixtures until an approved internal handoff
authorizes other data.

See [Write API Contract](../contracts/api/write-api-contract.md),
[Write API Runbook](../operations/write-api-runbook.md), and
[Ubuntu Deployment](../operations/deployment-ubuntu.md).
