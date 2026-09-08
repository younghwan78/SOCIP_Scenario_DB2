# ETL and viewer rules for coding agents

Read this file when changing fixtures, viewer projections, or read APIs.
These rules were moved from AGENTS.md to keep startup instructions concise.
For current endpoint contracts, start at [API contracts](../contracts/api/README.md).

## ETL Notes

- Auxiliary YAML that is not an ETL document (no `kind`) must be listed in
  `<fixtures>\.etlignore` (glob per line) so `--strict` runs stay green.
- Validate `db_fixtures_Exynos2600_S26Plus` with `--strict` when editing it;
  do not infer current validity from earlier successful loads.
- Pipeline edges support optional `port_pairs` (`- src: <WDMA/port>` /
  `dst: <RDMA/port>`); they drive the WDMA→RDMA edge labels and Level 2
  module-direct routing in the viewer.

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

## Local runtime reference

- Default ports: FastAPI `18000`, Streamlit `18502`, PostgreSQL `15432`,
  pgAdmin `15050` on `127.0.0.1`. Check current configuration before starting services.
- Read [Maintenance Guide](../operations/maintenance-guide.md) for setup.
- Configure `SCENARIO_DB_DATABASE_URL` or `DATABASE_URL` from the local environment;
  do not copy credentials into instructions or reports.
- When environment setup is needed: `uv sync --frozen --group dev --group dashboard --group sim`.
- Apply migrations when required: `uv run alembic upgrade head`.
- Strict ETL example: `uv run python -m scenario_db.etl.loader demo/fixtures --strict --report-json output/etl-report.json`.
- API: `uv run --group sim uvicorn scenario_db.api.app:app --host 127.0.0.1 --port 18000`.
- Streamlit: `uv run --group dashboard --group sim streamlit run dashboard/Home.py --server.port 18502 --server.address 127.0.0.1`.
