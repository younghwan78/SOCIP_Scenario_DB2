# ScenarioDB Troubleshooting

| Field | Value |
| --- | --- |
| Status | Current |
| Last verified | 2026-08-26 |
| First checks | DB URL, PostgreSQL readiness, dependency groups, current fixture load |

## API does not start

Confirm `SCENARIO_DB_DATABASE_URL` or `DATABASE_URL` is present and points to PostgreSQL. Server
startup intentionally has no in-memory SQLite fallback. Verify migration state with
`uv run alembic current` and `uv run alembic heads`.

## `/health/ready` is not ready

Readiness covers DB/cache and required simulation dependencies. Install the `sim` group when
NetworkX or SimPy is missing:

```powershell
uv sync --group dev --group dashboard --group sim
```

Treat a missing simulation dependency as an environment error rather than hiding simulation UI.

## Viewer shows stale or missing fixture data

The viewer reads PostgreSQL, not YAML. Reload the intended fixture family with strict ETL, restart
the API, and reselect SoC -> Project/Board -> Scenario -> Variant. Do not mix fixture families with
global scenario ID collisions unless replacement/skip behavior is explicit.

## Viewer returns an unexpected Level 0 layout

Check that mode is one of `architecture`, `topology`, or `resource`. Verify the requested project,
scenario, variant, and optional evidence identity. A mismatched simulation evidence ID must be
rejected rather than displayed on another variant.

## Write apply is rejected as stale

Repeat validate and diff against the current base state, review the new snapshot, then apply. Do
not bypass the stale-review guard; it prevents applying a proposal that was not the one reviewed.

## Simulation or Exploration returns 429

The worker admission limit is full. Retry after the response delay or reduce parallel requests.
Increasing worker count also multiplies deployment-wide concurrency and memory/CPU demand; size
both together.

## ETL exits non-zero

Inspect the structured report under `output/etl`. In strict mode any skipped YAML or semantic
validation error rolls back the batch. Fix missing/unsupported kind, parse errors, cycles, broken
references, overlay references, or scenario/project collisions before retrying.

## Exported report is missing or mismatched

Run artifact reconciliation in dry-run mode first. Missing files, checksum mismatch, and orphan
HTML are reported for manual review. Cleanup should remove only a verified stale staging directory,
not evidence metadata or arbitrary report-root content.

## Logs are scattered

New runs should write only below `runtime_logs/<session-id>`. Generated HTML, JSON, YAML, benchmark,
and screenshots belong under `output/<area>/<run-id>`. Both are disposable and ignored by Git.

## LSP tooling fails with `lsap.capability.doc`

This is a local semantic-analysis tool installation problem, not a ScenarioDB import error. Use
file reads, `rg`, import-structure analysis, and real unit/CLI checks until the LSP package is fixed.
