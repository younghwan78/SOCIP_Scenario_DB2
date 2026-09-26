# authoring/ — ScenarioDB 편집 원본

사람이 편집하는 layered source. 절차와 예제: [docs/guides/import/authoring-layers-guide-ko.md](../docs/guides/import/authoring-layers-guide-ko.md)

```
platforms/exynos2600/        root platform: canonical HW / sensor / SW docs
platforms/exynos2700/        extends exynos2600: s5e9965 -> s5e9975 rename + patches/
projects/sm-s947b/           root project (Exynos2600 reference): 13 scenarios, == db_fixtures_Exynos2600_S26Plus
projects/sm-s957b/           extends sm-s947b on exynos2700 (SM-S957B): rear camera recording only
                             (uc-cam-recording-e2700, overlay variants.keep = 16 rear KPI + 3 exploration; dual pip excluded)
examples/exynos2800-pipeline-change/   hypothetical pipeline-change example (tested, not loaded)
id-renames.yaml              id history -> python -m scenario_db.etl.rename_ids
retired.yaml                 stale DB rows to remove (never Exynos2600) -> python -m scenario_db.etl.retire
```
