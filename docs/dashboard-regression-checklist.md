# Evidence Dashboard Regression Checklist

Use this checklist before committing changes that touch `dashboard/pages/4_Evidence_Dashboard.py` or shared dashboard components.

The default guard should not require Playwright or a browser automation runtime. Use pure unit tests, Python compile checks, and HTTP smoke checks first. Manual browser review is still useful, but it is not the only regression gate.

## UI Contract

The Evidence Dashboard must keep these controls available:

- Sidebar context selectors: SoC Platform, Project / Board, Scenario Category, Scenario, Variant
- Preview result tab: KPI metrics, warnings/errors, Confirm & Save Evidence, Download Preview JSON, Download Preview KPI CSV, Open Scenario in Pipeline Viewer
- Saved evidence tab: evidence list, Selected Evidence, KPI metrics, warnings/errors, Open Pipeline Viewer, Download JSON, Download KPI CSV, Download DMA CSV, Delete Evidence
- Result breakdown tabs: IP/Node Power, DMA BW, Timing Chart, Timing Table, Timeline Table, Report, Debug Trace, Raw Evidence

These labels are also defined in `dashboard/components/evidence_dashboard_contract.py`. Dashboard code and tests should use that module instead of hard-coding required labels in multiple places.

## Browser-Less Checks

Run these before commit:

```powershell
uv run python -m py_compile dashboard\pages\4_Evidence_Dashboard.py dashboard\components\evidence_dashboard_contract.py
uv run --group dev --group sim pytest tests\unit -q
```

When the local API/Streamlit processes are running, also run a lightweight HTTP smoke:

```powershell
Invoke-RestMethod http://127.0.0.1:18000/health/ready
Invoke-WebRequest http://127.0.0.1:18502/Evidence_Dashboard -UseBasicParsing
```

## Manual Review

After dashboard layout changes, refresh `http://127.0.0.1:18502/Evidence_Dashboard` and verify:

- Changing SoC/Project/Scenario/Variant keeps the selectors usable.
- `Run Preview` shows preview KPI, result tabs, and `Open Scenario in Pipeline Viewer`.
- `Confirm & Save Evidence` moves the result to Saved Evidence.
- Saved Evidence shows `Open Pipeline Viewer` and download/delete actions.
- The `Report` tab offers timing, BW, simulation report HTML downloads, and a bundle ZIP link for saved evidence.
- For saved evidence, `Save HTML Bundle Locally` writes HTML artifacts and shows the returned local paths.
- Severe zero-power or zero-HW-time warnings are shown as errors, not hidden in raw JSON.

## Scope Rule

Removing or renaming a required selector, tab, or action is a UI contract change. Do not do it as an incidental refactor; document the reason and update the contract tests in the same commit.
