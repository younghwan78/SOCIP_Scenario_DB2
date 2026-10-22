# Compute and database resource budgets

| Field | Value |
| --- | --- |
| Status | Current |
| Last verified | 2026-10-22 |
| Scope | API calculation inputs, executor lifecycle and optional single-host admission |
| Evidence | `tests/unit/api/test_cpu_runtime.py`, `tests/unit/api/test_resource_limits.py`, `tests/integration/test_performance_reads.py`, `tests/integration/test_cpu_api.py` |

The existing calculation inputs, outputs and per-process admission defaults are
unchanged. This guide describes optional limits for a shared server and the CPU
sweep executor lifecycle.

## CPU sweep processes

`SCENARIO_DB_CPU_SWEEP_WORKERS` still defaults to `0`: at most
`min(os.cpu_count(), 8, number_of_points)` processes per API worker. `1` computes
inside the API process. Sweeps with fewer than three points also run inside the
API process. An existing executor can remain idle after a smaller request.

Explicitly size the API worker count and this value together. With W API workers
and a per-worker limit P, persistent sweep child processes can reach W × P.
Concurrent sweeps in one API worker share its executor; do not multiply this
count by the request admission limit again. API CPU work, PostgreSQL and the OS
also need capacity. Container CPU quotas may differ from `os.cpu_count()`.

Executor creation and batch submission use a lease. Resizing waits for active
batches, and application shutdown drains the executor. A transport/process error
cancels queued points and waits for running points before the existing sequential
fallback. Successful points are reused; they are not computed again. Domain
validation errors still propagate. This is not an execution deadline or hard
cancellation of a running calculation.

## Optional admission across API workers on one server

Per-process defaults remain two simulation requests and two exploration requests.
Architecture exploration, Scenario What-If and CPU routes share the `simulation`
operation. The separate `exploration` operation serves recipe/sweep previews.

To cap active requests across processes, set an absolute local directory shared
by every API worker and the global limits you want to enable. For example, after
choosing budgets from a staging load test:

```text
SCENARIO_DB_EXECUTION_BUDGET_DIR=/run/scenariodb/compute-slots
SCENARIO_DB_SIMULATION_GLOBAL_MAX_CONCURRENT_RUNS=2
SCENARIO_DB_EXPLORATION_GLOBAL_MAX_CONCURRENT_REQUESTS=2
SCENARIO_DB_CPU_SWEEP_WORKERS=2
```

These numbers are an example, not a capacity recommendation. Global limits default
to `0` (disabled); changing them is opt-in. Both the per-process and enabled global
limits must admit the request. Exhaustion preserves the existing HTTP 429 detail
and `Retry-After: 1`. An inaccessible budget directory returns HTTP 503 rather than
silently disabling the cap.

Slots use OS file locks, released on descriptor close or process exit. Provision
the directory for the service account, use the same directory and values for all
workers, and restart workers together when changing the budget. Do not delete slot
files while any worker is active: deleting locked files can create a second set of
independent slots. A service manager's runtime directory is suitable when its
lifetime covers all API workers. This is a local-filesystem, single-host budget;
it is not a distributed queue or an NFS/multi-host coordination mechanism. Different
applications should use different directories.

Global request admission bounds concurrent jobs, not the number of idle executor
processes or total resident memory. Continue to set P and W explicitly. It also
does not provide per-user fairness, job progress, cancellation or retry persistence.

`SCENARIO_DB_WHATIF_RELEASE_COMPUTE_SLOT_DURING_LLM` defaults to `false`, preserving
the original whole-request simulation admission and HTTP 429 timing. Setting it to
`true` lets natural-language What-If release simulation admission during the LLM
network call. Baseline and final calculations still require simulation admission;
LLM calls use a separate `whatif-llm` slot. Condition-builder requests retain their
existing admission scope. A busy server may therefore reject a natural-language
request when its final calculation reacquires a simulation slot. Enable this only
after validating that capacity behavior in staging.

## Database and validation

The existing SQLAlchemy defaults are 10 pooled plus 20 overflow connections per
API worker. Maximum API connections are W × (pool_size + max_overflow), plus ETL,
admin and other clients. Pure sweep child processes do not own DB pools. Size this
budget against PostgreSQL `max_connections` with operational reserve, and measure
actual checkout wait and connection hold time before raising it.

CPU read APIs prepare profile/model/timing inputs before calculation. The request
session can return its read connection while pure computation runs; caller-owned
transactions are preserved. A later bandwidth-coefficient read still happens
after computation, as before. Growth points reuse the same parsed profile and
models within one request; `timing_coupling=off` keeps its previous per-point timing
calculation and rounding.

Scenario What-If and public Architecture run creation also return their request's
read connection after loading the required inputs. Analysis graph loading excludes
unused evidence history and decision rules; viewers keep their full graph loading.
Registration/recomputation callers keep their transaction and locking scope.
The connection-release helper is for explicit read-only boundaries, before any
write (including an autoflush) or row/advisory lock. It cannot infer earlier flushed
writes or lock ownership from a clean ORM session.

Test 1/5/10/20 readers, mixed reads and calculations, concurrent identical sweeps,
worker failure, shutdown, and process termination while holding a global slot.
Record query and connection counts, PID/RSS totals, admission failures, wall time,
and identical calculation results. Run the PostgreSQL CPU integration tests in an
isolated database; no deployment settings are applied by this change.

## Optional request performance logs

`SCENARIO_DB_PERFORMANCE_LOG_ENABLED=true` enables one JSON log record per completed
HTTP application call on the `scenario_db.api.performance` logger at INFO. The
default is `false`: no performance middleware or SQLAlchemy listeners are installed.
Responses, headers, status codes, admission behavior and calculation inputs are
unchanged. Keep the application's log level at INFO or more verbose to collect it.

Records contain the registered route template (or `__unmatched__`), a bounded HTTP
method, status, total `wall_ms`, process-local active requests at start/end, SQL
statement-attempt count and cursor execution time, and summed connection checkout
hold time. HTTP 429 records can be counted by route to observe admission rejections.
Raw paths, query strings, bodies, credentials, record IDs, SQL text/parameters and
exception messages are not included.

Wall time includes streaming and application/dependency cleanup. SQL errors count
as attempted statements; SQL timing excludes result fetching and pool acquisition.
Connection hold time runs from successful checkout to checkin or invalidation,
and includes time between statements. A connection still held when the application
call ends is counted in `db_connections_open_at_finish`; its hold time is clipped
at that point. The sum can exceed wall time when a request holds multiple connections.
This does **not** measure pool checkout wait, child-process CPU time, unrelated DB
engines or work in threads that do not propagate the request context. FastAPI's
ordinary synchronous worker threads preserve the context. Streaming failures retain
the sent status with `failed=true`/`response_complete=false`; a failure before response
start is logged as 500. A disconnected client may not receive that status.
Individual preparation, CPU calculation and LLM phases are not separately timed;
wall time minus SQL time is not a CPU-time measurement.

Aggregate these records externally for p50/p95/p99 latency and SQL/connection costs;
the application keeps no request history or unbounded metrics registry. Validate
logging volume and storage before enabling it for the whole Ubuntu deployment.

### Focused validation (2026-10-22)

- Windows: 40 CPU/resource/config unit tests passed. Ten PostgreSQL CPU API tests
  passed, including all four compute paths with request-owned and caller-owned
  sessions and equality of calculation responses (excluding elapsed time).
- Linux: an isolated official `python:3.11-slim` container, with the checkout
  mounted read-only and runtime dependencies exported from the frozen lockfile,
  passed 17 CPU/resource tests. The real `flock` cross-process test includes
  releasing admission after forcibly terminating the holder.
- A separate real Linux `forkserver` probe compared complete synthetic Exynos2600
  rebalance results with sequential computation. Concurrent executor reuse,
  resize from two to three processes, and shutdown with no surviving pool workers
  passed. Image digest:
  `sha256:cce12316475d7d56d605f76e1d811d0dc4e7227f2d4afd29951521264f504ff8`.

These checks establish the tested result/lifecycle contracts. They do not establish
throughput or memory capacity for 20 users on the production Ubuntu server.
