from __future__ import annotations

from sqlalchemy import create_mock_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from scenario_db.api.routers.evidence import _summary_query
from scenario_db.api.schemas.evidence import (
    EVIDENCE_HEAVY_FIELDS,
    EvidenceResponse,
    EvidenceSummaryResponse,
)
from scenario_db.db.models.evidence import Evidence


def test_evidence_summary_query_defers_payloads_and_computes_metadata_in_sql():
    engine = create_mock_engine("postgresql://", lambda *args, **kwargs: None)
    with Session(engine) as db:
        statement = _summary_query(db.query(Evidence)).statement
        compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    # The first part projects the ORM entity; payloads can only occur inside
    # the SQL metadata expressions after it, never as returned JSONB values.
    entity_projection = sql.split("jsonb_build_object", 1)[0]
    for name in EVIDENCE_HEAVY_FIELDS:
        assert f"evidence.{name}" not in entity_projection
        assert f"pg_column_size(evidence.{name})" in sql
        assert f"evidence.{name} IS NOT NULL" in sql
        assert f"jsonb_typeof(evidence.{name})" in sql
    assert "evidence.timeline_events" in entity_projection
    assert "evidence.profiling_metadata" in entity_projection


def test_evidence_summary_schema_excludes_only_deferred_fields():
    full = set(EvidenceResponse.model_fields)
    summary = set(EvidenceSummaryResponse.model_fields)
    assert full - summary == set(EVIDENCE_HEAVY_FIELDS)
    assert summary - full == {"heavy"}
    assert {"kpi", "aggregation", "execution_context", "provenance", "run_info",
            "power_breakdown", "vdd_power"} <= summary
