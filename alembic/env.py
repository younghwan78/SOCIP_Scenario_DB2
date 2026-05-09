from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from scenario_db.db.base import Base
import scenario_db.db.models  # noqa: F401 — 모든 ORM 모델 등록

config = context.config


def _database_url() -> str:
    return (
        os.environ.get("SCENARIO_DB_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or _dotenv_value("SCENARIO_DB_DATABASE_URL")
        or _dotenv_value("DATABASE_URL")
        or ""
    )


def _dotenv_value(key: str) -> str | None:
    env_path = Path(config.config_file_name or "").resolve().parent / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return None


# DATABASE_URL 환경변수 주입 (alembic.ini의 %(DATABASE_URL)s 치환).
# Prefer explicit environment variables, then fall back to the local .env file
# so `uv run alembic upgrade head` behaves like the API process.
config.set_main_option("DATABASE_URL", _database_url())

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
