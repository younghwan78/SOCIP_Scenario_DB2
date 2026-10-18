"""Risk tracking validates the final closed state before mutating persisted fields."""
from datetime import date
from unittest.mock import MagicMock

import pytest

from scenario_db.api.services.review_risks import update_risk
from scenario_db.db.models.exploration import ReviewRisk
from scenario_db.exceptions import UnprocessableError


def stored_risk(**overrides):
    row = ReviewRisk(id='risk', project_ref='project', seq=1, risk_key='fps', rule='fps', severity='high', category='SW',
                     title='FPS', detail='', status='open', history=[], affected=[], auto_state='active',
                     **overrides)
    db = MagicMock()
    db.query.return_value.filter_by.return_value.populate_existing.return_value.with_for_update.return_value.one_or_none.return_value = row
    return db, row


@pytest.mark.parametrize('closed', [False, True])
def test_closure_evidence_cannot_be_cleared_when_closing_or_already_closed(closed):
    db, row = stored_risk(closure_evidence='old capture')
    if closed:
        row.status = 'closed'
    with pytest.raises(UnprocessableError, match='closure evidence'):
        update_risk(db, 'risk', status=None if closed else 'closed', closure_evidence='')
    assert row.closure_evidence == 'old capture'
    db.commit.assert_not_called()


@pytest.mark.parametrize('due', ['2026-02-30', '2026-13-01'])
def test_invalid_calendar_date_is_rejected_before_any_updates(due):
    db, row = stored_risk(owner='old')
    with pytest.raises(UnprocessableError, match='invalid due_date'):
        update_risk(db, 'risk', owner='new', due_date=due)
    assert row.owner == 'old' and row.history == []
    db.commit.assert_not_called()


def test_valid_close_records_date_evidence_and_history():
    db, row = stored_risk()
    result = update_risk(db, 'risk', status='closed', due_date='2026-11-05', closure_evidence=' capture OK ', user='reviewer')
    assert row.due_date == date(2026, 11, 5) and result['closure_evidence'] == 'capture OK'
    assert result['status'] == 'closed'
    assert [h['field'] for h in row.history] == ['status', 'closure_evidence', 'due_date']
