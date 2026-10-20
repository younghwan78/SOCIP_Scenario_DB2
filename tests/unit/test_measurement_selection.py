from datetime import UTC, datetime, timedelta, timezone
from itertools import permutations
from types import SimpleNamespace

from scenario_db.comparison.measurement_selection import representative_measurement


def capture(identifier, *, origin="physical_capture", total=0, when=None):
    return SimpleNamespace(id=identifier, kpi={"total_power_mw": {"mean": total}},
                           provenance={"data_origin": origin}, measured_at=when)


def test_choice_is_independent_of_input_order_including_timestamp_ties():
    utc = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        capture("z", when=utc),
        capture("a", when=datetime(2026, 1, 1, 9, tzinfo=timezone(timedelta(hours=9)))),
        capture("old", when=datetime(2025, 1, 1)),
    ]
    for ordered in permutations(rows):
        assert representative_measurement(ordered).id == "a"


def test_comparable_zero_beats_missing_total_and_origins_remain_distinct():
    physical_without_total = capture("physical", total=None, when=datetime(2026, 1, 1))
    unknown = capture("unknown", origin="unknown")
    synthetic = capture("synthetic", origin="synthetic", when=datetime(2026, 1, 1))
    assert representative_measurement([physical_without_total, synthetic]).id == "synthetic"
    assert representative_measurement([physical_without_total, synthetic, unknown]).id == "unknown"
    physical = capture("physical-zero")
    assert representative_measurement([physical, unknown, synthetic]).id == "physical-zero"


def test_missing_timestamps_use_id_order_and_empty_candidates_are_unassessed():
    assert representative_measurement([capture("z"), capture("a")]).id == "a"
    assert representative_measurement([]) is None
