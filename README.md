# SOCIP Scenario DB

PostgreSQL-backed ScenarioDB prototype for Android SoC multimedia scenario review.

The current implementation focuses on four flows:

- YAML fixture ETL into PostgreSQL.
- Canonical scenario resolver and review gate engine.
- FastAPI read endpoints for scenario, runtime, and viewer data.
- Streamlit + ELK/SVG pipeline viewer with Level 0/1/2 projections.

## Repository Layout

```text
.
├── alembic/                  # PostgreSQL migrations
├── dashboard/                # Streamlit viewer
├── demo/fixtures/            # Demo YAML data set
├── docs/                     # API, testing, deployment notes
├── scripts/                  # Utility scripts
├── src/scenario_db/          # Python package
│   ├── api/                  # FastAPI app, routers, response schemas
│   ├── db/                   # SQLAlchemy models and repositories
│   ├── etl/                  # YAML loader and DB mapper
│   ├── models/               # Pydantic YAML models
│   ├── resolver/             # Scenario resolution logic
│   ├── review_gate/          # Review gate rules and issue matching
│   └── view/                 # Viewer projection service
└── tests/                    # Unit and integration tests
```

## Prerequisites

- Python 3.11+
- Docker Desktop, for local PostgreSQL and integration tests
- `uv`

All commands below assume PowerShell and this working directory:

```powershell
cd E:\50_Codex_Soc_Scenario_DB\implementation
```

## Setup

Install dependencies into the project virtual environment:

```powershell
uv sync --group dev --group dashboard
```

If you prefer explicit `.venv` execution, the project-local Python is:

```powershell
.\.venv\Scripts\python.exe
```

## Database

Start PostgreSQL:

```powershell
docker compose up -d
```

Set the database URL for the current PowerShell session:

```powershell
$env:DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:5432/scenario_db"
```

Apply migrations:

```powershell
uv run alembic upgrade head
```

Load or reload demo fixtures:

```powershell
uv run python -m scenario_db.etl.loader demo\fixtures
```

Reload fixtures after changing YAML. The API reads from PostgreSQL, not directly from YAML.

## Run API

The FastAPI ASGI entry point is `scenario_db.api.app:app`.

```powershell
$env:DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:5432/scenario_db"
uv run uvicorn scenario_db.api.app:app --host 127.0.0.1 --port 18000
```

Open API docs:

```text
http://127.0.0.1:18000/docs
```

Quick API smoke check from another PowerShell:

```powershell
Invoke-RestMethod "http://127.0.0.1:18000/api/v1/scenarios/uc-camera-recording/variants/UHD60-HDR10-H265/view?level=0&mode=architecture"
```

## Run Viewer

Start the API first. Then open a new PowerShell and run:

```powershell
cd E:\50_Codex_Soc_Scenario_DB\implementation
$env:SCENARIODB_API_BASE="http://127.0.0.1:18000/api/v1"
uv run --group dashboard streamlit run dashboard\Home.py --server.port 18502 --server.address 127.0.0.1
```

Open:

```text
http://127.0.0.1:18502/Pipeline_Viewer
```

If `streamlit` is not found, run `uv sync --group dashboard` and retry.

## Viewer Check

Use the default scenario and variant:

```text
Scenario: uc-camera-recording
Variant:  UHD60-HDR10-H265
```

Check these views:

- `0 - Architecture + Task Topology`: Level 0 architecture should show App, Framework, HAL, Kernel, HW, and Memory. The task topology should be shown below it on the same page.
- `1 - IP Detail DAG`: grouped IP detail view using the fixture-backed task graph.
- `2 - Drill-Down`: selectable drill-down for `Camera pipeline`, `Video encode`, and `Display output`.

Important viewer notes:

- The viewer uses ELK.js and SVG rendering.
- Edges are routed as orthogonal lines.
- Memory descriptors include format, bitdepth, alignment, compression, and LLC placement.
- If fixture YAML changes, reload ETL and restart the API.

## Test

Run all unit tests:

```powershell
uv run --group dev pytest tests\unit
```

Run focused viewer/model tests:

```powershell
uv run --group dev pytest tests\unit\test_definition_models.py tests\unit\test_elk_viewer.py tests\unit\test_runtime_projection.py
```

Run integration tests only when Docker/PostgreSQL test containers are available:

```powershell
uv run --group dev pytest tests\integration
```

Equivalent explicit virtual environment commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit
.\.venv\Scripts\python.exe -m pytest tests\unit\test_definition_models.py tests\unit\test_elk_viewer.py tests\unit\test_runtime_projection.py
```

## Current Demo Coverage

- Camera recording UHD60 HDR10 H.265 scenario.
- Level 0 architecture overview with SW stack, HW path, and memory context.
- Level 0 SW task topology view.
- Level 1 grouped IP detail DAG.
- Level 2 drill-down for `camera`, `video`, and `display`.
- Review gate risk overlay from known issue matching.
- Memory descriptors and placement, including compression and LLC allocation.
