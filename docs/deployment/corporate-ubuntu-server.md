# 사내 Ubuntu Server 배포 가이드

로컬 Windows 개발 환경에서 사내망 Ubuntu Server로 전환할 때 수정/확인이 필요한 항목을 정리합니다.

---

## 1. `docker-compose.yml` — 포트 바인딩 + 비밀번호

현재 설정은 로컬 개발용이라 기본 비밀번호와 전체 바인딩 상태입니다.

```yaml
# 현재 (위험)
ports:
  - "5432:5432"   # 모든 인터페이스에 오픈

# 사내망 서버용 — 필요한 IP만 허용
ports:
  - "127.0.0.1:5432:5432"   # localhost only (앱과 같은 서버면)
  # 또는
  - "192.168.x.x:5432:5432" # 사내 IP만

environment:
  POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}  # .env에서 주입, 하드코딩 금지
```

> pgAdmin은 사내망이라도 웹 노출이 부담스러우면 제거하고 `psql` 또는 DBeaver로 대체 권장.

---

## 2. `.env` — 접속 정보 분리

```env
# 로컬
DATABASE_URL=postgresql+psycopg2://scenario_user:scenario_pass@localhost:5432/scenario_db

# 사내 서버 (클라이언트 PC에서 원격 접속 시)
DATABASE_URL=postgresql+psycopg2://scenario_user:강한비밀번호@192.168.x.x:5432/scenario_db

# 서버 내부에서 직접 실행 시
DATABASE_URL=postgresql+psycopg2://scenario_user:강한비밀번호@localhost:5432/scenario_db
```

> `.env`는 절대 Git에 올리면 안 됩니다 — 이미 `.gitignore`에 포함되어 있습니다.

---

## 3. Jupyter — 원격 접속 설정

현재 `jupyter lab`은 localhost에서만 열립니다. 사내 서버에서 실행하고 PC 브라우저로 접속하려면:

```bash
# 서버에서 실행
uv run --group notebook jupyter lab \
  --ip=0.0.0.0 \
  --port=8888 \
  --no-browser \
  --NotebookApp.token='사내용토큰' \
  demo/notebooks/
```

방화벽에서 8888 포트 허용:

```bash
sudo ufw allow from 192.168.0.0/16 to any port 8888
```

---

## 4. 실데이터 관리 — Git 전략

현재 `demo/fixtures/`는 공개 GitHub에 올라가 있습니다. 실데이터를 추가할 때:

```
# 옵션 A: fixtures 디렉토리 분리
demo/fixtures/          ← demo 데이터만 (public repo 유지)
data/fixtures/          ← 실데이터 (.gitignore 추가 or private repo)

# 옵션 B: 사내 GitLab/Gerrit private repo로 전환
git remote set-url origin git@gitlab.사내도메인:팀/scenariodb.git
```

`.gitignore`에 추가:

```
data/
real_fixtures/
*.confidential.yaml
```

---

## 5. uv / Python 환경 — 오프라인 설치

사내망이 인터넷 차단이면 PyPI 접근 불가합니다.

```bash
# 확인: 인터넷 연결 여부
curl -I https://pypi.org

# 사내 PyPI 미러가 있으면
uv sync --index-url http://사내미러/simple/

# 완전 오프라인이면 — PC에서 wheel 미리 다운로드 후 서버 복사
# PC에서:
uv export --format requirements-txt > requirements.txt
pip download -r requirements.txt -d ./wheels/

# 서버에서:
uv pip install --no-index --find-links ./wheels/ -r requirements.txt
```

---

## 변경 불필요한 부분

| 구성요소 | 이유 |
|----------|------|
| Pydantic 모델 / ETL 코드 | OS 무관 |
| Alembic 마이그레이션 | DB URL만 다르면 동일 |
| 노트북 쿼리 로직 | `get_engine()`이 `.env` 읽어서 자동 처리 |
| `docker-compose.yml` 서비스 구조 | Ubuntu Docker CE에서 그대로 동작 |
| pytest | 동일 |

---

## 체크리스트

배포 전 반드시 확인:

- [ ] `.env` 비밀번호 강화 (`openssl rand -base64 32`)
- [ ] `docker-compose.yml` 포트를 `127.0.0.1:5432:5432`로 제한
- [ ] 실데이터용 디렉토리를 `.gitignore`에 추가
- [ ] 방화벽 규칙 설정 (5432, 8888 포트)
- [ ] PyPI 접근 가능 여부 확인 (오프라인이면 wheel 사전 준비)
- [ ] Jupyter 토큰/비밀번호 설정
