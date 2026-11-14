"""S-10: the revision log matches ENGINE_REV, and an old engine gets the changes since it."""

from scenario_db.sim.arch_exploration import ENGINE_REV
from scenario_db.sim.engine_revisions import ENGINE_REVISIONS, changes_since, rev_number


def test_the_log_ends_at_the_current_revision_and_is_ordered():
    revs = [r["rev"] for r in ENGINE_REVISIONS]
    assert revs == sorted(revs) and len(set(revs)) == len(revs)
    assert revs[-1] == rev_number(ENGINE_REV)
    assert all(r["change"] and r["moves"] for r in ENGINE_REVISIONS)


def test_changes_since_an_older_engine():
    assert [r["rev"] for r in changes_since("arch-exploration/13", "arch-exploration/15")] == [14, 15]
    assert changes_since(ENGINE_REV, ENGINE_REV) == []
    assert [r["rev"] for r in changes_since("legacy", "arch-exploration/15")][-1] == 15  # unparsable: all known
    assert rev_number("arch-exploration/9") == 9 and rev_number(None) is None
