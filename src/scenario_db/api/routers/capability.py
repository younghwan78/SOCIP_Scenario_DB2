from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db
from scenario_db.api.pagination import apply_sort, validate_sort_column
from scenario_db.api.schemas.capability import (
    IpCatalogResponse,
    SocPlatformResponse,
    SwComponentResponse,
    SwProfileResponse,
)
from scenario_db.api.schemas.common import PagedResponse
from scenario_db.api.validators import (
    validate_feature_flag_name,
    validate_ip_category,
    validate_sw_component_category,
)
from scenario_db.db.models.capability import IpCatalog, SocPlatform, SwComponent, SwProfile

router = APIRouter(tags=["capability"])


# ---------------------------------------------------------------------------
# SoC Platforms
# ---------------------------------------------------------------------------

@router.get("/soc-platforms", response_model=PagedResponse[SocPlatformResponse])
def list_soc_platforms(
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: str | None = Query(None),
    sort_dir: str = Query("asc"),
    db: Session = Depends(get_db),
):
    """SoC 플랫폼 목록 조회."""
    sort_by = validate_sort_column(SocPlatform, sort_by)
    q = apply_sort(db.query(SocPlatform), SocPlatform, sort_by, sort_dir)
    return PagedResponse.from_query(q, limit=limit, offset=offset)


@router.get("/soc-platforms/{platform_id}", response_model=SocPlatformResponse)
def get_soc_platform(platform_id: str, db: Session = Depends(get_db)):
    row = db.query(SocPlatform).filter_by(id=platform_id).one_or_none()
    if row is None:
        raise NoResultFound(f"SocPlatform '{platform_id}' not found")
    return row


# ---------------------------------------------------------------------------
# IP Catalogs
# ---------------------------------------------------------------------------

@router.get("/ip-catalogs", response_model=PagedResponse[IpCatalogResponse])
def list_ip_catalog(
    category: str | None = Query(None),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: str | None = Query(None),
    sort_dir: str = Query("asc"),
    db: Session = Depends(get_db),
):
    """IP 카탈로그 목록 조회. ?category= 필터 지원."""
    sort_by = validate_sort_column(IpCatalog, sort_by)
    q = db.query(IpCatalog)
    if category is not None:
        validate_ip_category(category)
        q = q.filter(IpCatalog.category == category)
    q = apply_sort(q, IpCatalog, sort_by, sort_dir)
    return PagedResponse.from_query(q, limit=limit, offset=offset)


@router.get("/ip-catalogs/{ip_id}", response_model=IpCatalogResponse)
def get_ip_catalog(ip_id: str, db: Session = Depends(get_db)):
    row = db.query(IpCatalog).filter_by(id=ip_id).one_or_none()
    if row is None:
        raise NoResultFound(f"IpCatalog '{ip_id}' not found")
    return row


# ---------------------------------------------------------------------------
# SW Profiles
# ---------------------------------------------------------------------------

@router.get("/sw-profiles", response_model=PagedResponse[SwProfileResponse])
def list_sw_profiles(
    feature_flag: str | None = Query(None, description="name:value 형식 (예: LLC_per_ip_partition:enabled)"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: str | None = Query(None),
    sort_dir: str = Query("asc"),
    db: Session = Depends(get_db),
):
    """SW 프로필 목록. ?feature_flag=name:value 필터 지원 (JSONB 쿼리)."""
    sort_by = validate_sort_column(SwProfile, sort_by)
    q = db.query(SwProfile)
    if feature_flag is not None:
        if ":" not in feature_flag:
            raise HTTPException(status_code=400, detail="feature_flag 형식: name:value")
        name, value = feature_flag.split(":", 1)
        validate_feature_flag_name(name)
        q = q.filter(SwProfile.feature_flags[name].astext == value)
    q = apply_sort(q, SwProfile, sort_by, sort_dir)
    return PagedResponse.from_query(q, limit=limit, offset=offset)


@router.get("/sw-profiles/{profile_id}", response_model=SwProfileResponse)
def get_sw_profile(profile_id: str, db: Session = Depends(get_db)):
    row = db.query(SwProfile).filter_by(id=profile_id).one_or_none()
    if row is None:
        raise NoResultFound(f"SwProfile '{profile_id}' not found")
    return row


# ---------------------------------------------------------------------------
# SW Components
# ---------------------------------------------------------------------------

@router.get("/sw-components", response_model=PagedResponse[SwComponentResponse])
def list_sw_components(
    category: str | None = Query(None, description="hal | kernel | firmware"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: str | None = Query(None),
    sort_dir: str = Query("asc"),
    db: Session = Depends(get_db),
):
    sort_by = validate_sort_column(SwComponent, sort_by)
    q = db.query(SwComponent)
    if category is not None:
        validate_sw_component_category(category)
        q = q.filter(SwComponent.category == category)
    q = apply_sort(q, SwComponent, sort_by, sort_dir)
    return PagedResponse.from_query(q, limit=limit, offset=offset)
