# AGENTS.md

## Project Context

This repository is the implementation root for `SOCIP Scenario DB`.

Primary goal:

- Convert authored YAML scenario data into a PostgreSQL-backed single source of truth.
- Resolve scenario variants against HW/SW capability data.
- Run review-gate checks before project reuse.
- Serve viewer-ready projections through FastAPI.
- Render Level 0/1/2 multimedia pipeline views in Streamlit/Cytoscape.

## Working Rules

- Treat `implementation/` as the repository root.
- Always run Python commands through `.\.venv\Scripts\python.exe`.
- Do not commit `.venv`, `.env`, local logs, generated screenshots, cache folders, or PostgreSQL data volumes.
- Keep old reference codebases read-only:
  - `E:\10_Codes\32_Multimedia_ScenarioDB`
  - `E:\10_Codes\23_MMIP_Scenario_simulation2`
- Prefer fixture-backed tests before UI-only changes.

## Useful Commands

```powershell
$env:DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:5432/scenario_db"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m scenario_db.etl.loader demo\fixtures
.\.venv\Scripts\python.exe -m pytest tests\unit\test_definition_models.py tests\unit\test_runtime_projection.py tests\integration\test_runtime_view_e2e.py
```

## Viewer Defaults

- Level 0: architecture lane view plus SW task topology view.
- Level 1: grouped IP detail DAG.
- Level 2: selectable drill-down for `camera`, `video`, and `display`.
- Keep memory descriptor and memory placement separate. Compression and LLC allocation are different concepts.

