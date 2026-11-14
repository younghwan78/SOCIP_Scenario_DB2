# Exploration engine revisions

Status: current · Last verified: 2026-11-14 (`arch-exploration/15`)

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

Run `scripts/check_engine_equivalence.py dump` on main and on the branch, then `compare`. A change that should keep
the revision has 0 differences. A bump lists the moved variants in its PR.

## Revisions

| rev | change | what moves |
|---|---|---|
| 10 | shared CPU load; every output stream is judged | CPU power and the verdict of variants with several outputs (preview + record) |
| 11 | lossless and lossy compression per buffer; lever analysis | BW / BW power of compressed buffers; the lever table |
| 12 | SBWC mean ratio = the typical ratio (engine baseline); eligible-only lever path and exact optimum | BW of SBWC buffers; the recommended combination when a lever was not eligible |
| 13 | the v2-vf clock term uses the work clock (busy share no longer follows the SW margin) | IP power under the v2-vf power model when SW growth changed |
| 14 | profile CPU model (`cpu_sched`): opt-in RT cpupri placement; a task's threads on one CPU run in sequence | CPU power / slack with the profile CPU model |
| 15 | SW margin follows the throughput model (pipelined: longest task / shared-CPU load; the stage chain gives the frames in flight) | SW margin and SW growth tolerance under the pipelined model (recording: the NRT margin) |

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
