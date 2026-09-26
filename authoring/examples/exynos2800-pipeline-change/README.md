# Example — pipeline structure change (hypothetical Exynos2800)

**Not real 2800 data.** Demonstrates how a project whose pipeline differs from its parent is authored:

| Layer | File | Change |
| --- | --- | --- |
| Platform | `platforms/exynos2800-concept/platform.yaml` | extends `exynos2700`, id rename `exynos2700 → exynos2800c` |
| Platform | `platforms/exynos2800-concept/docs/00_hw/ip-nr-v2-exynos2800c.yaml` | new IP (placeholder values) |
| Project | `projects/e2800-concept/project.yaml` | extends `e2700-ref`, only camera recording |
| Scenario | `projects/e2800-concept/scenarios/uc-camera-recording-e2700/overlay.yaml` | remove `msnr`, re-bind `mtnr`, new edge |

Everything else (SW task graph, sw_timing, sensor sizes, 75 variants) is inherited.
The compile report's `impact` lists every variant reference that the structural change invalidated.

Try it (copies the example into a scratch authoring root):

```powershell
Copy-Item -Recurse authoring $env:TEMP\auth2800
Copy-Item -Recurse authoring\examples\exynos2800-pipeline-change\* $env:TEMP\auth2800 -Force
uv run python -m scenario_db.authoring --root $env:TEMP\auth2800 compile e2800-concept --out $env:TEMP\c2800
```
Covered by `tests/unit/authoring/test_authoring_roundtrip.py::test_pipeline_change_example`.
