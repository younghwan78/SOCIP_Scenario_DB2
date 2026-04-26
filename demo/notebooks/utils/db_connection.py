"""DB 연결 유틸 — notebooks에서 공통 import."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv  # python-dotenv는 sqlalchemy가 의존성으로 설치함
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# .env 자동 로드 (repo root 기준)
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")


def get_engine(url: str | None = None):
    """SQLAlchemy engine 반환. url 미지정 시 DATABASE_URL 환경변수 사용."""
    db_url = url or os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "DATABASE_URL 환경변수가 설정되지 않았습니다. "
            f"{_REPO_ROOT / '.env'} 파일을 확인하세요."
        )
    return create_engine(db_url, echo=False)


def get_session_factory(engine=None):
    return sessionmaker(bind=engine or get_engine(), expire_on_commit=False)


@contextmanager
def session_scope(engine=None):
    """with session_scope() as session: 패턴."""
    factory = get_session_factory(engine)
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def query_df(sql: str, engine=None, **params):
    """SQL → pandas DataFrame. 파라미터는 :name 스타일."""
    import pandas as pd
    eng = engine or get_engine()
    with eng.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)


def ping(engine=None) -> str:
    """DB 연결 확인. 버전 문자열 반환."""
    eng = engine or get_engine()
    with eng.connect() as conn:
        version = conn.execute(text("SELECT version()")).scalar()
    return version
