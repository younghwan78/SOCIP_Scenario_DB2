# Linux (Ubuntu) 서버 실행 가이드

사내 Ubuntu 서버에서 ScenarioDB를 올리고 authoring 변경을 반영하는 방법.
Windows의 `scripts/dev_up.ps1`에 대응하는 스크립트는 `scripts/dev_up.sh` / `scripts/dev_down.sh`다.

## 1. 준비 (최초 1회)

| 항목 | 명령 / 비고 |
|---|---|
| Python 3.11+, uv | `curl -LsSf https://astral.sh/uv/install.sh \| sh` (사내 mirror가 있으면 `pip install uv`) |
| Node.js 24 (UI) | CI와 동일 버전. UI를 안 쓰면 `--no-ui` |
| PostgreSQL 16 | Docker(`docker compose`) 또는 기존 PostgreSQL 서버 (`--no-docker`) |
| 의존성 | `uv sync --frozen --group dev --group dashboard --group sim` (`--extra profiling`은 Perfetto trace import가 필요할 때) |
| `.env` | `[ -f .env ] \|\| cp .env.example .env` 후 DB URL과 API secret 수정. Git에 올리지 않는다 |

```bash
cd <repo>/implementation
uv sync --frozen --group dev --group dashboard --group sim
(cd ui && npm ci)
[ -f .env ] || cp .env.example .env
```

Docker 없이 기존 PostgreSQL을 쓸 때 (DB/계정은 한 번만 만든다):

```bash
sudo -u postgres psql -c "create user scenario_user password '<strong-password>'"
sudo -u postgres psql -c "create database scenario_db owner scenario_user"
# .env
SCENARIO_DB_DATABASE_URL=postgresql+psycopg2://scenario_user:<strong-password>@localhost:5432/scenario_db
```

## 2. dev_up.sh

```bash
scripts/dev_up.sh                     # docker PG → migrate → rename/retire → ETL 2600 → [sync → 실측 import → ETL] 2700 → API + UI
scripts/dev_up.sh --no-docker         # .env / 환경변수의 DB URL 사용
scripts/dev_up.sh --no-ui             # API만 (authoring 반영 후 확인용)
scripts/dev_up.sh --load-only         # DB 적재만, 서버 안 띄움 (cron / CI)
scripts/dev_up.sh --skip-load         # 적재 없이 서버만
scripts/dev_up.sh --streamlit         # Streamlit 추가 (18502)
scripts/dev_up.sh --project sm-s957b=db_Exynos2700_SM-S957B --project explore-2600=db_explore
scripts/dev_down.sh                   # API / UI / Streamlit 정지 (PostgreSQL은 유지)
```

| 옵션 | PowerShell 대응 | 설명 |
|---|---|---|
| `--project KEY=DIR` (반복) | `-AuthoringProjects @{KEY="DIR"}` | 기본 `sm-s957b=db_Exynos2700_SM-S957B` |
| `--skip-load` | `-SkipLoad` | |
| `--no-ui` | `-NoUi` | |
| `--streamlit` | `-Streamlit` | |
| `--no-docker` | — | 기존 PostgreSQL |
| `--load-only` | — | 서버를 띄우지 않음 |
| `--bind HOST`, `--api-port`, `--ui-port` | — | 기본 `127.0.0.1`, 18000, 3000 |

- 서버는 백그라운드로 뜨고 로그는 `output/dev/{api,ui,streamlit}.log`, pid는 `output/dev/*.pid`다.
- 각 단계가 실패하면 즉시 멈춘다. ETL 결과는 `output/etl/*.json`, 삭제 백업은 `output/etl/*-backup-*.json`.
- 이미 떠 있는 서버는 다시 띄우지 않는다. 코드/DB 변경 후에는 `scripts/dev_down.sh && scripts/dev_up.sh --skip-load`.

## 3. PC 브라우저에서 접속

권장: 서버는 `127.0.0.1`에만 두고 **SSH 터널**로 접속한다. 인증 설정 없이 안전하다.

```bash
# PC에서
ssh -L 3000:127.0.0.1:3000 -L 18000:127.0.0.1:18000 <user>@<server>
# 브라우저: http://localhost:3000
```

`--bind 0.0.0.0`으로 직접 노출할 때:

- React의 조합 탐색·Timing Budget은 보호된 POST API를 API key 없이 호출한다.
  `.env`의 `SCENARIO_DB_MUTATION_AUTH_DISABLED=true`는 **localhost 전용**이며, `--bind`가 localhost가 아니면 dev_up.sh가 실행을 거부한다.
- 여러 사람이 쓰는 서버에서는 `SCENARIO_DB_API_PRINCIPALS`를 설정하고 방화벽으로 사내 대역만 허용한다
  (`sudo ufw allow from <사내대역> to any port 3000,18000 proto tcp`).
- DB 포트(15432/5432)는 외부에 열지 않는다.

## 4. authoring 변경 반영 (서버에서)

```bash
uv run python -m scenario_db.authoring compile sm-s957b --out output/preview
uv run python -m scenario_db.authoring sync sm-s957b --fixture db_Exynos2700_SM-S957B --to fixture --dry-run
uv run python -m scenario_db.authoring sync sm-s957b --fixture db_Exynos2700_SM-S957B --to fixture --prune
uv run python scripts/generate_simulation_evidence.py db_Exynos2700_SM-S957B uc-cam-recording-e2700
scripts/dev_down.sh && scripts/dev_up.sh --no-ui
uv run --group dev pytest -q tests/unit/authoring tests/unit/test_exynos2700_db_contract.py
```

## 5. PowerShell 명령을 bash로 옮기기

문서의 예시 중 PowerShell로 된 것은 아래처럼 바꿔 실행한다.

| PowerShell | bash |
|---|---|
| `.\.venv\Scripts\python.exe -m X` | `uv run python -m X` (또는 `.venv/bin/python -m X`) |
| `$env:DATABASE_URL="..."` | `export DATABASE_URL="..."` |
| 줄 끝 `` ` `` (줄 이음) | 줄 끝 `\` |
| `scripts\x.py`, `output\etl` | `scripts/x.py`, `output/etl` |
| `$env:TEMP\dir` | `/tmp/dir` (또는 `$(mktemp -d)`) |
| `Copy-Item -Recurse a b` | `cp -r a b` |
| `if (-not (Test-Path .env)) { Copy-Item .env.example .env }` | `[ -f .env ] \|\| cp .env.example .env` |
| `Start-Process powershell ... uvicorn ...` | `scripts/dev_up.sh --skip-load --no-ui` (또는 `nohup uv run ... &`) |
| `powershell -ExecutionPolicy Bypass -File scripts\dev_up.ps1 -NoUi` | `scripts/dev_up.sh --no-ui` |

Windows 전용으로 남아 있는 스크립트:
- `scripts/cleanup_runtime_outputs.ps1`: bash에서는 `rm -rf output/<run>` 등으로 직접 정리한다.
- `install_memory_commit_hook.ps1`, `write_memory_commit_note.ps1`: 개인 개발 PC용. 서버에는 필요 없다.

## 6. 자주 겪는 문제

| 증상 | 원인 / 해결 |
|---|---|
| `'uv' not found` | uv 설치 후 새 shell (`~/.local/bin` PATH) |
| `postgres not healthy` | `docker compose logs postgres`. 권한 문제면 사용자를 `docker` 그룹에 추가 |
| `--no-docker needs ... DATABASE_URL` | `.env`에 `SCENARIO_DB_DATABASE_URL=` 추가 |
| UI 3000 포트 사용 중 | `scripts/dev_down.sh`, 또는 `--ui-port 3100` (`--strictPort`라 다른 포트로 넘어가지 않는다) |
| 조합 탐색에서 503/401 | API 인증 미설정: localhost + `SCENARIO_DB_MUTATION_AUTH_DISABLED=true`, 또는 principals 설정 |
| 파일 경로에 `\` | 문서의 Windows 경로 → `/` |
