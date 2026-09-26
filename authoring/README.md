# authoring/ — ScenarioDB 편집 원본

사람이 편집하는 layered source. 절차와 예제: [docs/guides/import/authoring-layers-guide-ko.md](../docs/guides/import/authoring-layers-guide-ko.md)

```
platforms/exynos2600/        root platform: canonical HW / sensor / SW docs
projects/sm-s947b/           root project (Exynos2600 reference): uc-cam-recording-e2600, 18 KPI variants
examples/exynos2800-pipeline-change/   hypothetical pipeline-change example (tested, not loaded)
archive/2026-09-27-scope-reduction/    out-of-scope scenarios / variants / evidence (not loaded)
id-renames.yaml              id history -> python -m scenario_db.etl.rename_ids
retired.yaml                 DB rows to remove -> python -m scenario_db.etl.retire
```
