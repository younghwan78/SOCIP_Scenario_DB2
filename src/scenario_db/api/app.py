from __future__ import annotations

import time as _time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine

from scenario_db.api.cache import RuleCache
from scenario_db.api.exceptions import register_handlers
from scenario_db.api.routers import capability, decision, definition, evidence, explorer, runtime, write
from scenario_db.api.routers.utility import health_router
from scenario_db.api.routers import view as view_router
from scenario_db.config import get_settings
from scenario_db.db.session import make_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    is_sqlite = settings.database_url.startswith("sqlite")
    engine = create_engine(
        settings.database_url,
        **(
            {}
            if is_sqlite
            else {
                "pool_size": settings.db_pool_size,
                "max_overflow": settings.db_max_overflow,
                "pool_pre_ping": True,
                "pool_recycle": 3600,
            }
        ),
    )
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.rule_cache = RuleCache.load_with_retry(app.state.session_factory)
    app.state.start_time = _time.time()
    yield
    engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="ScenarioDB API",
        version="0.1.0",
        description="Mobile SoC Multimedia IP Scenario Database — REST API",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    register_handlers(app)

    # /health/live, /health/ready — prefix 없음
    app.include_router(health_router)

    # /api/v1/*
    for r in [
        capability.router,
        definition.router,
        evidence.router,
        decision.router,
        runtime.router,
        explorer.router,
        view_router.router,
        write.router,
    ]:
        app.include_router(r, prefix="/api/v1")

    return app


app = create_app()
