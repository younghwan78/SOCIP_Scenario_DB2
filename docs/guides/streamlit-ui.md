# Streamlit UI and archived SPA

The default UI is the existing Streamlit Dashboard with the embedded Scenario Workbench. The review SPA introduced by `feat/modern-web-spa` is preserved remotely on [archive/modern-web-spa-is-v15](https://github.com/younghwan78/SOCIP_Scenario_DB2/tree/archive/modern-web-spa-is-v15), including the IS v15 camera improvements. Its SPA source and API static mount are removed from main. `web/package.json` remains only as a compatibility entry point for the existing CI job and delegates to `frontend/`; it contains no UI server. Ignored local build artifacts must not select a different default UI.

Run from `implementation/` after configuring the existing PostgreSQL connection:

```powershell
.\.venv\Scripts\python.exe -m uvicorn scenario_db.api.app:app --host 127.0.0.1 --port 18000
.\.venv\Scripts\python.exe -m streamlit run dashboard/Home.py --server.address 127.0.0.1 --server.port 18502 --server.headless true
```

Open [Dashboard](http://127.0.0.1:18502/), [Pipeline Viewer](http://127.0.0.1:18502/Pipeline_Viewer), or [Evidence Dashboard](http://127.0.0.1:18502/Evidence_Dashboard). API docs remain at [18000/docs](http://127.0.0.1:18000/docs). Port 5173 is no longer the default UI.

The existing `frontend/` Workbench, committed component assets, ELK viewer, timing integration and node labels remain. To rebuild the Workbench, run `npm ci`, `npm test`, and `npm run build` inside `frontend/`; include the output under `dashboard/components/workbench_frontend/component/`.

This is a selective UI restoration, not a revert of all PR #5 changes. Query/pagination improvements, simulation correctness, API/write fixes, security lock updates, and IS v15 sensors/DMA/timing/evidence stay in main. The existing Evidence Dashboard Timing Table also shows camera SW min/mean/max, source, start delay and included hardware. Measurement comparison remains in the existing dashboard.
