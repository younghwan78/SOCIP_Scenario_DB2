# AGENTS.md

## Project Context

This repository is the implementation root for `SOCIP Scenario DB`.

Primary goal:

- Convert authored YAML scenario data into a PostgreSQL-backed single source of truth.
- Resolve scenario variants against HW/SW capability data.
- Run review-gate checks before project reuse.
- Serve viewer-ready projections through FastAPI.
- Render Level 0/1/2 multimedia pipeline views in Streamlit with ELK.js/SVG.
- Support board/form-factor scoped projects under the same SoC, such as
  `ERD`, `SEP1`, and `SEP2`.

## Working Rules

- This file lives in the repository root. Run repo commands from this directory
  unless a task explicitly targets parent-level planning documents.
- Always run Python commands through the project virtual environment.
- Preferred explicit form: `.\.venv\Scripts\python.exe -m ...`.
- `uv run ...` is also acceptable from `implementation/` because it uses the project environment.
- Do not commit `.venv`, `.env`, local logs, generated screenshots, cache folders, or PostgreSQL data volumes.
- Keep old reference codebases read-only:
  - `E:\10_Codes\32_Multimedia_ScenarioDB`
  - `E:\10_Codes\23_MMIP_Scenario_simulation2`
- Prefer fixture-backed tests before UI-only changes.

## Server Assumptions

- Server startup must have a real database URL. Use `SCENARIO_DB_DATABASE_URL`
  or `DATABASE_URL`; do not rely on an in-memory SQLite fallback.
- PostgreSQL is the runtime database for API, Streamlit, query, and viewer checks.
- `networkx` and `simpy` are required server dependencies for simulation-backed
  features. Treat missing packages as an environment error, not as a degraded
  mode that should be hidden from users.
- Default local service ports are FastAPI `127.0.0.1:18000`, Streamlit
  `127.0.0.1:18502`, PostgreSQL `127.0.0.1:15432`, and pgAdmin
  `127.0.0.1:15050`.

## Useful Commands

```powershell
$env:SCENARIO_DB_DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:15432/scenario_db"
$env:DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:15432/scenario_db"
uv sync --group dev --group dashboard --group sim
uv run alembic upgrade head
uv run python -m scenario_db.etl.loader demo\fixtures
uv run --group sim uvicorn scenario_db.api.app:app --host 127.0.0.1 --port 18000
uv run --group dashboard --group sim streamlit run dashboard\Home.py --server.port 18502 --server.address 127.0.0.1
uv run --group dev --group sim pytest tests\unit
```

## Viewer Defaults

- Viewer selection should follow this hierarchy:
  `SoC Platform -> Project / Board -> Scenario -> Variant -> View Level`.
- Treat `Project` as the board/form-factor boundary. Store board-specific
  conditions in project metadata, including `board_type`, `board_name`,
  `sensor_module_ref`, `display_module_ref`, and `default_sw_profile_ref`.
- Scenarios may have no variants. In that case, use the base scenario view
  endpoint rather than forcing a dummy variant.
- Level 0: architecture overview plus SW task topology view on one vertically scrollable page.
- Level 0 modes are `architecture`, `topology`, and `resource`. Other modes
  should fail validation instead of falling back silently.
- Level 1: grouped IP detail DAG, aligned with the legacy ELK view style.
- Level 2: selectable drill-down for `camera`, `video`, and `display`.
- Keep memory descriptor and memory placement separate. Compression and LLC allocation are different concepts.
- If viewer fixture YAML changes, reload ETL and restart the API.

## Read API Notes

- Use board-aware filters before adding ad-hoc dashboard filtering:
  - `/projects?soc_ref=...&board_type=...`
  - `/scenarios?project_ref=...&soc_ref=...&board_type=...`
  - `/variants?scenario_id=...&project=...&soc_ref=...&board_type=...`
- Variant view endpoint: `/scenarios/{scenario_id}/variants/{variant_id}/view`.
- Base scenario view endpoint: `/scenarios/{scenario_id}/view`.
- A requested `sim_evidence_id` must belong to the requested scenario and
  variant. Do not overlay unrelated simulation evidence onto a view.
- Variant matrix pagination should not change the reported design-axis keys;
  compute axis keys from the full filtered result set, not only the current page.
