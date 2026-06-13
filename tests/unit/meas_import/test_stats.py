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
    assert kpi["std"] == pytest.approx(math.sqrt(200.0 / 3), abs=1e-3)
    lower, upper = kpi["ci_95"]
    assert lower < kpi["mean"] < upper


def test_measured_kpi_single_sample_has_no_ci():
    kpi = measured_kpi([500.0])
    assert kpi == {"mean": 500.0, "p95": 500.0, "std": 0.0, "n": 1}
