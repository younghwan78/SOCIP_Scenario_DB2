# Project Memory

This file records repo-local implementation decisions and current state. It is not the Codex internal memory store.

## 2026-04-26 Viewer Direction

- The viewer moved from Cytoscape-style rendering toward ELK.js/SVG because SoC block diagrams need readable orthogonal routing, hierarchy groups, and professional topology/detail diagrams.
- The legacy reference project `E:\10_Codes\23_MMIP_Scenario_simulation2` remains read-only and is used as the visual behavior reference.
- The current renderer lives in `dashboard/components/elk_viewer.py`.
- The FastAPI view projection still returns `ViewResponse`; the Streamlit renderer adapts that response into an ELK graph.

## Current Viewer Behavior

- Level 0 shows architecture overview and SW task topology on one vertically scrollable page.
- Level 0 architecture should include `App`, `Framework`, `HAL`, `Kernel`, `HW`, and `Memory`.
- Memory is treated as first-class review context and should appear below HW in the overview.
- Topology, Level 1, and Level 2 should stay close to the legacy ELK visual style.
- Edges should be orthogonal and should not be hidden behind group/layer backgrounds.
- HW-to-HW summary edges are kept at Level 0 even when buffer-specific edges are also shown.

## Fixture Decisions

- Demo data is loaded from `demo/fixtures`.
- The main demo scenario is `uc-camera-recording` with variant `UHD60-HDR10-H265`.
- Fixture view data is stored under `pipeline` as JSON-compatible YAML:
  - `buffers`
  - `architecture_graph`
  - `task_graph`
  - `level1_graph`
- Buffer data should include format, bitdepth, planes, size reference, alignment, compression, and memory placement.
- LLC placement must remain separate from compression.

## Commands

Run API:

```powershell
uv run uvicorn scenario_db.api.app:app --host 127.0.0.1 --port 18000
```

Run viewer:

```powershell
$env:SCENARIODB_API_BASE="http://127.0.0.1:18000/api/v1"
uv run --group dashboard streamlit run dashboard\Home.py --server.port 18502 --server.address 127.0.0.1
```

Run unit tests:

```powershell
uv run --group dev pytest tests\unit
```

## Recent Local Commits

- `71c6a42 Add ELK viewer rendering`
- `de327fc Align viewer fixture with legacy ELK layout`
