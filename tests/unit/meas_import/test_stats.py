from __future__ import annotations

import math

import pytest

from scenario_db.meas_import.stats import measured_kpi, percentile


def test_percentile_interpolates():
    values = [10.0, 20.0, 30.0, 40.0]
    assert percentile(values, 0.0) == 10.0
    assert percentile(values, 100.0) == 40.0
    # rank = 0.5 * 3 = 1.5 -> between 20 and 30
    assert percentile(values, 50.0) == 25.0


def test_percentile_single_value():
    assert percentile([42.0], 95.0) == 42.0


def test_percentile_empty_raises():
    with pytest.raises(ValueError):
        percentile([], 50.0)


def test_measured_kpi_shape_and_values():
    values = [100.0, 110.0, 120.0]
    kpi = measured_kpi(values)
    assert kpi["mean"] == 110.0
    assert kpi["n"] == 3
    assert kpi["p95"] == pytest.approx(119.0)
    # Sample stdev (n-1 denominator), the correct estimator for repeated runs.
    assert kpi["std"] == pytest.approx(10.0, abs=1e-3)
    lower, upper = kpi["ci_95"]
    assert lower < kpi["mean"] < upper


def test_measured_kpi_single_sample_has_no_ci():
    kpi = measured_kpi([500.0])
    assert kpi == {"mean": 500.0, "p95": 500.0, "std": 0.0, "n": 1}


def test_default_ci_uses_student_t_and_no_ci_level():
    values = [100.0, 110.0, 120.0]
    kpi = measured_kpi(values)
    # n=3 -> dof=2 -> two-sided t(0.975) = 4.30265; the old z=1.96 constant
    # understated a 3-run CI by ~2.2x.
    half = 4.30265 * 10.0 / math.sqrt(3)
    assert kpi["ci_95"][0] == pytest.approx(110.0 - half, abs=2e-3)
    assert kpi["ci_95"][1] == pytest.approx(110.0 + half, abs=2e-3)
    assert "ci_level" not in kpi          # default level is implicit


def test_t_multiplier_matches_reference_values():
    from scenario_db.meas_import.stats import t_multiplier

    assert t_multiplier(0.95, 2) == pytest.approx(4.30265, abs=1e-4)
    assert t_multiplier(0.95, 1) == pytest.approx(12.7062, abs=1e-3)
    assert t_multiplier(0.99, 4) == pytest.approx(4.60409, abs=1e-4)
    # Large dof converges to the normal z multiplier.
    assert t_multiplier(0.95, 10000) == pytest.approx(1.96, abs=1e-3)


def test_explicit_0_95_matches_default():
    values = [100.0, 110.0, 120.0]
    assert measured_kpi(values, confidence_level=0.95) == measured_kpi(values)


def test_lower_confidence_narrows_interval_and_records_level():
    values = [100.0, 110.0, 120.0]
    wide = measured_kpi(values)                              # 95%
    narrow = measured_kpi(values, confidence_level=0.90)     # 90%
    assert narrow["ci_level"] == 0.90
    assert (narrow["ci_95"][1] - narrow["ci_95"][0]) < (wide["ci_95"][1] - wide["ci_95"][0])


def test_higher_confidence_widens_interval():
    values = [100.0, 110.0, 120.0]
    wide99 = measured_kpi(values, confidence_level=0.99)
    base95 = measured_kpi(values)
    assert wide99["ci_level"] == 0.99
    assert (wide99["ci_95"][1] - wide99["ci_95"][0]) > (base95["ci_95"][1] - base95["ci_95"][0])


def test_invalid_confidence_level_raises():
    with pytest.raises(ValueError, match="confidence_level"):
        measured_kpi([1.0, 2.0, 3.0], confidence_level=1.5)
