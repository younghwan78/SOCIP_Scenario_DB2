# Exynos2700 platform patches

One file per **renamed** document id: `patches/<doc id>.yaml`, deep-merged onto the doc inherited
from exynos2600. Lists are replaced whole; `$unset: [key]` removes a key.

```yaml
# patches/ip-mfc-s5e9975.yaml  (example — not active)
capabilities:
  sim:
    source: exynos2700_arch_rev1
    modes:
      Normal:
        ppc: 8.0              # 2700 MFC PPC
        unit_power_mw_mp: 0.9 # measured / calibrated value
```

`python -m scenario_db.authoring compile sm-s957b --out <dir>` prints the effective result;
`check`-style diffs vs the parent are visible in the generated files.
