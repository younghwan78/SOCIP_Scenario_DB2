# CPU Analysis API Contract

Status: Current. Verified: 2026-10-04.

Runtime: `src/scenario_db/api/routers/cpu.py`, `api/schemas/cpu.py`,
`api/services/cpu.py`, `sim/cpu_sched.py`, `sim/cpu_rebalance.py`, `sim/cpu_dsu.py`.

## Read-only analysis

`GET /api/v1/cpu/inputs` lists CPU topology parameters and measurement profiles.
`POST /api/v1/cpu/whatif`, `/cpu/sweep`, and `/cpu/rebalance` require an analyst,
writer, or admin role. They do not modify evidence or topology parameters.
Simulation admission is shared with other analyses: a busy slot returns 429 with
`Retry-After`; the UI uses bounded retries and preserves the request payload.

The request selects a measurement `cpu_profile_ref` or inline `cpu_profile`, a
target `power_params_ref`, and optionally a measured-topology `base_power_params_ref`.
A version suffix on a topology reference must match the stored version.
Unknown references return 404; unusable profiles, unsupported modes, or invalid
rebalance constraints return 422.

## DSU assumptions

`dsu_mode` is `auto`, `vote`, `proportional`, `measured`, or `fixed`. `auto` uses
a vote table when available, otherwise measured residency, otherwise proportional
coupling. A request `dsu_vote` overrides the topology table without saving it.
Fixed mode requires `dsu_fixed_mhz`; measured mode requires profile residency.

Sweep and rebalance responses expose `dsu_model`, `dsu_params`, and
`dsu_measured` so client experiments reproduce the selected rule. Client
experiments rerank only returned candidates; applying the assumption to the
server reruns the search. Vote tables are assumptions unless their source is
characterized. See [CPU profile import](../../guides/measurement/cpu-profile-import-ko.md).

## Rebalance constraints and verification

Rebalance requires at least two distinct known pool clusters. Default movable
tasks are measured on that pool, excluding `(other)` and locked tasks. Explicit
`movable` duplicates are folded. Locks pin a task to a cluster or exclude it from
movement; excluded tasks retain measured placement.

`co_move` combines movable tasks into one unit. Members must share a measured
home cluster, preserving the reference placement before the group moves. This
models a placement constraint; cgroup composition and splitting costs are not
measured inputs.

Cluster symmetry reduction requires identical CPU power/performance parameters,
effective scheduler capacity, DSU votes, and absence of frozen load. Distinct
named DSU votes must not collapse two clusters into one search state.

The search uses exhaustive enumeration up to `max_exhaustive`, then local
move/swap search. It returns the method and evaluated counts. The reference and
top candidates are checked with full scheduler evaluation; `verified` and
`model_err_mw` expose that check. A local-search best is the best found candidate,
not a guarantee of a global optimum.

## SW growth sweep

`POST /cpu/rebalance/sweep` accepts the rebalance request plus 2–13 `growths`
in `(0.2, 5]`, and uses the same analyst/writer/admin role and simulation admission
slot as rebalance. At least two values must remain distinct after rounding to four
decimal places. Results contain reference/best/strategy power, cluster OPP
changes, stage room and a growth tolerance. Per-task growth overrides remain fixed;
only `default_growth` is swept. Zero or negative stage room yields zero SW growth
tolerance. The UI preserves both requested range endpoints when limiting the grid
to 13 points and discards results from a previously selected profile/topology.

Sweep points are computed in worker processes (`SCENARIO_DB_CPU_SWEEP_WORKERS`,
0 = min(cpu_count, 8), 1 = in-process); any pool failure falls back to the
in-process path. Responses report `workers`.

## Distribution curve, CPU-caused BW power (CPU-07, CPU-09)

`POST /cpu/rebalance` additionally returns `ratio_curves`: per pool cluster, units
moved onto that one cluster one at a time (largest power reduction first) with the
share of movable util on it, CPU + DSU mW, feasibility and cluster MHz. The curves
are evaluated outside the search and never change `best` / `cases`. Sweeps skip them.

`bw_power` (rebalance) and `bw_power` + per-point `bw_mw` (sweep) convert
`cpu_bw_mbs` with the profile variant's registered prediction coefficient
(IP BW mW / IP BW MB/s, same coefficient and LLC weight as the exploration); without
a prediction the builtin 80 mW per GB/s is used and `source` says `builtin`.

## Review snapshots (CPU-11)

`POST /review/cpu-snapshots` {project_ref, request (sweep request), note} — writer/admin,
simulation admission slot. The server reruns the sweep and stores a summary
(tolerance, binding limit, OPP step, power per growth, best distribution at the first
growth, BW power). One `active` snapshot per (project, scenario, variant); a newer one
supersedes it. `GET /review/cpu-snapshots?project_ref` lists active snapshots;
`POST /review/cpu-snapshots/{id}/withdraw` withdraws one. Project reports freeze the
active snapshots into `snapshot.cpu` and the `cpu_growth_tolerance` risk rule
(tolerance < ×1.2, medium).

The UI associates a completed growth result with the request that calculated it.
Editing inputs does not rewrite that request. Replacing/cancelling an analysis
invalidates pending results and snapshot eligibility; main, comparison, growth
and comparison-growth requests remain sequential to share admission capacity.
