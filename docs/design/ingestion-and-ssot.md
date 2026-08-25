# Ingestion and PostgreSQL Single Source of Truth

| Field | Value |
| --- | --- |
| Status | Current |
| Last verified | 2026-08-26 |
| Primary code | `src/scenario_db/etl`, `src/scenario_db/db`, `src/scenario_db/integrity_checks.py` |
| Primary tests | `tests/unit/test_etl_*`, `tests/integration/test_etl_*` |

## 1. Authority boundary

Canonical YAML is the authored and interchange representation. After loading, PostgreSQL is the
runtime authority. API, viewer, query, resolver, review, and simulation flows read database rows
or repositories built from them; they do not silently switch to YAML when the DB is empty.

The supported local sources are synthetic fixtures under `demo/fixtures`,
`db_fixtures_Exynos2600_S26Plus`, examples, and test fixtures. Legacy adapters may read a
separately supplied fixture root, but real company data is outside the repository boundary.

## 2. Canonical document kinds and load order

`etl.loader` dispatches by top-level `kind` and loads FK dependencies in this order:

1. `soc`, `soc.dvfs_table`, `soc.cdgm_profile`
2. `ip`, `sw_profile`, `sw_component`
3. `project`, `scenario.usecase`
4. `evidence.simulation`, `evidence.measurement`
5. `decision.gate_rule`, `decision.issue`, `decision.waiver`, `decision.review`

Unsupported or missing kinds are always reported. A scenario data-flow cycle is rejected before
mapping; feedback must be represented as a `control` edge.

## 3. Transaction and strictness semantics

Each file mapper runs in a nested transaction/SAVEPOINT so non-strict bulk loading can report a
bad file while preserving valid files. Post-load validation checks project/scenario/variant/IP,
evidence, issue, waiver, review, and overlay references.

`--strict` changes the batch outcome: any skipped document or validation error rolls back the
outer session and exits non-zero. `--report-json` writes a structured report under `output/`.

```powershell
uv run python -m scenario_db.etl.loader demo\fixtures `
  --strict `
  --report-json output\etl\demo-report.json
```

Scenario IDs are global. On a scenario/project collision, the default is error. Replacement or
skip must be explicit through the corresponding CLI switch; silent reassignment is forbidden.

## 4. Storage design

Stable identity, relationship, timestamp, and query-filter fields are relational columns.
Heterogeneous capability details, pipeline graphs, variant overlays, evidence breakdowns, and
lineage use PostgreSQL JSONB. Promoted/generated columns and indexes support frequently filtered
fields without flattening every evolving payload.

The current schema is evolved only through Alembic revisions. ORM model changes and migration
changes must be reviewed together. A new JSONB metric does not automatically require a migration;
a new promoted/indexed field or relational invariant usually does.

See [Data and Storage](data-and-storage.md) for the detailed relational/JSONB mapping.

## 5. Ingestion paths

### Direct canonical ETL

Use for reviewed canonical fixture trees. It is deterministic, dependency ordered, and supports
strict rollback.

### Legacy fixture conversion

`scenario_db.legacy_import` converts a separately supplied legacy fixture shape into canonical
YAML plus `import_report.json`. Generated canonical files are reviewed before loading. The
repository does not modify the legacy source tree.

### Import Workbench and Write API

The Workbench builds `scenario.import_bundle`, then uses the same authenticated
`stage -> validate -> diff -> apply` flow as other writes. It does not become another truth
source and must not bypass mapper or integrity validation.

### Measurement import

`scenario_db.meas_import` normalizes supported summary inputs into
`evidence.measurement`. Raw traces and logs stay outside PostgreSQL; evidence stores digests,
lineage, artifact references, and comparable metric observations.

## 6. Validation ownership

| Layer | Catches |
| --- | --- |
| Pydantic canonical model | Shape, enum, forbidden extras, edge references, inheritance cycles |
| ETL pre-map checks | Missing/unsupported kind, YAML parse errors, data-flow cycles |
| Mapper/DB | FK, unique, check constraints, upsert semantics |
| Post-load validator | Cross-document references and overlay integrity |
| Write validation | Payload-specific semantic errors and reviewed snapshot |
| Contract tests | Stable accepted/rejected behavior across entry points |

## 7. Maintenance rule

When adding a document kind or field, update the canonical model, mapper, persistence decision,
fixtures, validation, tests, and the relevant contract together. Do not document a future field
as supported until the loader and validation path accept it.
