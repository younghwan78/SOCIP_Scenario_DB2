"""Capability 도메인 — SocPlatform, IpCatalog, SwProfile, SwComponent."""
from __future__ import annotations

from sqlalchemy.orm import Session

from scenario_db.api.pagination import apply_sort
from scenario_db.db.models.capability import IpCatalog, SocPlatform, SwComponent, SwProfile


def list_soc_platforms(
    db: Session,
    *,
    limit: int,
    offset: int,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[SocPlatform], int]:
    q = apply_sort(db.query(SocPlatform), SocPlatform, sort_by, sort_dir)
    total = q.count()
    return q.offset(offset).limit(limit).all(), total


def get_soc_platform(db: Session, platform_id: str) -> SocPlatform | None:
    return db.query(SocPlatform).filter_by(id=platform_id).one_or_none()


def list_ip_catalogs(
    db: Session,
    *,
    category: str | None = None,
    limit: int,
    offset: int,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[IpCatalog], int]:
    q = db.query(IpCatalog)
    if category is not None:
        q = q.filter(IpCatalog.category == category)
    q = apply_sort(q, IpCatalog, sort_by, sort_dir)
    total = q.count()
    return q.offset(offset).limit(limit).all(), total


def get_ip_catalog(db: Session, ip_id: str) -> IpCatalog | None:
    return db.query(IpCatalog).filter_by(id=ip_id).one_or_none()


def list_sw_profiles(
    db: Session,
    *,
    feature_flag_name: str | None = None,
    feature_flag_value: str | None = None,
    limit: int,
    offset: int,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[SwProfile], int]:
    q = db.query(SwProfile)
    if feature_flag_name is not None and feature_flag_value is not None:
        q = q.filter(SwProfile.feature_flags[feature_flag_name].astext == feature_flag_value)
    q = apply_sort(q, SwProfile, sort_by, sort_dir)
    total = q.count()
    return q.offset(offset).limit(limit).all(), total


def get_sw_profile(db: Session, profile_id: str) -> SwProfile | None:
    return db.query(SwProfile).filter_by(id=profile_id).one_or_none()


def list_sw_components(
    db: Session,
    *,
    category: str | None = None,
    limit: int,
    offset: int,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[SwComponent], int]:
    q = db.query(SwComponent)
    if category is not None:
        q = q.filter(SwComponent.category == category)
    q = apply_sort(q, SwComponent, sort_by, sort_dir)
    total = q.count()
    return q.offset(offset).limit(limit).all(), total
