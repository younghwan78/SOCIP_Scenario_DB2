from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from testcontainers.postgres import PostgresContainer

from scenario_db.api.app import create_app
from scenario_db.api.cache import RuleCache
from scenario_db.api.deps import get_db, get_rule_cache
from scenario_db.db.session import make_session_factory
from scenario_db.etl.loader import load_yaml_dir

pytestmark = pytest.mark.integration

DEMO_FIXTURES = Path(__file__).parent.parent.parent / "demo" / "fixtures"
ALEMBIC_INI = Path(__file__).parent.parent.parent / "alembic.ini"


# ---------------------------------------------------------------------------
# 1. PostgreSQL container (session scope — 테스트 세션당 1회 기동)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def pg():
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


# ---------------------------------------------------------------------------
# 2. Engine + Alembic migration + ETL (session scope — 1회만 실행)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def engine(pg):
    url = pg.get_connection_url()
    if "postgresql+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

    os.environ["DATABASE_URL"] = url

    eng = create_engine(url, pool_pre_ping=True)

    from alembic import command
    from alembic.config import Config
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    with Session(eng) as session:
        counts = load_yaml_dir(DEMO_FIXTURES, session)
        loaded = sum(counts.values())
        assert loaded > 0, f"ETL 로딩 실패: {counts}"

    yield eng
    eng.dispose()


# ---------------------------------------------------------------------------
# 3. RuleCache (session scope — 한 번 로드 후 공유)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def rule_cache(engine):
    with Session(engine) as session:
        return RuleCache.load(session)


# ---------------------------------------------------------------------------
# 4. TestClient (session scope — noop lifespan + 의존성 주입)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def api_client(engine, rule_cache):
    app = create_app()
    sf = make_session_factory(engine)

    @asynccontextmanager
    async def _noop_lifespan(a):
        a.state.engine = engine
        a.state.session_factory = sf
        a.state.rule_cache = rule_cache
        a.state.start_time = time.time()
        yield

    app.router.lifespan_context = _noop_lifespan

    def _get_db():
        session = sf()
        try:
            yield session
        finally:
            session.close()

    def _get_cache():
        return rule_cache

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_rule_cache] = _get_cache

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client

    app.dependency_overrides.clear()
