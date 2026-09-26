# authoring/ — ScenarioDB 편집 원본

사람이 편집하는 layered source. `python -m scenario_db.authoring compile <project> --out <dir>`로
canonical v2.2 YAML을 만든다. 사용법: [docs/guides/import/authoring-layers-guide-ko.md](../docs/guides/import/authoring-layers-guide-ko.md)

```
platforms/exynos2600/        root: canonical HW/sensor/SW docs (docs/)
platforms/exynos2700/        extends exynos2600: rename + patches/
projects/sm-s947b/           root project (S26+) + 13 scenarios (decompiled, == fixture)
projects/e2700-ref/          extends sm-s947b on exynos2700: measured SW timing slots
examples/exynos2800-pipeline-change/   hypothetical pipeline-change example (tested)
```
