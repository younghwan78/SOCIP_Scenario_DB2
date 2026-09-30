from __future__ import annotations

from scenario_db.api.services.failures import variant_failure


def _raise(exc: BaseException) -> BaseException:
    try:
        raise exc
    except BaseException as caught:  # noqa: BLE001
        return caught


def test_failure_row_carries_stage_type_location_category_and_hint():
    exc = _raise(ValueError("eis: included hardware needs positive PPC and a time budget"))
    row = variant_failure(exc, variant_id="cam-rec-r1-uhd120", scenario_id="uc-x", stage="load")
    assert row["scenario_id"] == "uc-x" and row["variant_id"] == "cam-rec-r1-uhd120"
    assert (row["stage"], row["error_type"], row["category"]) == ("load", "ValueError", "sw_stage_budget")
    assert "includes_hw_nodes" in row["hint"]
    assert row["location"] and "test_variant_failures.py" in row["location"]


def test_sw_timing_and_reference_categories_and_full_message():
    assert variant_failure(_raise(ValueError("timing must satisfy min_ms <= mean_ms <= max_ms")),
                           variant_id="v", stage="timing_budget")["category"] == "sw_timing"
    long = "not found: " + "x" * 1000
    row = variant_failure(_raise(LookupError(long)), variant_id="v", stage="load")
    assert row["category"] == "reference" and row["error"] == long and "scenario_id" not in row


def test_unexpected_exceptions_are_internal():
    row = variant_failure(_raise(ZeroDivisionError("float division by zero")), variant_id="v", stage="explore")
    assert row["category"] == "internal" and row["error_type"] == "ZeroDivisionError"
