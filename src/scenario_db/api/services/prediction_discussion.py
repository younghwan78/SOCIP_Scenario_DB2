"""Collaboration records leave the original prediction metrics and inputs untouched."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.orm import Session, load_only

from scenario_db.api.schemas.prediction_discussion import PredictionCommentRequest, PredictionNoteRequest
from scenario_db.db.models.exploration import Prediction, PredictionComment, PredictionNote
from scenario_db.exceptions import ConflictError, NotFoundError, UnprocessableError

_NOTE_FIELDS = ("title", "purpose", "description", "assumptions", "conclusion", "tags")


def _prediction(db: Session, prediction_id: str, *, lock: bool = False) -> Prediction:
    query = db.query(Prediction).options(load_only(cast(Any, Prediction.id))).filter_by(id=prediction_id)
    if lock:
        query = query.populate_existing().with_for_update()
    prediction = query.one_or_none()
    if prediction is None:
        raise NotFoundError(f"prediction not found: {prediction_id}")
    return prediction


def _note_dict(prediction_id: str, row: PredictionNote | None) -> dict[str, Any]:
    if row is None:
        return {"prediction_id": prediction_id, **{key: [] if key == "tags" else "" for key in _NOTE_FIELDS},
                "revision": 0, "created_by": None, "updated_by": None, "created_at": None, "updated_at": None}
    return {"prediction_id": prediction_id, **{key: getattr(row, key) for key in _NOTE_FIELDS},
            "revision": row.revision, "created_by": row.created_by, "updated_by": row.updated_by,
            "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}


def get_notes(db: Session, prediction_id: str) -> dict[str, Any]:
    _prediction(db, prediction_id)
    return _note_dict(prediction_id, db.get(PredictionNote, prediction_id))


def put_notes(db: Session, prediction_id: str, request: PredictionNoteRequest, actor: str) -> dict[str, Any]:
    # The stable prediction row serializes even two first saves, where a note row does not yet exist.
    _prediction(db, prediction_id, lock=True)
    # Legacy Column mappings expose instance values dynamically at runtime.
    row: Any = db.query(PredictionNote).filter_by(prediction_ref=prediction_id).populate_existing().one_or_none()
    revision = row.revision if row is not None else 0
    if request.expected_revision != revision:
        raise ConflictError(f"prediction notes changed (current revision {revision}); reload before saving")
    now = datetime.now(UTC)
    if row is None:
        row = PredictionNote(prediction_ref=prediction_id, created_by=actor, created_at=now)
        db.add(row)
    for key in _NOTE_FIELDS:
        setattr(row, key, getattr(request, key))
    row.revision = revision + 1
    row.updated_by = actor
    row.updated_at = now
    db.flush()
    result = _note_dict(prediction_id, row)
    db.commit()
    return result


def _comment_dict(row: PredictionComment) -> dict[str, Any]:
    return {"id": row.id, "prediction_id": row.prediction_ref, "parent_id": row.parent_ref,
            "body": row.body, "created_by": row.created_by, "created_at": row.created_at.isoformat()}


def list_comments(db: Session, prediction_id: str, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    _prediction(db, prediction_id)
    query = db.query(PredictionComment).filter_by(prediction_ref=prediction_id)
    total = query.count()
    # Database insertion order is independent of application clock precision or clock corrections.
    items = query.order_by(PredictionComment.sequence).offset(offset).limit(limit).all()
    return {"prediction_id": prediction_id, "items": [_comment_dict(row) for row in items],
            "total": total, "limit": limit, "offset": offset}


def add_comment(db: Session, prediction_id: str, request: PredictionCommentRequest, actor: str) -> dict[str, Any]:
    _prediction(db, prediction_id)
    if request.parent_id is not None:
        parent = db.get(PredictionComment, request.parent_id)
        if parent is None or parent.prediction_ref != prediction_id:
            raise UnprocessableError("reply parent must be a comment on the same prediction")
    row = PredictionComment(id=f"PCOM-{uuid4().hex}", prediction_ref=prediction_id, parent_ref=request.parent_id,
                            body=request.body, created_by=actor, created_at=datetime.now(UTC))
    db.add(row)
    db.flush()
    result = _comment_dict(row)
    db.commit()
    return result
