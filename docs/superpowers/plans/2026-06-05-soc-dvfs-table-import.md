# SoC DVFS Table Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add first-class `soc.dvfs_table` data so DVFS versions are a SoC-scoped independent sequence and EVT remains metadata.

**Architecture:** Store DVFS tables in a new `soc_dvfs_tables` table keyed by document id with a unique `(soc_ref, dvfs_version)` constraint. Extend canonical YAML, direct ETL, Write API import bundles, simulation lookup, evidence provenance, and Import Workbench helpers around the same staged `stage -> validate -> diff -> apply` workflow.

**Tech Stack:** SQLAlchemy ORM, Alembic, Pydantic v2, FastAPI schemas/routers, Streamlit helpers, pytest.

---

### Task 1: Canonical Model And DB Table

**Files:**
- Modify: `src/scenario_db/models/common.py`
- Modify: `src/scenario_db/models/capability/hw.py`
- Modify: `src/scenario_db/db/models/capability.py`
- Modify: `src/scenario_db/db/models/__init__.py`
- Create: `alembic/versions/0008_soc_dvfs_tables.py`
- Test: `tests/unit/test_capability_models.py`

- [ ] Add failing tests for `dvfs-...` document ids and `soc.dvfs_table` model validation.
- [ ] Add Pydantic `SocDvfsTable` with `soc_ref`, `dvfs_version`, `evt_hint`, `source`, `domains`, and optional `compatibility_scope`.
- [ ] Add ORM `SocDvfsTable` and Alembic table with unique `(soc_ref, dvfs_version)`.

### Task 2: ETL And Import Bundle

**Files:**
- Modify: `src/scenario_db/etl/mappers/capability.py`
- Modify: `src/scenario_db/etl/loader.py`
- Modify: `src/scenario_db/legacy_import/validate_generated.py`
- Modify: `src/scenario_db/legacy_import/write_bundle.py`
- Modify: `src/scenario_db/write/service.py`
- Test: `tests/unit/test_write_service.py`
- Test: `tests/unit/test_legacy_import_write_bundle.py`

- [ ] Add failing tests that `scenario.import_bundle` accepts `soc.dvfs_table`, diffs it, and applies it.
- [ ] Register `soc.dvfs_table` in direct ETL and bundle collection.
- [ ] Add import validation for referenced SoC and duplicate `(soc_ref, dvfs_version)` documents.

### Task 3: Simulation Lookup And Provenance

**Files:**
- Modify: `src/scenario_db/api/schemas/simulation.py`
- Modify: `src/scenario_db/sim/service.py`
- Modify: `src/scenario_db/models/evidence/common.py`
- Test: `tests/unit/sim/test_service_hash.py`

- [ ] Add failing tests that request hash changes by `dvfs_table_ref` or `dvfs_version` and that `evt_hint` is metadata.
- [ ] Let simulation requests provide either raw `dvfs_tables` or DB lookup via `soc_ref + dvfs_version` / `dvfs_table_ref`.
- [ ] Store `dvfs_table_ref`, `dvfs_version`, and `evt_hint` in `execution_context`.

### Task 4: Read API And Workbench Helpers

**Files:**
- Modify: `src/scenario_db/api/schemas/capability.py`
- Modify: `src/scenario_db/api/routers/capability.py`
- Modify: `dashboard/components/import_api_client.py`
- Modify: `dashboard/pages/6_Import_Workbench.py`
- Test: `tests/unit/test_import_workbench_client.py`

- [ ] Add DVFS table list/detail API.
- [ ] Add helper to build `scenario.import_bundle` payloads for one DVFS table document.
- [ ] Add Import Workbench DVFS update mode using the same stage/validate/diff/apply controls.

### Task 5: Docs And Verification

**Files:**
- Modify: `docs/db-data-guide.md`
- Modify: `docs/write-api-contract.md`
- Modify: `docs/write-api-runbook.md`

- [ ] Document `soc.dvfs_table`, SoC-scoped `dvfs_version`, and `evt_hint` metadata.
- [ ] Run focused unit tests.
- [ ] Run broader affected unit tests.
