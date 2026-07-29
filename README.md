# SOCIP Scenario DB

PostgreSQL-backed ScenarioDB prototype for Android SoC multimedia scenario review.

The current implementation focuses on these flows:

- YAML fixture ETL into PostgreSQL.
- Canonical scenario resolver and review gate engine.
- FastAPI read endpoints for scenario, runtime, and viewer data.
- Streamlit + ELK/SVG pipeline viewer with Level 0/1/2 projections.
- Write API staging flow for variant overlays and base pipeline patches.
- Scenario/variant simulation for BW, power, timing, and persisted evidence overlays.

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
│   ├── sim/                  # BW, power, DVFS, and timing simulation
│   ├── view/                 # Viewer projection service
│   └── write/                # Write staging, validation, diff, apply services
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
docker compose up -d postgres
```

Set the database URL for the current PowerShell session, or keep the same value
in a local `.env` file. Alembic, the API, and ETL loader all accept
`SCENARIO_DB_DATABASE_URL` with higher priority and fall back to `DATABASE_URL`.

```powershell
$env:DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:15432/scenario_db"
```

Apply migrations:

```powershell
uv run alembic upgrade head
```

Load or reload demo fixtures:

```powershell
uv run python -m scenario_db.etl.loader demo\fixtures --strict --report-json output\etl-report.json
```

Reload fixtures after changing YAML. The API reads from PostgreSQL, not directly from YAML.
For a practical map of required and optional DB data, see
[docs/db-data-guide.md](docs/db-data-guide.md).

Scenario IDs are global in the current schema. If two fixture sets contain the
same scenario id under different projects, the default ETL policy rejects the
incoming conflicting scenario instead of silently moving it between projects.
Load into a clean database when switching fixture families, or make replacement
explicit:

```powershell
uv run python -m scenario_db.etl.loader db_fixtures_Exynos2600_S26Plus --replace-scenario-project-collisions
```

Use `--skip-scenario-project-collisions` only when you intentionally want to
keep the existing scenario owner and ignore conflicting incoming YAML.

## Run API

The FastAPI ASGI entry point is `scenario_db.api.app:app`.

```powershell
$env:DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:15432/scenario_db"
$env:SCENARIO_DB_MUTATION_API_KEYS='{"architect@example.com":"replace-with-a-long-random-secret"}'
uv run uvicorn scenario_db.api.app:app --host 127.0.0.1 --port 18000
```

Read endpoints remain available without credentials. Write staging, simulation
execution/export/delete, and admin endpoints require both
`X-ScenarioDB-Key-Id` and `X-ScenarioDB-API-Key`. The key ID becomes the
server-controlled audit actor; a caller-supplied `actor` cannot override it.
If no server keys are configured, mutation requests fail closed with HTTP 503.
`SCENARIO_DB_MUTATION_AUTH_DISABLED=true` is an explicit local-test bypass and
must not be enabled in a shared or production environment.

Configure dashboard-side credentials separately in the dashboard process:

```powershell
$env:SCENARIODB_API_KEY_ID="architect@example.com"
$env:SCENARIODB_API_KEY="replace-with-a-long-random-secret"
```

If you want to launch FastAPI in a background PowerShell window, set the
environment variable in the parent shell and let `Start-Process` inherit it.
Avoid building a double-quoted command such as
`"$env:DATABASE_URL='...'; uv run ..."` because PowerShell expands
`$env:DATABASE_URL` before the child process starts.

```powershell
$env:DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:15432/scenario_db"
Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-Command",
  "uv run uvicorn scenario_db.api.app:app --host 127.0.0.1 --port 18000"
)
```

Open API docs:

```text
http://127.0.0.1:18000/docs
```

Quick API smoke check from another PowerShell:

```powershell
Invoke-RestMethod "http://127.0.0.1:18000/api/v1/scenarios/uc-camera-recording/variants/UHD60-HDR10-H265/view?level=0&mode=resource"
Invoke-RestMethod "http://127.0.0.1:18000/api/v1/scenarios/uc-camera-recording/variants/UHD60-HDR10-H265/view?level=0&mode=topology"
```

Board-aware Read API filters:

```powershell
$api="http://127.0.0.1:18000/api/v1"
Invoke-RestMethod "$api/soc-platforms?limit=100"
Invoke-RestMethod "$api/projects?soc_ref=soc-exynos2500&board_type=ERD"
Invoke-RestMethod "$api/scenarios?project_ref=proj-demo-import"
Invoke-RestMethod "$api/variants?scenario_id=uc-demo-import-recording"
```

Base scenario view is available even when a scenario has no variants:

```powershell
Invoke-RestMethod "$api/scenarios/uc-demo-import-recording/view?level=0&mode=resource"
```

Optional query/cache settings:

```powershell
$env:SCENARIO_DB_QUERY_FACETS_CACHE_TTL_SECONDS="60"
```

`/api/v1/query/facets` uses this short TTL cache when the value is greater than
0. Write apply invalidates it automatically. If you load YAML directly through
`python -m scenario_db.etl.loader`, either wait for the TTL or enable the
internal admin endpoint in a trusted local/VPN environment and refresh caches:

```powershell
$env:SCENARIO_DB_ADMIN_ENDPOINTS_ENABLED="true"
Invoke-RestMethod -Method Post "$api/admin/cache/refresh"
```

The admin endpoint refreshes the current API process. With multiple uvicorn
workers, restart the API or refresh each worker through the operational entry
point you expose.

## Write API

The write targets are `scenario.variant_overlay`, `scenario.pipeline_patch`, and
`scenario.import_bundle`. All use a staged flow:

```text
stage -> validate -> diff -> apply
```

Use variant overlay writes to add or update a single variant without directly
mutating the base scenario topology. Use pipeline patch writes only when the
base `pipeline.nodes`, `pipeline.edges`, or `pipeline.buffers` must change for
the entire scenario and all variants. Use import bundle writes to review and
apply canonical YAML generated by the legacy importer.

Run a valid sample:

```powershell
$api="http://127.0.0.1:18000/api/v1"
$mutationHeaders = @{
  "X-ScenarioDB-Key-Id" = "architect@example.com"
  "X-ScenarioDB-API-Key" = "replace-with-a-long-random-secret"
}
$payload = Get-Content .\demo\write_payloads\variant_overlay_valid.json -Raw
$stage = Invoke-RestMethod -Method Post -Uri "$api/write/staging" -Headers $mutationHeaders -ContentType "application/json" -Body $payload
$batchId = $stage.batch_id
Invoke-RestMethod -Method Post -Uri "$api/write/staging/$batchId/validate" -Headers $mutationHeaders
Invoke-RestMethod -Method Post -Uri "$api/write/staging/$batchId/diff" -Headers $mutationHeaders
Invoke-RestMethod -Method Post -Uri "$api/write/staging/$batchId/apply" -Headers $mutationHeaders
```

Inspect the result:

```powershell
Invoke-RestMethod "$api/scenarios/uc-camera-recording/variants/FHD30-SDR-H265-runbook"
Invoke-RestMethod "$api/scenarios/uc-camera-recording/variants/FHD30-SDR-H265-runbook/graph"
```

Run a base pipeline patch sample:

```powershell
$payload = Get-Content .\demo\write_payloads\pipeline_patch_valid.json -Raw
$stage = Invoke-RestMethod -Method Post -Uri "$api/write/staging" -Headers $mutationHeaders -ContentType "application/json" -Body $payload
$batchId = $stage.batch_id
Invoke-RestMethod -Method Post -Uri "$api/write/staging/$batchId/validate" -Headers $mutationHeaders
$diff = Invoke-RestMethod -Method Post -Uri "$api/write/staging/$batchId/diff" -Headers $mutationHeaders
$diff.impact
Invoke-RestMethod -Method Post -Uri "$api/write/staging/$batchId/apply" -Headers $mutationHeaders
```

Pipeline patch diff includes an `impact` block that shows whether existing
variant overlays would become stale after the base change.

More examples are in [docs/write-api-runbook.md](docs/write-api-runbook.md).
The write contract is in [docs/write-api-contract.md](docs/write-api-contract.md).

## Import Workbench

The Import Workbench is a Streamlit helper for this flow:

```text
generated canonical YAML -> scenario.import_bundle -> stage -> validate -> diff -> apply
```

It is not a direct DB editor. It builds a Write API payload from a generated
canonical YAML directory, shows `import_report.json`, stages the payload, and
displays validation and diff impact before apply.

Start the dashboard, then open:

```text
http://127.0.0.1:18502/Import_Workbench
```

CLI equivalent for building the bundle:

```powershell
uv run python -m scenario_db.legacy_import.write_bundle `
  --generated demo\generated\scenariodb `
  --out demo\generated\scenariodb\import_bundle.json `
  --actor legacy-importer `
  --note "demo import" `
  --strict
```

The repo includes `demo\generated\scenariodb` as a small generated-output
example for Workbench smoke testing. Real importer output should be generated
into a separate working directory.

After `Apply to DB`, the Workbench shows `Open in Viewer` links for applied
scenarios/variants. The link passes `soc_id`, `project_id`, `scenario_id`, and
`variant_id` query parameters to the Viewer so imported data can be inspected
without manually copying IDs.

## Run Viewer

Start the API first. Then open a new PowerShell and run:

```powershell
cd E:\50_Codex_Soc_Scenario_DB\implementation
$env:SCENARIODB_API_BASE="http://127.0.0.1:18000/api/v1"
uv run --group dashboard streamlit run dashboard\Home.py --server.port 18502 --server.address 127.0.0.1
```

Background launch follows the same rule: set the environment variable in the
parent shell or use a single-quoted child command.

```powershell
$env:SCENARIODB_API_BASE="http://127.0.0.1:18000/api/v1"
Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-Command",
  "uv run --group dashboard streamlit run dashboard\Home.py --server.port 18502 --server.address 127.0.0.1 --server.headless true"
)
```

Open:

```text
http://127.0.0.1:18502/Pipeline_Viewer
```

The home page also links to `Pipeline Viewer` and `Import Workbench`.

If `streamlit` is not found, run `uv sync --group dashboard` and retry.

The Viewer selector is hierarchical:

```text
SoC Platform -> Project / Board -> Scenario -> Variant -> View Level
```

Use `Project / Board` to separate board form-factor conditions under the same
SoC, for example `ERD`, `SEP1`, and `SEP2`. Project metadata can carry
`board_type`, `board_name`, `sensor_module_ref`, `display_module_ref`, and
`default_sw_profile_ref`. If a scenario has no variants, the Viewer loads the
base scenario pipeline through `/api/v1/scenarios/{scenario_id}/view`.

## Simulation Evidence Dashboard

Start PostgreSQL, reload fixtures, run the API, and run the Streamlit dashboard
as shown above. Then open:

```text
http://127.0.0.1:18502/Evidence_Dashboard
```

The Evidence Dashboard runs scenario/variant simulation as a preview first.
Only results confirmed with `Confirm & Save Evidence` are persisted as
`evidence.simulation` rows in PostgreSQL. The simulation currently
calculates:

- IP power from `capabilities.sim.modes` unit power and PPC parameters.
- DMA bandwidth and bandwidth power, including size, format, bitwidth,
  compression, and LLC fields in the result table.
- HW timing and optional SW/HW timeline events, including resource wait,
  M2M/OTF token delay, multi-frame timing, and critical-path markers when
  timeline inputs provide those constraints.
- Sensor source timing from `sensor_fps` and `v_valid_ms`, plus display sink
  timing from panel refresh/scanout metadata when sensor/panel catalog entries
  are available.
- DVFS-selected clock/voltage breakdowns.
- Optional debug calculation traces that explain formula inputs,
  intermediate values, and final KPI values.

The left sidebar selects the simulation context:

```text
SoC Platform -> Project / Board -> Scenario Category -> Scenario -> Variant
```

The run form provides selectable silicon revision, SW baseline, and thermal
bucket. Silicon revision defaults to the common bring-up labels `EVT0` and
`EVT1`, and includes `EVT1.3` for Exynos2600 final silicon. Use `Custom` for
other minor revisions. Thermal buckets are sent with an `ambient_temp_c` value:

```text
normal ~= 25C ambient
hot    ~= 85C chamber
cold   ~= -20C chamber
```

The DVFS Tables JSON field is prefilled with a default table shape. Domain keys
should match IP `dvfs_group` values such as `CAM`, `CSIS`, `INTCAM`, and `INT`.
Enable `Debug calculation trace` when you need to audit how power, current,
bandwidth, DVFS, HW timing, and timeline summary values were derived.

Preview results appear above `Simulation Results` and are not saved to DB until
confirmed. Persisted results are shown in `Simulation Results`. `Open Pipeline Viewer
Overlay` opens the Pipeline Viewer in a new browser tab and passes the selected
SoC, project, scenario, variant, API base, and simulation evidence id as query
parameters. The original Evidence Dashboard state remains in place. Use
`Download JSON`, `Download KPI CSV`, `Download DMA CSV`, or the `Report` tab
downloads to copy selected simulation evidence into a separate report,
spreadsheet, or baseline archive.

The `Report` tab generates three legacy-style HTML artifacts from the stored
`evidence.simulation` row, lets you select one of them for inline preview, and
keeps browser-local downloads available:

- `{prefix}_timing_chart.html`
- `{prefix}_bw_chart.html`
- `{prefix}_simulation_result.html`

`Download Selected HTML` saves the currently previewed artifact through the
browser. `Download All as ZIP` saves all three HTML artifacts through the
browser without writing server-side files. Saved evidence also exposes an
advanced `API server local save` section that writes the same bundle on the API
host. The default API-host directory is `output_simulation`; override it with
`SCENARIO_DB_REPORT_DIR` or with a relative export request body such as
`projectA`. Absolute custom export paths are rejected by default; enable
`SCENARIO_DB_ALLOW_CUSTOM_REPORT_DIR=true` only for trusted local environments.
The saved-evidence ZIP endpoint remains available for scripts:

```text
GET /api/v1/simulation/results/{evidence_id}/artifacts/download.zip
```

Simulation API examples:

```powershell
$api="http://127.0.0.1:18000/api/v1"
$mutationHeaders = @{
  "X-ScenarioDB-Key-Id" = "architect@example.com"
  "X-ScenarioDB-API-Key" = "replace-with-a-long-random-secret"
}

$payload = @{
  scenario_id = "uc-camera-recording"
  variant_id = "cam-rec-f1-fhd30"
  execution_context = @{
    silicon_rev = "EVT0"
    sw_baseline_ref = "sw-vendor-v1.2.3"
    thermal = "normal"
    ambient_temp_c = 25
  }
  config = @{
    asv_group = 4
    include_timeline = $true
    debug_trace = $true
    debug_trace_level = "formula"
  }
  dvfs_tables = @{}
  persist = $false
  force = $false
} | ConvertTo-Json -Depth 20

$run = Invoke-RestMethod -Method Post -Uri "$api/simulation/run" -Headers $mutationHeaders -ContentType "application/json" -Body $payload
$run.evidence_id
$run.evidence.calculation_trace.kpi | ConvertTo-Json -Depth 20

# Save only after reviewing the preview.
$savePayload = $payload | ConvertFrom-Json
$savePayload.persist = $true
$saved = Invoke-RestMethod -Method Post -Uri "$api/simulation/run" -Headers $mutationHeaders -ContentType "application/json" -Body ($savePayload | ConvertTo-Json -Depth 20)
Invoke-RestMethod "$api/simulation/results/$($saved.evidence_id)" | ConvertTo-Json -Depth 20

# Export legacy-style local HTML artifacts on the API host.
$exportPayload = @{
  project_ref = "projectA"
  variant_name = "FHD30 Recording"
  output_dir = "projectA"
  overwrite = $true
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post `
  -Uri "$api/simulation/results/$($saved.evidence_id)/artifacts/export" `
  -Headers $mutationHeaders `
  -ContentType "application/json" `
  -Body $exportPayload

# Download the same three HTML artifacts as a ZIP without server-side file writes.
Invoke-WebRequest `
  -Uri "$api/simulation/results/$($saved.evidence_id)/artifacts/download.zip?project_ref=projectA&variant_name=FHD30+Recording" `
  -OutFile ".\projectA-FHD30_Recording_html_report_bundle.zip"
```

Simulation evidence is not an unbounded append log for identical inputs. The
run request computes a `params_hash` from the effective simulation inputs,
execution context, run config, and DVFS tables. It reuses a matching persisted
result unless `force=true`. Execution control flags such as `persist` and
`force` are excluded from the hash. Distinct scenario/variant, thermal/SW
context, config, or DVFS inputs create distinct evidence ids. Use
`persist=false` for a temporary run that returns the calculated result without
saving it to DB. Debug trace flags are also excluded from the hash; if a
confirmed evidence row exists without a requested trace, the API recomputes the
same result and updates that evidence with `calculation_trace` when
`persist=true`.

## Viewer Check

Use the default scenario and variant:

```text
Scenario: uc-camera-recording
Variant:  UHD60-HDR10-H265
```

Check these views:

- `0 - Resource + Topology`: Level 0 should show the Scenario Resource Overview first, then the Level 0 - Topology Overview graph below it. The resource overview summarizes active resources, buffer handoffs, sensor/display endpoint details, and subsystem power/BW metrics when simulation overlay data is loaded.
- `1 - IP Detail DAG`: grouped IP detail view using the fixture-backed task graph.
- `2 - Drill-Down`: selectable drill-down for `Camera pipeline`, `Video encode`, and `Display output`.

Important viewer notes:

- The viewer uses ELK.js and SVG rendering.
- Edges are routed as orthogonal lines.
- Memory descriptors include format, bitdepth, alignment, compression, and LLC placement.
- Level 0 API consumers should use `level=0&mode=resource` for tables and
  `level=0&mode=topology` for the buffer-aware graph. `mode=architecture`
  remains available for legacy callers.
- If fixture YAML changes, reload ETL and restart the API.

## Test

Run all unit tests:

```powershell
uv run --group dev pytest tests\unit
```

Run focused viewer/model tests:

```powershell
uv run --group dev pytest tests\unit\test_definition_models.py tests\unit\test_elk_viewer.py tests\unit\test_runtime_projection.py tests\unit\test_viewer_api_client.py
```

Run integration tests only when Docker/PostgreSQL test containers are available:

```powershell
uv run --group dev pytest tests\integration
```

Run Write API focused tests:

```powershell
uv run --group dev pytest tests\unit\test_write_service.py tests\integration\test_write_api.py
```

Run simulation focused tests:

```powershell
uv run --group dev --group sim pytest tests\unit\sim tests\unit\api\test_simulation.py
```

Run a core module coverage baseline without changing the default test gate:

```powershell
uv run --group dev pytest tests\unit --cov=scenario_db --cov-report=term-missing
```

The current read-side contract is documented in [docs/read-api-contract.md](docs/read-api-contract.md). Update that file and the related tests before changing Read API response shapes.

Equivalent explicit virtual environment commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit
.\.venv\Scripts\python.exe -m pytest tests\unit\test_definition_models.py tests\unit\test_elk_viewer.py tests\unit\test_runtime_projection.py
```

## Current Demo Coverage

- Camera recording UHD60 HDR10 H.265 scenario.
- Level 0 Scenario Resource Overview with active IP/resource rows, buffer handoffs, endpoint details, and subsystem metric summary.
- Level 0 active topology overview with explicit buffer handoff nodes.
- Level 1 grouped IP detail DAG.
- Level 2 drill-down for `camera`, `video`, and `display`.
- Review gate risk overlay from known issue matching.
- Memory descriptors and placement, including compression and LLC allocation.
- Write API examples for variant overlay, derived variants, routing switch, SW task injection, base pipeline patch, and validation failures.
