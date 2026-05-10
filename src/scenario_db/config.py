from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic.aliases import AliasChoices
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # SCENARIO_DB_DATABASE_URL 우선, 없으면 DATABASE_URL 읽음 (기존 .env 호환)
    database_url: str = Field(
        default="sqlite:///:memory:",
        validation_alias=AliasChoices("SCENARIO_DB_DATABASE_URL", "DATABASE_URL"),
    )
    api_port: int = 8000
    cors_origins: list[str] = ["http://localhost:8501", "http://localhost:3000"]
    log_level: str = "INFO"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    model_config = {"env_prefix": "SCENARIO_DB_", "env_file": ".env", "extra": "ignore"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
