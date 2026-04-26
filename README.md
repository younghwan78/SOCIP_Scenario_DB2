# SOCIP Scenario DB

PostgreSQL-backed ScenarioDB prototype for Android SoC multimedia scenario review.

The current implementation focuses on four flows:

- YAML fixture ETL into PostgreSQL
- Canonical scenario resolver and review gate engine
- FastAPI read endpoints for scenario/runtime/view data
- Streamlit + Cytoscape pipeline viewer with Level 0/1/2 projections

## Repository Layout

```text
.
├── alembic/                    # PostgreSQL migrations
├── dashboard/                  # Streamlit viewer
├── demo/fixtures/              # Demo YAML data set
├── docs/                       # API, testing, deployment notes
├── scripts/                    # Utility scripts
├── src/scenario_db/            # Python package
│   ├── api/                    # FastAPI app, routers, response schemas
│   ├── db/                     # SQLAlchemy models and repositories
│   ├── etl/                    # YAML loader and DB mapper
│   ├── models/                 # Pydantic YAML models
│   ├── resolver/               # Scenario resolution logic
│   ├── review_gate/            # Review gate rules and issue matching
│   └── view/                   # Viewer projection service
└── tests/                      # Unit and integration tests
```

## Prerequisites

- Python 3.11+
- Docker Desktop, for local PostgreSQL
- `uv` is recommended, but the checked-in virtual environment workflow also works with `pip`

## Local Setup

Create or reuse a local virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pip install pytest httpx requests streamlit
```

If you use `uv`, the equivalent command is:

```powershell
uv sync --group dev --group dashboard
```

Start PostgreSQL:

```powershell
docker compose up -d
```

Apply migrations:

```powershell
$env:DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:5432/scenario_db"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Load demo fixtures:

```powershell
$env:DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:5432/scenario_db"
.\.venv\Scripts\python.exe -m scenario_db.etl.loader demo\fixtures
```

Run the API:

```powershell
$env:DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:5432/scenario_db"
.\.venv\Scripts\python.exe -m uvicorn scenario_db.api.app:app --host 127.0.0.1 --port 18000
```

Run the viewer:

```powershell
$env:SCENARIODB_API_BASE="http://127.0.0.1:18000/api/v1"
.\.venv\Scripts\python.exe -m streamlit run dashboard\Home.py --server.port 18502 --server.address 127.0.0.1
```

Open:

- API docs: `http://127.0.0.1:18000/docs`
- Viewer: `http://127.0.0.1:18502/Pipeline_Viewer`

## Test

Run the standard verification set from the virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_definition_models.py tests\unit\test_runtime_projection.py tests\integration\test_runtime_view_e2e.py
```

The current demo fixture covers:

- Camera recording UHD60 HDR10 H.265 scenario
- Level 0 architecture and SW task topology views
- Level 1 grouped IP detail DAG
- Level 2 drill-down for `camera`, `video`, and `display`
- Memory descriptors including format, compression, alignment, and LLC allocation
