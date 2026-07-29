from __future__ import annotations

from functools import lru_cache

from typing import Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic.aliases import AliasChoices
from pydantic_settings import BaseSettings


ApiRole = Literal["reader", "analyst", "writer", "admin"]


class ApiPrincipalSettings(BaseModel):
    secret: SecretStr
    roles: set[ApiRole] = Field(min_length=1)


class Settings(BaseSettings):
    # SCENARIO_DB_DATABASE_URL 우선, 없으면 DATABASE_URL 읽음 (기존 .env 호환)
    database_url: str = Field(
        validation_alias=AliasChoices("SCENARIO_DB_DATABASE_URL", "DATABASE_URL"),
    )
    api_port: int = 8000
    cors_origins: list[str] = ["http://localhost:8501", "http://localhost:3000"]
    log_level: str = "INFO"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    report_dir: str = "output_simulation"
    allow_custom_report_dir: bool = False
    # Internal ops endpoints (/api/v1/admin/*) — default off; enable only on
    # trusted networks (VPN) via SCENARIO_DB_ADMIN_ENDPOINTS_ENABLED=true.
    admin_endpoints_enabled: bool = False
    # /query/facets response cache TTL in seconds. 0 disables the cache;
    # write apply invalidates it regardless of TTL.
    query_facets_cache_ttl_seconds: float = 0.0
    # Per-worker decision-rule cache maximum staleness. 0 refreshes on every
    # rule-dependent request; a small positive value bounds multi-worker drift.
    rule_cache_ttl_seconds: float = 5.0
    # Architecture Query materializes effective topology facts in Python after
    # SQL prefiltering. These bounds prevent an unscoped request from turning
    # into an unbounded process-memory scan.
    query_max_candidates: int = Field(default=5_000, ge=1)
    query_max_evidence_rows: int = Field(default=20_000, ge=1)
    query_max_issue_rows: int = Field(default=5_000, ge=1)
    query_facets_max_candidates: int = Field(default=10_000, ge=1)
    # API authentication is deny-by-default. Prefer role-bearing principals:
    # {"architect@example.com":{"secret":"...","roles":["writer"]}}.
    api_principals: dict[str, ApiPrincipalSettings] = Field(default_factory=dict)
    # Deprecated compatibility path. Legacy keys receive all protected-operation
    # roles so existing deployments can migrate without an outage.
    mutation_api_keys: dict[str, SecretStr] = Field(default_factory=dict)
    # Explicit local-development escape hatch. Never enable on a shared host.
    mutation_auth_disabled: bool = False

    model_config = {"env_prefix": "SCENARIO_DB_", "env_file": ".env", "extra": "ignore"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
