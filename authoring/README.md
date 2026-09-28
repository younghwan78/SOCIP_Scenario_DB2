# authoring/ — ScenarioDB 편집 원본

사람이 편집하는 layered source. 절차와 예제: [docs/guides/import/authoring-layers-guide-ko.md](../docs/guides/import/authoring-layers-guide-ko.md)

```
platforms/exynos2600/        root platform: canonical HW / sensor / SW docs
platforms/exynos2700/        root (ejected from exynos2600): complete docs/ with ids *-s5e9975; edit files directly
projects/sm-s947b/           root project (Exynos2600 reference): 13 scenarios, == ../db_Exynos2600_SM-S947B
projects/sm-s957b/           root (ejected from sm-s947b) on exynos2700 (SM-S957B): rear camera recording only
                             (scenarios/uc-cam-recording-e2700: 16 rear KPI variants; power options = knobs.yaml explore)
                             parent-diff: python -m scenario_db.authoring parent-diff sm-s957b
                             -> generated into ../db_Exynos2700_SM-S957B (00~02); measurements/ -> 03_evidence
examples/exynos2800-pipeline-change/   hypothetical pipeline-change example (tested, not loaded)
id-renames.yaml              id history -> python -m scenario_db.etl.rename_ids
retired.yaml                 stale DB rows to remove (never Exynos2600) -> python -m scenario_db.etl.retire
```
