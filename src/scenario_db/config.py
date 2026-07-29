from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic.aliases import AliasChoices
from pydantic_settings import BaseSettings


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
    # State-changing API calls are deny-by-default. Configure a JSON object of
    # audit identity -> secret, for example {"architect@example.com": "secret"}.
    mutation_api_keys: dict[str, SecretStr] = Field(default_factory=dict)
    # Explicit local-development escape hatch. Never enable on a shared host.
    mutation_auth_disabled: bool = False

    model_config = {"env_prefix": "SCENARIO_DB_", "env_file": ".env", "extra": "ignore"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
