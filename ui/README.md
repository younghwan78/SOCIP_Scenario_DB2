# ScenarioDB UI (React)

React 18 + Vite + TypeScript front-end for the Scenario DB FastAPI (`/api/v1`). Provides Explorer, Pipeline and Compare alongside the existing Streamlit pages. Streamlit remains available for Evidence and Import.

## Run

Use Node.js 24 (matching CI) and a configured PostgreSQL API.

```bash
# 1) API (repo root)
uv run uvicorn scenario_db.api.app:app --host 127.0.0.1 --port 18000
# 2) UI
cd ui
npm ci
npm run dev          # http://localhost:3000  (/api → http://127.0.0.1:18000)
```

- API target override: `SCENARIODB_API_TARGET=http://host:port npm run dev`
- Static build: `npm run build` → `dist/` (set `VITE_SCENARIODB_API_BASE` if the API is not served under `/api/v1` on the same origin)
- Checks: `npm run typecheck`, `npm test` (vitest), `npm run build`, `npm audit`
- CI checks this application in `react-ui`; `web` checks the existing Workbench.
- DMA sizes use decimal MB and the declared sample bit depth (P010/P210 use 16-bit containers). Compressed/aligned buffers without an explicit byte size are excluded from the traffic estimate. This is a partial model estimate, not measured DRAM traffic.
- Timing preserves the recorded durations and frame IDs. Sensor-to-output latency requires an explicit predecessor path to a sensor; unlinked frame numbers do not establish latency.

## Pages (hash routes, shareable)

| Route | Content |
|---|---|
| `#/` | Home — brand click. Canvas 2D pipeline fly-through (generic stage roles, IP names only as examples; Camera / Video / Display), SSO placeholder, status links. Honors `prefers-reduced-motion`, pauses on hidden tab |
| `#/explorer` | Scenario type pills → scenario list (description) → variant table vs. reference (medoid / parent), facets, select → Pipeline / Compare |
| `#/matrix` | All-scenario variant matrix, grouped by scenario, normalized columns |
| `#/pipeline` | ELK orthogonal graph (buffers as separate nodes, IP groups, external sensor/panel), lens Sequence / DMA / IP 내부 (IP connection map coloured by voltage domain or BLK → click for ports, page scroll only), concurrent subsystems, Perfetto-style timing linked to graph, DMA table |
| `#/compare` | N-way compare, column per variant: conditions, DMA transfers, KPI Δ%, prediction vs. measurement |
| `#/timing` · `#/timing-fleet` | Stage timing budget of one variant / all variants of a scenario |
| `#/predictions` | Current power/BW prediction per variant, change vs. previous and cause |
| `#/explore` · `#/reports` | Architecture exploration runs · review reports |
| `#/calibration` | 예측 ↔ 실측: CPU / IP / BW(MIF·DRAM) / 기타 split of measured rails vs. current prediction and simulation evidence, rail table, SW task 실측 |
| `#/library` | Tabs `ip` · `dvfs` · `comp` · `sensor` · `sw` (param `tab`): input catalogs and their source/assumed status |
| `#/settings` | 설정 · 기존 도구 (Streamlit links, base `VITE_STREAMLIT_BASE`), API status, reset `sdb.*` preferences |

Sidebar groups: 탐색 · 예측 · Architecture · Library; 설정 at the bottom. Sidebar colors are `--sd-*` tokens in `styles.css` (map to the company design system later).

`Ctrl K`: variant picker (Mode = KPI/Pro Video/Slow motion/Portrait/None, Camera = rear wide/tele/UW/front/dual; Enter = open, Shift+Enter = add to compare, ★ = pin).

## Screen layout

- Sidebar: drag the edge to resize, `Ctrl+B` collapses to an icon rail
- Every page = top (toolbar/filters, ▴ collapse, drag to resize) · main · bottom tabs (`Ctrl+J`, drag to resize)
- Pipeline: `나란히 | Pipeline | Timing`, drag the divider between Pipeline and Timing
  - Graph: wheel = scroll, Ctrl+wheel/pinch = zoom at cursor, drag = pan, double-click empty area = fit all; 폭 / 전체 buttons
  - Timing: wheel = tracks scroll, Ctrl+wheel = zoom at cursor, drag or Shift+wheel = pan, W/S/A/D
- Sizes and modes persist per browser (localStorage)

## Source layout

- `src/lib/` — api client, condition normalization, graph build/ELK layout, timeline model, routing
- `src/components/` — GraphView, TimelineView, Picker, DataTable, PipelineTunnel
- `src/pages/` — Home, Explorer, Matrix, Pipeline, Compare, TimingBudget, Predictions, Explore, Reports, Calibration, Library, Settings
- `tests/` — vitest (conditions, graph orthogonality, timeline/route, timing budget, arch pages, home/library/calibration helpers)
