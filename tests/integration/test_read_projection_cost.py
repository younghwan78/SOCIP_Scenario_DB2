from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from scenario_db.db.models.evidence import Evidence
from scenario_db.db.repositories.scenario_graph import load_canonical_graph
from scenario_db.query_engine.service import _load_scoped_evidence
from scenario_db.view.service import _project_reference_level1


def test_view_projection_omits_heavy_evidence_without_changing_response(engine):
    with Session(engine) as db:
        pair = db.query(Evidence.scenario_ref, Evidence.variant_ref).first()
        assert pair is not None
        full = load_canonical_graph(db, *pair)
        expected = _project_reference_level1(full).model_dump()
        db.expunge_all()
        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        event.listen(engine, 'before_cursor_execute', capture)
        try:
            lean = load_canonical_graph(db, *pair, include_evidence_details=False)
            assert lean.evidence
            assert 'timeline_events' in inspect(lean.evidence[0]).unloaded
            assert 'calculation_trace' in inspect(lean.evidence[0]).unloaded
            loaded_query_count = len(statements)
            assert _project_reference_level1(lean).model_dump() == expected
            assert len(statements) == loaded_query_count  # no hidden lazy SELECT
        finally:
            event.remove(engine, 'before_cursor_execute', capture)
        evidence_selects = [sql for sql in statements if 'FROM evidence' in sql]
        assert evidence_selects
        assert all('evidence.timeline_events' not in sql and 'evidence.calculation_trace' not in sql for sql in evidence_selects)


def test_query_evidence_keeps_context_and_kpi_but_omits_trace(engine):
    with Session(engine) as db:
        pair = db.query(Evidence.scenario_ref, Evidence.variant_ref).first()
        assert pair is not None
        rows = _load_scoped_evidence(db, {pair[0]}, {pair[1]}, max_rows=20000)
        assert rows
        for row in rows:
            assert 'timeline_events' in inspect(row).unloaded
            assert 'calculation_trace' in inspect(row).unloaded
            assert 'execution_context' not in inspect(row).unloaded
            assert 'resolution_result' not in inspect(row).unloaded
            assert 'kpi' not in inspect(row).unloaded
