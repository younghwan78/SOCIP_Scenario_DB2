#!/usr/bin/env bash
# Stop the servers started by scripts/dev_up.sh (API / UI / Streamlit). PostgreSQL keeps running;
# `docker compose stop postgres` stops it too.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
for name in api ui streamlit; do
  pidf="output/dev/$name.pid"
  [[ -f "$pidf" ]] || continue
  pid="$(cat "$pidf")"
  if kill -0 "$pid" 2>/dev/null; then
    kill -- "-$pid" 2>/dev/null || kill "$pid"   # whole process group (uv -> uvicorn, npm -> vite)
    echo "stopped $name (pid $pid)"
  fi
  rm -f "$pidf"
done
