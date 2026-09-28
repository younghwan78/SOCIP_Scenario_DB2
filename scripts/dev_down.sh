#!/usr/bin/env bash
# Stop the servers started by scripts/dev_up.sh (API / UI / Streamlit). PostgreSQL keeps running;
# `docker compose stop postgres` stops it too.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
for name in api ui streamlit; do
  pidf="output/dev/$name.pid"
  [[ -f "$pidf" ]] || continue
  pid="$(head -1 "$pidf")"
  started="$(sed -n '2p' "$pidf")"
  current="$(ps -o lstart= -p "$pid" 2>/dev/null || true)"
  sid="$(ps -o sid= -p "$pid" 2>/dev/null | tr -d ' ' || true)"
  if [[ "$pid" =~ ^[0-9]+$ && "$pid" -gt 1 && "$sid" == "$pid" && -n "$started" && "$started" == "$current" ]] && kill -0 "$pid" 2>/dev/null; then
    kill -- "-$pid" 2>/dev/null  # only the recorded session, never a reused PID
    echo "stopped $name (pid $pid)"
  fi
  rm -f "$pidf"
done
