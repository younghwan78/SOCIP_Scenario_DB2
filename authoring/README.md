# authoring/ — ScenarioDB 편집 원본

사람이 편집하는 layered source. `python -m scenario_db.authoring compile <project> --out <dir>`로
canonical v2.2 YAML을 만든다. 사용법: [docs/guides/import/authoring-layers-guide-ko.md](../docs/guides/import/authoring-layers-guide-ko.md)

```
platforms/exynos2600/        root: canonical HW/sensor/SW docs (docs/)
platforms/exynos2700/        extends exynos2600: s5e9965 -> s5e9975 rename + patches/
projects/sm-s947b/           root project (S26+) + 13 scenarios (decompiled, == fixture)
projects/sm-s957b/           extends sm-s947b on exynos2700 (S5E9975), SM-S957B: measured SW timing slots,
                             bcrop / L0-skip exploration variants
examples/exynos2800-pipeline-change/   hypothetical pipeline-change example (tested)
```
