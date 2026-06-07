from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from scenario_db.api.schemas.cdgm import CdgmResolveRequest
from scenario_db.cdgm.resolver import resolve_cdgm_arch_info
from scenario_db.db.models.capability import SocCdgmProfile, SocDvfsTable
from scenario_db.db.repositories.scenario_graph import load_canonical_graph


def resolve_cdgm_request(db: Session, request: CdgmResolveRequest) -> dict[str, Any]:
    try:
        graph = load_canonical_graph(db, request.scenario_id, request.variant_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    soc_ref = str(request.soc_ref or _graph_soc_ref(graph) or "")
    dvfs_table = _resolve_dvfs_table(db, request, soc_ref)
    profile = _resolve_cdgm_profile(db, request, soc_ref)
    result = resolve_cdgm_arch_info(
        graph,
        dvfs_domains=(dvfs_table.domains if dvfs_table is not None else {}),
        profile=profile,
    )
    result.update(
        {
            "soc_ref": soc_ref or None,
            "dvfs_table_ref": dvfs_table.id if dvfs_table is not None else None,
            "cdgm_profile_ref": profile.id if profile is not None else None,
        }
    )
    return result


def _resolve_dvfs_table(db: Session, request: CdgmResolveRequest, soc_ref: str) -> SocDvfsTable | None:
    if request.dvfs_table_ref and request.dvfs_version is not None:
        raise HTTPException(status_code=422, detail="dvfs_table_ref cannot be combined with dvfs_version")
    if request.dvfs_table_ref:
        row = db.query(SocDvfsTable).filter_by(id=str(request.dvfs_table_ref)).one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"DVFS table not found: {request.dvfs_table_ref}")
    elif request.dvfs_version is not None:
        if not soc_ref:
            raise HTTPException(status_code=422, detail="soc_ref is required when selecting a DVFS table by dvfs_version")
        row = db.query(SocDvfsTable).filter_by(soc_ref=soc_ref, dvfs_version=request.dvfs_version).one_or_none()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"DVFS table not found for soc_ref={soc_ref} dvfs_version={request.dvfs_version}",
            )
    else:
        return None
    if soc_ref and str(row.soc_ref) != soc_ref:
        raise HTTPException(status_code=422, detail=f"DVFS table {row.id} belongs to {row.soc_ref}, not {soc_ref}")
    return row


def _resolve_cdgm_profile(db: Session, request: CdgmResolveRequest, soc_ref: str) -> SocCdgmProfile | None:
    if request.cdgm_profile_ref and request.cdgm_profile_version is not None:
        raise HTTPException(status_code=422, detail="cdgm_profile_ref cannot be combined with cdgm_profile_version")
    if request.cdgm_profile_ref:
        row = db.query(SocCdgmProfile).filter_by(id=str(request.cdgm_profile_ref)).one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"CDGM profile not found: {request.cdgm_profile_ref}")
    elif request.cdgm_profile_version is not None:
        if not soc_ref:
            raise HTTPException(status_code=422, detail="soc_ref is required when selecting a CDGM profile by profile_version")
        row = db.query(SocCdgmProfile).filter_by(soc_ref=soc_ref, profile_version=request.cdgm_profile_version).one_or_none()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"CDGM profile not found for soc_ref={soc_ref} profile_version={request.cdgm_profile_version}",
            )
    else:
        return None
    if soc_ref and str(row.soc_ref) != soc_ref:
        raise HTTPException(status_code=422, detail=f"CDGM profile {row.id} belongs to {row.soc_ref}, not {soc_ref}")
    return row


def _graph_soc_ref(graph: Any) -> str | None:
    soc = getattr(graph, "soc", None)
    if soc is not None and getattr(soc, "id", None):
        return str(soc.id)
    project = getattr(graph, "project", None)
    if project is None:
        return None
    metadata = getattr(project, "metadata_", None) or {}
    globals_ = getattr(project, "globals_", None) or {}
    return metadata.get("soc_ref") or globals_.get("soc_ref")

