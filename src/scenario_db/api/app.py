from __future__ import annotations

import logging
import time as _time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import create_engine

from scenario_db.api.cache import RuleCache
from scenario_db.api.performance import PerformanceMiddleware, install_sql_observers
from scenario_db.api.services.cpu import shutdown_cpu_pool
from scenario_db.api.services.whatif_jobs import shutdown_whatif_jobs
from scenario_db.api.exceptions import register_handlers
from scenario_db.api.routers import admin, capability, catalog, cdgm, decision, definition, evidence, exploration, explorer, query, runtime, simulation, write
from scenario_db.api.routers.utility import health_router
from scenario_db.api.routers import behavior, camera_profiling, sensors, driver_models, sim_inputs
from scenario_db.api.routers import timing_budget as timing_budget_router
from scenario_db.api.routers import arch_exploration as arch_exploration_router
from scenario_db.api.routers import calibration as calibration_router
from scenario_db.api.routers import model_basis as model_basis_router
from scenario_db.api.routers import cpu as cpu_router
from scenario_db.api.routers import review as review_router
from scenario_db.api.routers import scenario_whatif as scenario_whatif_router
from scenario_db.api.routers import view as view_router
from scenario_db.config import get_settings
from scenario_db.db.session import make_session_factory


def configure_logging(settings) -> None:
    level = getattr(logging, str(settings.log_level).upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger("scenario_db").setLevel(level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings)
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
    app.state.rule_cache_ttl_seconds = settings.rule_cache_ttl_seconds
    app.state.start_time = _time.time()
    remove_performance_hooks = install_sql_observers(engine) if settings.performance_log_enabled else None
    try:
        yield
    finally:
        try:
            shutdown_whatif_jobs()
            shutdown_cpu_pool()
        finally:
            try:
                if remove_performance_hooks is not None:
                    remove_performance_hooks()
            finally:
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
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    # JSON lists (variant matrix, run summaries, prediction board) compress ~5-10x
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
    if settings.performance_log_enabled:
        app.add_middleware(PerformanceMiddleware)

    register_handlers(app)

    # /health/live, /health/ready — prefix 없음
    app.include_router(health_router)

    # /api/v1/*
    routers = [
        capability.router,
        sensors.router,
        driver_models.router,
        sim_inputs.router,
        behavior.router,
        catalog.router,
        cdgm.router,
        definition.router,
        evidence.router,
        camera_profiling.router,
        decision.router,
        runtime.router,
        explorer.router,
        query.router,
        exploration.router,
        simulation.router,
        timing_budget_router.router,
        arch_exploration_router.router,
        calibration_router.router,
        model_basis_router.router,
        cpu_router.router,
        review_router.router,
        scenario_whatif_router.router,
        view_router.router,
        write.router,
    ]
    # Internal ops router stays off unless explicitly enabled (VPN-only tool).
    if settings.admin_endpoints_enabled:
        routers.append(admin.router)
    for r in routers:
        app.include_router(r, prefix="/api/v1")

    return app


app = create_app()
