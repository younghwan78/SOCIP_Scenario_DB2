from __future__ import annotations

from pathlib import Path

from scenario_db.db.models.evidence import Evidence
from scenario_db.db.models.write import WriteBatch

ROOT = Path(__file__).resolve().parents[2]


def _index_names(table) -> set[str]:
    return {index.name for index in table.indexes}


def test_evidence_declares_scenario_variant_index():
    assert "idx_ev_scenario_variant" in _index_names(Evidence.__table__)


def test_write_batches_declares_updated_at_index():
    assert "idx_write_batches_updated_at" in _index_names(WriteBatch.__table__)


def test_alembic_migration_0010_declares_indexes():
    migration = (
        ROOT / "alembic" / "versions" / "0010_evidence_write_batch_indexes.py"
    ).read_text(encoding="utf-8")

    assert "idx_ev_scenario_variant" in migration
    assert "idx_write_batches_updated_at" in migration
