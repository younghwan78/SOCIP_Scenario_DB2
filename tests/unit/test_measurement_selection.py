from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

from scenario_db.comparison.measurement_selection import representative_measurement


def capture(identifier, *, origin="physical_capture", total=0, when=None):
    return SimpleNamespace(id=identifier, kpi={"total_power_mw": {"mean": total}},
                           provenance={"data_origin": origin}, measured_at=when)


def test_newest_wins_and_equal_instants_keep_database_order():
    utc = datetime(2026, 1, 1, tzinfo=UTC)
    same_instant = datetime(2026, 1, 1, 9, tzinfo=timezone(timedelta(hours=9)))
    old = capture("old", when=datetime(2025, 1, 1))
    # callers pass rows ordered measured_at DESC NULLS LAST, id (database collation)
    assert representative_measurement([capture("z", when=utc), capture("a", when=same_instant), old]).id == "z"
    assert representative_measurement([capture("a", when=same_instant), capture("z", when=utc), old]).id == "a"
    assert representative_measurement([old, capture("n", when=utc)]).id == "n"


def test_comparable_zero_beats_missing_total_and_origins_remain_distinct():
    physical_without_total = capture("physical", total=None, when=datetime(2026, 1, 1))
    unknown = capture("unknown", origin="unknown")
    synthetic = capture("synthetic", origin="synthetic", when=datetime(2026, 1, 1))
    assert representative_measurement([physical_without_total, synthetic]).id == "synthetic"
    assert representative_measurement([physical_without_total, synthetic, unknown]).id == "unknown"
    physical = capture("physical-zero")
    assert representative_measurement([physical, unknown, synthetic]).id == "physical-zero"


def test_missing_timestamps_keep_input_order_and_empty_candidates_are_unassessed():
    assert representative_measurement([capture("z"), capture("a")]).id == "z"
    assert representative_measurement([]) is None


def test_total_rule_is_caller_owned():
    """Report counts any non-None total; calibration counts numeric totals only (pre-refactor rules)."""
    text_total = capture("text", total="n/a", when=datetime(2026, 1, 1, tzinfo=UTC))
    numeric = capture("numeric", total=10, when=datetime(2025, 1, 1, tzinfo=UTC))
    assert representative_measurement([text_total, numeric]).id == "text"

    def numeric_only(m):
        t = (m.kpi or {}).get("total_power_mw")
        v = t.get("mean") if isinstance(t, dict) else t
        return isinstance(v, (int, float))

    assert representative_measurement([text_total, numeric], has_total=numeric_only).id == "numeric"
