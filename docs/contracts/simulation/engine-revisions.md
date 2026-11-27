# Exploration engine revisions

Status: current · Last verified: 2026-11-27 (`arch-exploration/16`)

`ENGINE_REV` (`src/scenario_db/sim/arch_exploration.py`) names the revision a run, a prediction and a report row
were computed with. A result from an older revision is flagged "이전 engine". The flag shows the
revisions in between, taken from `src/scenario_db/sim/engine_revisions.py`, in two places:

- Reports: the old-engine note
- 모델 기준 상세: the Engine section

## When to bump

| Change | Revision | Record |
|---|---|---|
| The same inputs give a different result (any variant of the fixture) | bump `ENGINE_REV` | a new `ENGINE_REVISIONS` entry in the same change: what changed, what moves, the size on the E2600 fixture |
| New data opts in; undeclared data gives identical results | keep | an `OPT_IN` entry |
| Refactor, speed-up | keep | — |

Run the change gate from the repository root:

```
uv run python scripts/check_change_gate.py run --base main
```

It checks the base out into a temporary worktree and dumps both trees with no database. It then compares them in
three groups and checks the ejected Exynos2700 documents (`authoring check sm-s957b --against
db_Exynos2700_SM-S957B`):

| Group | Compared | Gate |
|---|---|---|
| E2600 results | the `check_engine_equivalence` fixed cases, outside the input hash | reported (`--strict` fails) |
| E2600 input hash | `input_hash` / `input_sections` / `_manifest_blobs` of those cases: a change makes their registered predictions stale | reported (`--strict` fails) |
| E2700 | every E2700 variant: the Timing Budget report and the DMA breakdown, plus the documents | **any difference fails** |

A change that should keep the revision has no E2600 result difference. A bump lists the moved variants in its PR.
An opt-in change lists the cases whose input hash moved (only the scenarios that declare it).

The fixed cases cover every E2600 scenario (a test fails when a fixture scenario has none). `dump --root` /
`compare` run the two halves by hand (`scripts/check_engine_equivalence.py` still dumps the E2600 cases alone).
`tests/unit/authoring` (the inherited-2700 compile test) also stays green.

### After a bump or an input-hash change: refresh the predictions

A bump (or a moved input hash) leaves the project's registered predictions stale (`GET
/api/v1/arch/predictions/freshness`). Refresh one project at a time, then regenerate its review report:

```powershell
.\.venv\Scripts\python.exe scripts\refresh_predictions.py --project proj-sm-s947b --check   # compute, store nothing
.\.venv\Scripts\python.exe scripts\refresh_predictions.py --project proj-sm-s947b
```

`api/services/prediction_refresh.py` re-runs each registered exploration run once under its stored condition and
promotes its variants by the default rule (expected current = today's prediction, one transaction). Variants with
no current prediction are re-evaluated under the newest run that has them, so the project report has no
old-engine rows. Timing Budget registrations go through `recompute_prediction`. Hand-picked (`user:` / `lever:`)
registrations are listed as skipped (exit 1) and need a new selection.

## Revisions

| rev | change | what moves |
|---|---|---|
| 10 | shared CPU load; every output stream is judged | CPU power and the verdict of variants with several outputs (preview + record) |
| 11 | lossless and lossy compression per buffer; lever analysis | BW / BW power of compressed buffers; the lever table |
| 12 | SBWC mean ratio = the typical ratio (engine baseline); eligible-only lever path and exact optimum | BW of SBWC buffers; the recommended combination when a lever was not eligible |
| 13 | the v2-vf clock term uses the work clock (busy share no longer follows the SW margin) | IP power under the v2-vf power model when SW growth changed |
| 14 | profile CPU model (`cpu_sched`): opt-in RT cpupri placement; a task's threads on one CPU run in sequence | CPU power / slack with the profile CPU model |
| 15 | SW margin follows the throughput model (pipelined: longest task / shared-CPU load; the stage chain gives the frames in flight) | SW margin and SW growth tolerance under the pipelined model (recording: the NRT margin) |
| 16 | one bytes-per-pixel lookup (`format_bpp_factor`: packed RGBA = 4 B/px whatever the bitdepth; steady BW, debug trace and event jobs agree); an IP node timed by `sw_timing` keeps its M2M buffer DMA; a buffer with no size or an unknown pixel format is reported | BW / BW power of RGBA buffers (E2600 game FHD 120: 497.7 → 1990.7 MB/s, +119 mW; gallery ×4), the game m2m-upscale path (0 → 3926 MB/s), GPU fallback and SW demux buffer writes (SW BW). E2700: no change |

## Opt-in since rev 15 (no bump)

| change | opts in with |
|---|---|
| objective order (Pareto policy); registration rule `auto:min-power` / `auto:objective` | an explicit objective order in the request |
| task cadence vocabulary; own cadences judged by their own deadline; own-cadence SW counted as CPU work | `node_configs.<node>.timeline.cadence` |
| workload load models (`codec-throughput-v1` decoder throughput) | `sim.load_model` / the pipeline node's `load_model` |

## Properties every revision keeps

`tests/unit/sim/test_engine_properties.py` fixes directions, not numbers. The golden cases
(`simulation_golden_cases.yaml`) fix the numbers.

- A faster DVFS level never lowers power.
- Compression (any ratio ≤ 1) never raises a port's BW.
- More SW growth, with DVFS fixed, never raises the SW slack. This uses the exploration's SW-margin rule for both
  throughput models. With DVFS re-selection, a growth that lifts a domain one OPP can raise the slack again; that is
  the other growth tolerance, not a property.
- A higher fps never lowers an IP's own required clock.

## Accuracy per revision (when measurements exist)

Once physical measurements are registered, store the prediction error per revision (MAPE of predicted vs. measured
power per variant). The 예측 ↔ 실측 view can then show whether a revision improved accuracy. The E2600 fixture has
only synthetic measurements, so this is not stored yet.
