"""Statistical drift: PSI, Kolmogorov-Smirnov and Jensen-Shannon."""

import numpy as np
import pandas as pd
import pytest

from datadiff_engine import DiffConfig, compare
from datadiff_engine.drift import (
    categorical_psi,
    jensen_shannon_distance,
    ks_2samp,
    numeric_psi,
)


def kinds(diff):
    return {(issue.kind, issue.column) for issue in diff.issues()}


@pytest.fixture
def rng():
    return np.random.default_rng(42)


# --- the measures themselves ----------------------------------------------


def test_ks_matches_scipy(rng):
    stats = pytest.importorskip("scipy.stats")
    for n, m, shift in [(200, 300, 0.0), (500, 400, 0.3), (60, 80, 1.0)]:
        a = rng.normal(0, 1, n)
        b = rng.normal(shift, 1, m)
        statistic, p_value = ks_2samp(a, b)
        expected = stats.ks_2samp(a, b, method="asymp")
        assert statistic == pytest.approx(expected.statistic, abs=1e-12)
        assert p_value == pytest.approx(expected.pvalue, rel=0.1, abs=1e-6)


def test_ks_handles_ties_and_empty_input():
    statistic, p_value = ks_2samp(np.array([1, 1, 2, 2]), np.array([1, 2, 2, 3]))
    assert 0 <= statistic <= 1
    assert 0 <= p_value <= 1
    assert ks_2samp(np.array([]), np.array([1.0])) == (0.0, 1.0)


def test_js_distance_matches_scipy():
    distance = pytest.importorskip("scipy.spatial.distance")
    old = pd.Series(list("aabbbcc") * 20)
    new = pd.Series(list("abbccdd") * 20)
    p = old.value_counts(normalize=True)
    q = new.value_counts(normalize=True)
    index = p.index.union(q.index)
    expected = distance.jensenshannon(
        p.reindex(index, fill_value=0), q.reindex(index, fill_value=0), base=2
    )
    assert jensen_shannon_distance(old, new) == pytest.approx(expected)


def test_js_distance_bounds():
    same = pd.Series(["a", "b"] * 10)
    assert jensen_shannon_distance(same, same) == pytest.approx(0.0)
    disjoint = jensen_shannon_distance(
        pd.Series(["a"] * 10), pd.Series(["b"] * 10)
    )
    assert disjoint == pytest.approx(1.0)


def test_psi_is_zero_for_identical_data_and_grows_with_shift(rng):
    values = rng.normal(0, 1, 1000)
    assert numeric_psi(values, values) == pytest.approx(0.0, abs=1e-12)

    small = numeric_psi(values, rng.normal(0.1, 1, 1000))
    large = numeric_psi(values, rng.normal(1.0, 1, 1000))
    assert 0 <= small < large
    assert large > 0.25


def test_psi_counts_values_outside_the_old_range(rng):
    old = rng.uniform(0, 1, 1000)
    new = rng.uniform(5, 6, 1000)
    assert numeric_psi(old, new) > 1


def test_psi_on_low_cardinality_numeric_uses_values():
    old = np.array([0, 1] * 100, dtype=float)
    new = np.array([0] * 150 + [1] * 50, dtype=float)
    assert numeric_psi(old, new) == pytest.approx(
        categorical_psi(pd.Series(old), pd.Series(new))
    )


# --- integration in compare() --------------------------------------------


def test_numeric_distribution_drift_is_reported(rng):
    old = pd.DataFrame({"fare": rng.normal(100, 10, 1000)})
    new = pd.DataFrame({"fare": rng.normal(115, 10, 1000)})

    diff = compare(old, new)
    dist = diff.column("fare").distribution

    assert dist is not None and dist.method == "numeric"
    assert dist.ks_p_value < 0.01
    assert ("distribution_drift", "fare") in kinds(diff)


def test_shape_change_with_same_mean_is_caught(rng):
    # Same mean and median, very different spread: the summary-statistic
    # heuristic misses it on the mean but the KS test does not.
    old = pd.DataFrame({"x": rng.normal(100, 1, 2000)})
    new = pd.DataFrame({"x": rng.normal(100, 15, 2000)})

    diff = compare(old, new)

    assert ("distribution_drift", "x") in kinds(diff)


def test_no_drift_on_resampled_data(rng):
    old = pd.DataFrame({"x": rng.normal(0, 1, 2000), "c": rng.choice(list("abc"), 2000)})
    new = pd.DataFrame({"x": rng.normal(0, 1, 2000), "c": rng.choice(list("abc"), 2000)})

    diff = compare(old, new)

    assert ("distribution_drift", "x") not in kinds(diff)
    assert ("distribution_drift", "c") not in kinds(diff)


def test_categorical_distribution_drift(rng):
    old = pd.DataFrame({"channel": rng.choice(["web", "app"], 1000, p=[0.8, 0.2])})
    new = pd.DataFrame({"channel": rng.choice(["web", "app"], 1000, p=[0.3, 0.7])})

    diff = compare(old, new)
    dist = diff.column("channel").distribution

    assert dist.method == "categorical"
    assert dist.js_distance > 0.2
    assert dist.severity == "CRITICAL"


def test_small_samples_skip_statistical_tests():
    old = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    new = pd.DataFrame({"x": [10.0, 20.0, 30.0]})

    assert compare(old, new).column("x").distribution is None


def test_statistical_tests_can_be_disabled(rng):
    old = pd.DataFrame({"x": rng.normal(0, 1, 500)})
    new = pd.DataFrame({"x": rng.normal(3, 1, 500)})

    diff = compare(old, new, DiffConfig(statistical_tests=False))

    assert diff.column("x").distribution is None
    assert ("distribution_drift", "x") not in kinds(diff)


def test_ignored_and_date_columns_are_not_tested(rng):
    old = pd.DataFrame({
        "id": np.arange(500),
        "day": pd.date_range("2026-01-01", periods=500, freq="h").astype(str),
    })
    new = pd.DataFrame({
        "id": np.arange(1000, 1500),
        "day": pd.date_range("2026-03-01", periods=500, freq="h").astype(str),
    })

    diff = compare(old, new, DiffConfig(ignored_columns={"id"}))

    assert diff.column("id").distribution is None
    assert diff.column("day").distribution is None
    assert diff.column("day").new_datetime_stats is not None


def test_high_cardinality_text_is_not_tested():
    old = pd.DataFrame({"email": [f"u{i}@x.com" for i in range(200)]})
    new = pd.DataFrame({"email": [f"v{i}@x.com" for i in range(200)]})

    assert compare(old, new).column("email").distribution is None


def test_drift_results_are_strict_json(rng):
    import json

    old = pd.DataFrame({"x": rng.normal(0, 1, 500), "c": ["a"] * 500})
    new = pd.DataFrame({"x": rng.normal(2, 1, 500), "c": ["b"] * 500})

    json.dumps(compare(old, new).to_dict(), allow_nan=False)


def test_invalid_statistical_config():
    with pytest.raises(ValueError):
        DiffConfig(psi_warning=0.3, psi_critical=0.2)
    with pytest.raises(ValueError):
        DiffConfig(ks_alpha=1.5)
    with pytest.raises(ValueError):
        DiffConfig(min_rows_for_tests=1)
