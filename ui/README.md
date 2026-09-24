# ScenarioDB UI (React)

React 18 + Vite + TypeScript front-end for the Scenario DB FastAPI (`/api/v1`). Replaces the Streamlit explorer/viewer/compare pages; Streamlit remains for Evidence and Import.

## Run

```bash
# 1) API (repo root)
uvicorn scenario_db.api.app:app --port 18000
# 2) UI
cd ui
npm install
npm run dev          # http://localhost:3000  (/api → http://127.0.0.1:18000)
```

- API target override: `SCENARIODB_API_TARGET=http://host:port npm run dev`
- Static build: `npm run build` → `dist/` (set `VITE_SCENARIODB_API_BASE` if the API is not served under `/api/v1` on the same origin)
- Checks: `npm run typecheck`, `npm test` (vitest)

## Pages (hash routes, shareable)

| Route | Content |
|---|---|
| `#/explorer` | Scenario type pills → scenario list (description) → variant table vs. reference (medoid / parent), facets, select → Pipeline / Compare |
| `#/matrix` | All-scenario variant matrix, grouped by scenario, normalized columns |
| `#/pipeline` | ELK orthogonal graph (buffers as separate nodes, IP groups, external sensor/panel), lens Topology / DMA / Transform, concurrent subsystems, Perfetto-style timing linked to graph, DMA table |
| `#/compare` | N-way compare, column per variant: conditions, DMA transfers, KPI Δ%, prediction vs. measurement |

`Ctrl K`: variant picker (Mode = KPI/Pro Video/Slow motion/Portrait/None, Camera = rear wide/tele/UW/front/dual; Enter = open, Shift+Enter = add to compare, ★ = pin).

## Layout

- `src/lib/` — api client, condition normalization, graph build/ELK layout, timeline model, routing
- `src/components/` — GraphView, TimelineView, Picker
- `src/pages/` — Explorer, Matrix, Pipeline, Compare
- `tests/` — vitest (conditions, graph orthogonality, timeline/route)
