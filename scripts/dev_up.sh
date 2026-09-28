#!/usr/bin/env bash
# Linux (Ubuntu) counterpart of scripts/dev_up.ps1.
#
# PostgreSQL (docker compose, or an existing server with --no-docker) -> alembic ->
# rename/retire -> ETL db_Exynos2600_SM-S947B -> per derived project [authoring sync ->
# measurement import -> ETL] -> API (+ React UI, Streamlit) in the background.
#
# Examples
#   scripts/dev_up.sh                                  # docker PG, load, API + UI on 127.0.0.1
#   scripts/dev_up.sh --no-docker                      # use DATABASE_URL / SCENARIO_DB_DATABASE_URL (.env)
#   scripts/dev_up.sh --skip-load --streamlit
#   scripts/dev_up.sh --load-only                      # DB only (cron / CI); no servers
#   scripts/dev_up.sh --bind 0.0.0.0                   # reachable from other PCs (auth must be configured)
#   scripts/dev_up.sh --project sm-s957b=db_Exynos2700_SM-S957B --project explore-2600=db_explore
#   scripts/dev_down.sh                                # stop the background servers
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # implementation/
cd "$ROOT"

PROJECTS=()
SKIP_LOAD=0; NO_UI=0; STREAMLIT=0; NO_DOCKER=0; LOAD_ONLY=0
BIND="127.0.0.1"; API_PORT=18000; UI_PORT=3000; ST_PORT=18502

usage() { sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECTS+=("$2"); shift 2 ;;
    --skip-load) SKIP_LOAD=1; shift ;;
    --no-ui) NO_UI=1; shift ;;
    --streamlit) STREAMLIT=1; shift ;;
    --no-docker) NO_DOCKER=1; shift ;;
    --load-only) LOAD_ONLY=1; shift ;;
    --bind) BIND="$2"; shift 2 ;;
    --api-port) API_PORT="$2"; shift 2 ;;
    --ui-port) UI_PORT="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "unknown option: $1" >&2; usage 2 ;;
  esac
done
[[ ${#PROJECTS[@]} -eq 0 ]] && PROJECTS=("sm-s957b=db_Exynos2700_SM-S957B")

C_STEP=$'\e[36m'; C_OK=$'\e[32m'; C_ERR=$'\e[31m'; C_OFF=$'\e[0m'
[[ -t 1 ]] || { C_STEP=""; C_OK=""; C_ERR=""; C_OFF=""; }
step() { printf '\n%s=== %s ===%s\n' "$C_STEP" "$*" "$C_OFF"; }
die() { printf '%s%s%s\n' "$C_ERR" "$*" "$C_OFF" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "'$1' not found: $2"; }
run() { "$@" || die "failed (exit $?): $*"; }

need uv "install uv (https://docs.astral.sh/uv/) or pip install uv"
mkdir -p output/etl output/dev
STAMP="$(date +%Y%m%d-%H%M%S)"

# ------------------------------------------------------------------ PostgreSQL
if [[ $NO_DOCKER -eq 0 ]]; then
  step "PostgreSQL (docker compose)"
  need docker "install Docker or rerun with --no-docker and an existing PostgreSQL (DATABASE_URL)"
  if docker compose version >/dev/null 2>&1; then DC=(docker compose); else need docker-compose "compose plugin"; DC=(docker-compose); fi
  run "${DC[@]}" up -d postgres
  cid="$("${DC[@]}" ps -q postgres)"
  health=""
  for _ in $(seq 60); do
    health="$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null || true)"
    [[ "$health" == "healthy" ]] && break
    sleep 2
  done
  [[ "$health" == "healthy" ]] || die "postgres not healthy: ${health:-unknown}"
  echo "postgres: healthy (127.0.0.1:15432)"
else
  step "PostgreSQL (existing server)"
  url="${SCENARIO_DB_DATABASE_URL:-${DATABASE_URL:-}}"
  if [[ -z "$url" && -f .env ]]; then
    url="$(grep -E '^(SCENARIO_DB_DATABASE_URL|DATABASE_URL)=' .env | head -1 | cut -d= -f2-)"
  fi
  [[ -n "$url" ]] || die "--no-docker needs SCENARIO_DB_DATABASE_URL or DATABASE_URL (env or .env)"
  echo "database: $(sed -E 's#://([^:/@]+):[^@]*@#://\1:***@#' <<<"$url")"
fi

step "Alembic migration"
run uv run alembic upgrade head

# ------------------------------------------------------------------ load
if [[ $SKIP_LOAD -eq 0 ]]; then
  step "Rename legacy ids (authoring/id-renames.yaml; no-op when nothing matches)"
  run uv run python -m scenario_db.etl.rename_ids --map authoring/id-renames.yaml \
      --apply --backup "output/etl/rename-backup-$STAMP.json"

  step "Retire out-of-scope rows (authoring/retired.yaml; no-op when nothing matches)"
  run uv run python -m scenario_db.etl.retire --spec authoring/retired.yaml \
      --apply --backup "output/etl/retire-backup-$STAMP.json"

  step "ETL: db_Exynos2600_SM-S947B"
  run uv run python -m scenario_db.etl.loader db_Exynos2600_SM-S947B \
      --strict --report-json output/etl/etl-exynos2600.json

  for pair in "${PROJECTS[@]}"; do
    key="${pair%%=*}"; db="${pair#*=}"
    [[ "$key" != "$pair" && -n "$db" ]] || die "--project expects KEY=DB_FOLDER, got '$pair'"
    step "Authoring sync -> $db ($key)"
    run uv run python -m scenario_db.authoring sync "$key" --fixture "$db" --to fixture --prune
    if [[ -d "$db/measurements" ]]; then
      step "Measurement import -> $db/03_evidence"
      run uv run python scripts/import_measurements.py "$db" --strict
    fi
    run uv run python -m scenario_db.etl.loader "$db" --strict --report-json "output/etl/etl-$key.json"
  done
fi

if [[ $LOAD_ONLY -eq 1 ]]; then
  printf '\n%sDone (load only). ETL reports: output/etl/*.json%s\n' "$C_OK" "$C_OFF"
  exit 0
fi

# ------------------------------------------------------------------ servers
auth_off="${SCENARIO_DB_MUTATION_AUTH_DISABLED:-}"
[[ -z "$auth_off" && -f .env ]] && auth_off="$(grep -E '^SCENARIO_DB_MUTATION_AUTH_DISABLED=' .env | cut -d= -f2- || true)"
if [[ "$BIND" != "127.0.0.1" && "$BIND" != "localhost" && "${auth_off,,}" == "true" ]]; then
  die "--bind $BIND with SCENARIO_DB_MUTATION_AUTH_DISABLED=true exposes write APIs; configure SCENARIO_DB_API_PRINCIPALS"
fi

start_bg() {  # name, workdir, command...
  local name="$1" dir="$2"; shift 2
  local pidf="output/dev/$name.pid" log="$ROOT/output/dev/$name.log"
  if [[ -f "$pidf" ]] && kill -0 "$(cat "$pidf")" 2>/dev/null; then
    echo "$name already running (pid $(cat "$pidf")); scripts/dev_down.sh to restart"; return
  fi
  # new session: the recorded pid is the process-group leader, so dev_down stops uv/npm and their children
  # shellcheck disable=SC2016  # $$ / $0 / $@ expand in the inner bash
  (cd "$dir" && exec setsid -f bash -c 'echo $$ > "$0"; exec "$@"' "$ROOT/$pidf" "$@" >"$log" 2>&1 < /dev/null)
  for _ in $(seq 20); do [[ -s "$pidf" ]] && break; sleep 0.1; done
  echo "$name: pid $(cat "$pidf"), log output/dev/$name.log"
}

step "API http://$BIND:$API_PORT/docs"
start_bg api "$ROOT" uv run --group sim uvicorn scenario_db.api.app:app --host "$BIND" --port "$API_PORT"

if [[ $NO_UI -eq 0 ]]; then
  step "React UI http://$BIND:$UI_PORT"
  need npm "install Node.js 20+ (or rerun with --no-ui)"
  [[ -d ui/node_modules ]] || run bash -c "cd ui && npm ci"
  SCENARIODB_API_TARGET="http://127.0.0.1:$API_PORT" \
    start_bg ui "$ROOT/ui" npm run dev -- --host "$BIND" --port "$UI_PORT" --strictPort
fi
if [[ $STREAMLIT -eq 1 ]]; then
  step "Streamlit http://$BIND:$ST_PORT"
  start_bg streamlit "$ROOT" uv run --group dashboard --group sim streamlit run dashboard/Home.py \
      --server.port "$ST_PORT" --server.address "$BIND" --server.headless true
fi

printf '\n%sDone. ETL reports: output/etl/*.json · logs: output/dev/*.log · stop: scripts/dev_down.sh%s\n' "$C_OK" "$C_OFF"
