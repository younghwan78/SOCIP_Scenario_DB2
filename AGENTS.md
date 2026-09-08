# Scenario DB coding instructions

## Scope and sources

- Run Git, Python, and backend commands from this directory (`implementation/`).
- This system turns YAML scenarios into PostgreSQL data and serves FastAPI,
  a React SPA (`web/`), and Streamlit/Workbench (`dashboard/`, `frontend/`).
- Use current code, tests, and `docs/README.md` for behavior and contracts.
  `internal_docs/README.md` indexes historical evidence; verify it before reuse.
- Read `docs/reference/agent-domain-rules.md` before changing ETL fixtures,
  viewer projections, or read APIs. Read only documentation relevant to the task.

## Working boundaries

- Inspect Git status before editing; preserve unrelated and uncommitted work.
- Use `.\.venv\Scripts\python.exe -m ...` or `uv run ...`; never system Python.
- Keep these reference repositories read-only:
  `E:\10_Codes\32_Multimedia_ScenarioDB`, `E:\10_Codes\23_MMIP_Scenario_simulation2`.
- Do not commit secrets, `.env`, `.venv`, logs, screenshots, caches, or database volumes.
- Runtime API and viewer checks require PostgreSQL and a configured
  `SCENARIO_DB_DATABASE_URL` or `DATABASE_URL`; do not substitute SQLite.
- Simulation features require `networkx` and `simpy`; report missing dependencies.
- Preserve board/project scoping and scenario/variant ownership of simulation evidence.

## Validation

- Run checks relevant to the changed behavior; add regression coverage for bug fixes.
  Documentation-only changes need link/content checks, not the application test suite.
- Backend: `uv run pytest <affected-test-path>`; use PostgreSQL integration tests
  for persistence/query changes. Run Ruff and mypy when applicable.
- `web/` (React SPA): run `npm test`, `npm run lint`, and `npm run build` there.
- `frontend/` (Workbench): run `npm test` and `npm run build` there;
  include rebuilt assets under `dashboard/components/workbench_frontend/component/`.
- Preserve Streamlit static serving for `dashboard/static/elk.bundled.js`.
- Fixture changes require strict ETL validation; reload ETL and restart the API
  before checking affected viewer behavior.
- Before reporting CI readiness, check `.github/workflows/ci.yml` for required
  gates, including frozen dependency sync and runtime dependency audit.
  Older testing documents may not reflect the current workflow.

## Communication

- Answer in Korean. State changes, verification results, and remaining limitations.
- For routine reversible choices, proceed within the requested scope.
  Ask only when missing information materially changes correctness or scope.
- Keep tool output focused; do not dump whole logs or repeat successful checks.
