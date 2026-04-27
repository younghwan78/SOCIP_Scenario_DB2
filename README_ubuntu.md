# Ubuntu Server Deployment Guide

This guide describes how to run ScenarioDB on an internal Ubuntu server.

Target runtime:

- FastAPI Read/Write API
- PostgreSQL
- Optional Streamlit viewer
- Optional nginx reverse proxy

The server should be treated as an internal engineering service. Do not expose
PostgreSQL, pgAdmin, or Streamlit directly to the public internet.

## Recommended Deployment Shape

```text
client browser
  |
  | http://server/scenariodb/
  v
nginx
  |-- /api/    -> FastAPI uvicorn on 127.0.0.1:18000
  |-- /viewer/ -> Streamlit on 127.0.0.1:18502
  |
PostgreSQL on 127.0.0.1:5432
```

Recommended choices:

- Run PostgreSQL locally on the Ubuntu server or on a managed internal DB host.
- Bind FastAPI and Streamlit to `127.0.0.1`.
- Expose only nginx to the internal network.
- Use `.env` for local runtime configuration, but do not commit it.
- Use `systemd` to restart API/viewer after reboot.

## Server Packages

Example for Ubuntu 22.04/24.04:

```bash
sudo apt update
sudo apt install -y \
  git curl ca-certificates build-essential \
  python3 python3-venv python3-pip \
  postgresql-client \
  nginx
```

Install `uv` for the service account:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
uv --version
```

If the server cannot access the internet, mirror or pre-stage the `uv` binary
and Python package cache through the internal network.

## Service Account And Directory

Create a dedicated account:

```bash
sudo useradd --system --create-home --shell /bin/bash scenariodb
sudo mkdir -p /opt/scenariodb
sudo chown scenariodb:scenariodb /opt/scenariodb
```

Clone the repo:

```bash
sudo -iu scenariodb
cd /opt/scenariodb
git clone <internal-or-github-repo-url> implementation
cd implementation
```

Install dependencies:

```bash
uv sync --group dev --group dashboard
```

For a production-like server, `dev` can be omitted after the deployment process
is stable:

```bash
uv sync --group dashboard
```

## Environment File

Create `/opt/scenariodb/implementation/.env`:

```bash
DATABASE_URL=postgresql+psycopg2://scenario_user:CHANGE_ME@127.0.0.1:5432/scenario_db
SCENARIO_DB_CORS_ORIGINS=["http://localhost:18502","http://<server-hostname>"]
SCENARIO_DB_LOG_LEVEL=INFO
SCENARIO_DB_DB_POOL_SIZE=10
SCENARIO_DB_DB_MAX_OVERFLOW=20
SCENARIODB_API_BASE=http://127.0.0.1:18000/api/v1
```

Notes:

- `DATABASE_URL` is accepted by the app and Alembic.
- `SCENARIO_DB_DATABASE_URL` can also be used and takes priority.
- `SCENARIODB_API_BASE` is used by the Streamlit dashboard.
- Replace `CHANGE_ME`.
- Keep `.env` readable only by the service account:

```bash
chmod 600 /opt/scenariodb/implementation/.env
```

## PostgreSQL Option A: Local Native PostgreSQL

Install PostgreSQL:

```bash
sudo apt install -y postgresql
sudo systemctl enable --now postgresql
```

Create DB and user:

```bash
sudo -u postgres psql
```

Inside `psql`:

```sql
CREATE USER scenario_user WITH PASSWORD 'CHANGE_ME';
CREATE DATABASE scenario_db OWNER scenario_user;
GRANT ALL PRIVILEGES ON DATABASE scenario_db TO scenario_user;
\q
```

Validate:

```bash
psql "postgresql://scenario_user:CHANGE_ME@127.0.0.1:5432/scenario_db" -c "select now();"
```

## PostgreSQL Option B: Docker Compose

The repo includes `docker-compose.yml` for local development:

```bash
docker compose up -d postgres
```

For an internal Ubuntu server, review it before use:

- Change the default password.
- Avoid publishing `5432` to broad networks.
- Do not run `pgadmin` unless it is explicitly needed.
- Prefer binding published ports to `127.0.0.1`.

Example hardening direction:

```yaml
ports:
  - "127.0.0.1:5432:5432"
```

## DB Migration And Demo Data

Run from the repo root:

```bash
cd /opt/scenariodb/implementation
set -a
source .env
set +a
uv run alembic upgrade head
uv run python -m scenario_db.etl.loader demo/fixtures
```

Smoke check:

```bash
uv run python - <<'PY'
from sqlalchemy import create_engine, text
import os
engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as conn:
    print(conn.execute(text("select count(*) from scenarios")).scalar())
PY
```

## Run Manually

FastAPI:

```bash
cd /opt/scenariodb/implementation
set -a
source .env
set +a
uv run uvicorn scenario_db.api.app:app --host 127.0.0.1 --port 18000
```

Viewer:

```bash
cd /opt/scenariodb/implementation
set -a
source .env
set +a
uv run --group dashboard streamlit run dashboard/Home.py \
  --server.port 18502 \
  --server.address 127.0.0.1 \
  --server.headless true
```

API smoke:

```bash
curl -s "http://127.0.0.1:18000/health/ready"
curl -s "http://127.0.0.1:18000/api/v1/scenarios/uc-camera-recording/variants/UHD60-HDR10-H265/graph" | python3 -m json.tool
```

## systemd: FastAPI

Create `/etc/systemd/system/scenariodb-api.service`:

```ini
[Unit]
Description=ScenarioDB FastAPI service
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=scenariodb
Group=scenariodb
WorkingDirectory=/opt/scenariodb/implementation
EnvironmentFile=/opt/scenariodb/implementation/.env
ExecStart=/opt/scenariodb/implementation/.venv/bin/uvicorn scenario_db.api.app:app --host 127.0.0.1 --port 18000
Restart=on-failure
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now scenariodb-api
sudo systemctl status scenariodb-api
journalctl -u scenariodb-api -f
```

If `.venv/bin/uvicorn` does not exist, use:

```ini
ExecStart=/opt/scenariodb/implementation/.venv/bin/python -m uvicorn scenario_db.api.app:app --host 127.0.0.1 --port 18000
```

## systemd: Viewer

Create `/etc/systemd/system/scenariodb-viewer.service`:

```ini
[Unit]
Description=ScenarioDB Streamlit viewer
After=network-online.target scenariodb-api.service
Wants=network-online.target

[Service]
Type=simple
User=scenariodb
Group=scenariodb
WorkingDirectory=/opt/scenariodb/implementation
EnvironmentFile=/opt/scenariodb/implementation/.env
ExecStart=/opt/scenariodb/implementation/.venv/bin/streamlit run dashboard/Home.py --server.port 18502 --server.address 127.0.0.1 --server.headless true
Restart=on-failure
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now scenariodb-viewer
sudo systemctl status scenariodb-viewer
journalctl -u scenariodb-viewer -f
```

If `.venv/bin/streamlit` does not exist, use:

```ini
ExecStart=/opt/scenariodb/implementation/.venv/bin/python -m streamlit run dashboard/Home.py --server.port 18502 --server.address 127.0.0.1 --server.headless true
```

## nginx Reverse Proxy

Create `/etc/nginx/sites-available/scenariodb`:

```nginx
server {
    listen 80;
    server_name scenariodb.internal;

    client_max_body_size 20m;

    location /api/ {
        proxy_pass http://127.0.0.1:18000/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /docs {
        proxy_pass http://127.0.0.1:18000/docs;
        proxy_set_header Host $host;
    }

    location /openapi.json {
        proxy_pass http://127.0.0.1:18000/openapi.json;
        proxy_set_header Host $host;
    }

    location /viewer/ {
        proxy_pass http://127.0.0.1:18502/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable:

```bash
sudo ln -s /etc/nginx/sites-available/scenariodb /etc/nginx/sites-enabled/scenariodb
sudo nginx -t
sudo systemctl reload nginx
```

If Streamlit path-prefix behavior is problematic, use a separate host such as
`scenariodb-viewer.internal` instead of `/viewer/`.

## Firewall

Expose only what is needed internally:

```bash
sudo ufw allow from <internal-subnet> to any port 80 proto tcp
sudo ufw deny 5432/tcp
sudo ufw deny 18000/tcp
sudo ufw deny 18502/tcp
sudo ufw enable
sudo ufw status
```

If nginx is not used, expose `18000` and `18502` only to trusted internal
subnets.

## Write API Server Checks

After deployment:

```bash
api="http://127.0.0.1:18000/api/v1"
payload="$(cat demo/write_payloads/variant_overlay_valid.json)"
stage="$(curl -s -X POST "$api/write/staging" -H "Content-Type: application/json" -d "$payload")"
echo "$stage" | python3 -m json.tool
batch_id="$(echo "$stage" | python3 -c 'import json,sys; print(json.load(sys.stdin)["batch_id"])')"
curl -s -X POST "$api/write/staging/$batch_id/validate" | python3 -m json.tool
curl -s -X POST "$api/write/staging/$batch_id/diff" | python3 -m json.tool
curl -s -X POST "$api/write/staging/$batch_id/apply" | python3 -m json.tool
```

Check effective topology:

```bash
curl -s "$api/scenarios/uc-camera-recording/variants/FHD30-SDR-H265-runbook/graph" | python3 -m json.tool
```

## Test On Ubuntu

Unit tests:

```bash
uv run --group dev pytest tests/unit
```

Integration tests require Docker:

```bash
uv run --group dev pytest tests/integration
```

If Docker access fails:

```bash
sudo usermod -aG docker scenariodb
sudo systemctl restart docker
```

Then log out and back in as `scenariodb`.

## Update Procedure

```bash
sudo -iu scenariodb
cd /opt/scenariodb/implementation
git pull --ff-only
uv sync --group dashboard
set -a
source .env
set +a
uv run alembic upgrade head
sudo systemctl restart scenariodb-api
sudo systemctl restart scenariodb-viewer
```

Smoke check:

```bash
curl -s http://127.0.0.1:18000/health/ready
curl -s http://127.0.0.1:18000/api/v1/scenarios | python3 -m json.tool
```

## Backup And Restore

Backup:

```bash
mkdir -p /opt/scenariodb/backups
pg_dump "$DATABASE_URL" > "/opt/scenariodb/backups/scenario_db_$(date +%Y%m%d_%H%M%S).sql"
```

Restore to an empty DB:

```bash
psql "$DATABASE_URL" < /opt/scenariodb/backups/scenario_db_YYYYMMDD_HHMMSS.sql
```

For production use, put backup under cron or the internal backup system.

## Operational Notes

- Do not keep default DB or pgAdmin passwords.
- Do not expose PostgreSQL to the full company network unless required.
- Keep `.env` out of git and restrict file permissions.
- Run Alembic migrations before starting a newly pulled API version.
- Reload fixtures only for demo/test systems. For real data, prefer Write API.
- Watch `journalctl -u scenariodb-api` during first deployment and after schema changes.
- Treat `routing_switch` and `topology_patch` as variant overlay data. They do not modify the base scenario topology.

## Current Gaps Before Production Hardening

These are not blockers for internal prototype usage, but should be addressed
before broader deployment:

- Authentication and authorization are not implemented yet.
- Write API audit records exist, but actor identity is currently client-supplied.
- No role separation between read-only users and write users.
- No automatic DB backup job is included in the repo.
- nginx TLS is not configured in this document.
- Streamlit behind a subpath may need additional testing in the target network.
