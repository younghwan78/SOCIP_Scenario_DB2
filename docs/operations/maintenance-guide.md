# ScenarioDB Maintenance Guide

| Field | Value |
| --- | --- |
| Status | Current |
| Last verified | 2026-08-26 |
| Working directory | `implementation/` |
| Data boundary | Synthetic fixtures only in repository/local validation |

## 1. Standard environment

Run commands from the implementation root and through the project environment.

```powershell
uv sync --group dev --group dashboard --group sim
uv run alembic upgrade head
uv run --group dev --group sim pytest tests\unit
```

PostgreSQL is required for runtime and integration paths. Set
`SCENARIO_DB_DATABASE_URL` or `DATABASE_URL`; do not introduce an in-memory SQLite fallback for
server startup. Local default ports are documented in `AGENTS.md` and the main README.

## 2. Change workflow

1. Identify the contract and source-of-truth code affected.
2. Add or update the narrowest failing/contract test.
3. Make the smallest implementation change.
4. Update canonical `docs` in the same change.
5. Reload fixtures/migrate DB when persistence changed.
6. Run focused tests, then the relevant regression suite.
7. Run `git diff --check` and review generated/ignored artifacts before commit.

Do not mix unrelated formatting or historical-document cleanup into a behavior change.

## 3. Persistence and migrations

- Create an Alembic revision for relational columns, constraints, indexes, or promoted fields.
- Keep ORM model, migration, ETL mapper, API schema, and tests aligned.
- Verify a single expected Alembic head.
- Test upgrade against a disposable PostgreSQL DB before shared staging.
- Never edit an already-deployed revision to represent a new change.
- Define backup/restore and rollback handling before an irreversible data migration.

## 4. Fixture maintenance

Canonical fixture changes require strict ETL and usually API/view smoke tests.

```powershell
uv run python -m scenario_db.etl.loader demo\fixtures `
  --strict `
  --report-json output\etl\demo-report.json
```

Keep project/board scope explicit. Do not copy real project IDs, company paths, measurement files,
ACLs, or credentials into demo fixtures. When a viewer fixture changes, reload ETL and restart the
API so PostgreSQL and process-local caches reflect it.

## 5. Contract maintenance matrix

| Changed area | Required checks |
| --- | --- |
| Read API | schema/router tests, dashboard client, read contract |
| Write API | auth, state safety, stale review, diff/apply, write contract/runbook |
| ETL/model | model, mapper, strict rollback, post-load validation, migration if needed |
| Simulation | readiness, resource bounds, numerical unit tests, evidence schema |
| Measurement/comparison | catalog, unit/statistic, lineage, dashboard coverage |
| Viewer | mode validation, semantic/golden projection, dashboard regression |
| Reporting | path safety, atomic export, checksum, reconciliation dry-run |
| Deployment config | startup validation, Ubuntu guide, operational guard tests |

## 6. Runtime output policy

Only two disposable roots are used:

- `runtime_logs/<session-id>/`: API/Streamlit stdout and stderr
- `output/<area>/<run-id>/`: ETL reports, compiled recipes, benchmark output, HTML, QA captures

Do not create `.codex_run_logs`, `.runlogs`, `.runtime`, `logs`, or root-level `*.log` again.
Keep only the last five sessions or seven days locally. A long-lived audit artifact belongs in an
approved evidence store, referenced by run ID and commit SHA, after redaction.

Before cleanup, list resolved targets and confirm they remain below the implementation root.
Cleanup scripts should support dry-run and should never recursively target the workspace root.

The repository cleanup helper is dry-run by default:

```powershell
.\scripts\cleanup_runtime_outputs.ps1
.\scripts\cleanup_runtime_outputs.ps1 -Apply
```

Permission-locked `pytest-cache-files-*` directories are excluded by default. They can be listed
with `-IncludePytestTemp`, but ownership/ACL repair is an administrator decision and is not
performed by the cleanup helper.

## 7. Documentation maintenance

- `docs`: current system contract and repeatable operations.
- `internal_docs`: dated implementation history, investigations, validations, release checklists.
- Remove Week/Phase roadmap statements from current reference documents.
- Add `Status` and `Last verified` to new canonical documents.
- Preserve historical documents; do not rewrite old plans to look current.
- Run a local Markdown-link check after moves or renames.

## 8. Release readiness

At minimum, verify clean dependency install, Alembic head/upgrade, unit tests, affected integration
tests, strict fixture ETL, API readiness, dashboard smoke, artifact reconciliation dry-run, and
rollback ownership. Shared staging approval uses the internal release checklist without recording
secrets or real identity values in Git.
