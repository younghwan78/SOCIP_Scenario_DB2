from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import CheckConstraint

from scenario_db.api.schemas.write import DiffPreviewResponse
from scenario_db.db.models.evidence import Evidence
from scenario_db.db.models.write import WriteBatch, WriteEvent
from scenario_db.write import service as write_service

ROOT = Path(__file__).resolve().parents[2]


class _BatchQuery:
    def __init__(self, batch, session=None):
        self.batch = batch
        self.session = session

    def filter_by(self, **kwargs):
        return self

    def with_for_update(self):
        if self.session is not None:
            self.session.locked = True
        return self

    def one_or_none(self):
        return self.batch


class _FakeSession:
    def __init__(self, batch):
        self.batch = batch
        self.committed = False
        self.locked = False

    def query(self, model):
        return _BatchQuery(self.batch, self)

    def add(self, row) -> None:
        return None

    def commit(self) -> None:
        self.committed = True


def _batch(status: str):
    return SimpleNamespace(
        id="batch-1",
        kind=write_service.VARIANT_OVERLAY_KIND,
        raw_payload={},
        normalized_payload={"scenario_ref": "scenario-1", "variant": {"id": "variant-1"}},
        validation_result={"valid": True, "issues": []},
        actor="tester",
        status=status,
        diff_result={},
        applied_refs=None,
        updated_at=None,
    )


def test_validate_batch_rejects_already_applied_batch() -> None:
    with pytest.raises(HTTPException) as exc_info:
        write_service.validate_batch(_FakeSession(_batch("applied")), "batch-1")

    assert exc_info.value.status_code == 409
    assert "Cannot validate write batch in status 'applied'" in str(exc_info.value.detail)


def test_diff_batch_requires_validated_status(monkeypatch) -> None:
    monkeypatch.setattr(
        write_service,
        "build_write_diff",
        lambda db, kind, normalized: DiffPreviewResponse(
            batch_id="batch-1",
            target_id="scenario-1::variant-1",
            operation="update",
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        write_service.diff_batch(_FakeSession(_batch("staged")), "batch-1")

    assert exc_info.value.status_code == 409
    assert "Cannot diff write batch in status 'staged'" in str(exc_info.value.detail)


def test_apply_batch_requires_diff_ready_status(monkeypatch) -> None:
    monkeypatch.setattr(
        write_service,
        "_apply_variant_overlay",
        lambda db, normalized: {"scenario_ref": "scenario-1", "variant_id": "variant-1"},
    )

    with pytest.raises(HTTPException) as exc_info:
        write_service.apply_batch(_FakeSession(_batch("validated")), "batch-1")

    assert exc_info.value.status_code == 409
    assert "Cannot apply write batch in status 'validated'" in str(exc_info.value.detail)


def test_state_transitions_fetch_batch_with_row_lock(monkeypatch) -> None:
    """Regression: validate/diff/apply must lock the batch row to serialize
    concurrent state transitions (two applies of one diff_ready batch)."""
    monkeypatch.setattr(
        write_service,
        "_apply_variant_overlay",
        lambda db, normalized: {"scenario_ref": "scenario-1", "variant_id": "variant-1"},
    )
    monkeypatch.setattr(
        write_service,
        "build_write_diff",
        lambda db, kind, normalized: DiffPreviewResponse(
            batch_id="batch-1",
            target_id="scenario-1::variant-1",
            operation="update",
        ),
    )
    monkeypatch.setattr(
        write_service,
        "normalize_write_payload",
        lambda kind, payload: {"scenario_ref": "scenario-1", "variant": {"id": "variant-1"}},
    )
    monkeypatch.setattr(write_service, "validate_write_payload", lambda db, kind, normalized: [])

    validate_session = _FakeSession(_batch("staged"))
    write_service.validate_batch(validate_session, "batch-1")
    assert validate_session.locked is True

    diff_session = _FakeSession(_batch("validated"))
    write_service.diff_batch(diff_session, "batch-1")
    assert diff_session.locked is True

    apply_session = _FakeSession(_batch("diff_ready"))
    write_service.apply_batch(apply_session, "batch-1")
    assert apply_session.locked is True


def _constraint_names(table) -> set[str]:
    return {constraint.name for constraint in table.constraints if isinstance(constraint, CheckConstraint)}


def test_write_and_evidence_models_declare_domain_constraints() -> None:
    assert "ck_write_batches_kind" in _constraint_names(WriteBatch.__table__)
    assert "ck_write_batches_status" in _constraint_names(WriteBatch.__table__)
    assert "ck_write_events_action" in _constraint_names(WriteEvent.__table__)
    assert "ck_evidence_kind" in _constraint_names(Evidence.__table__)


def test_alembic_migration_declares_domain_constraints() -> None:
    migration = (ROOT / "alembic" / "versions" / "0007_write_state_constraints.py").read_text(
        encoding="utf-8"
    )

    assert "ck_write_batches_kind" in migration
    assert "ck_write_batches_status" in migration
    assert "ck_write_events_action" in migration
    assert "ck_evidence_kind" in migration
