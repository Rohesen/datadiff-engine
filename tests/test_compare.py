import pandas as pd
import pytest

from datadiff_engine import DiffConfig, compare


def test_compare_detects_basic_changes():
    old = pd.DataFrame({
        "id": [1, 2, 3],
        "name": ["a", "b", "c"],
    })

    new = pd.DataFrame({
        "id": [1, 2, 3, 4],
        "name": ["a", None, "c", "d"],
        "country": ["IN", "IN", "US", "IN"],
    })

    diff = compare(old, new)

    assert diff.rows_old == 3
    assert diff.rows_new == 4

    assert diff.row_change == 1
    assert diff.row_change_pct == 33.33333333333333

    assert diff.added_columns == ["country"]
    assert diff.removed_columns == []

    assert "name" in diff.null_rate_changes
    assert "name" not in diff.unique_count_changes


def test_compare_handles_empty_old_dataset():
    old = pd.DataFrame({
        "id": [],
    })

    new = pd.DataFrame({
        "id": [1, 2, 3],
    })

    diff = compare(old, new)

    assert diff.rows_old == 0
    assert diff.rows_new == 3
    assert diff.row_change == 3
    assert diff.row_change_pct == 0.0

def test_column_detects_critical_null_rate_change():
    old = pd.DataFrame({
        "amount": [100, 200, 300, 400],
    })

    new = pd.DataFrame({
        "amount": [100, None, None, 400],
    })

    diff = compare(old, new)

    amount = diff.column("amount")

    assert amount.null_rate_old == 0.0
    assert amount.null_rate_new == 0.5
    assert amount.severity == "CRITICAL"

def test_compare_supports_custom_severity_thresholds():
    old = pd.DataFrame({
        "amount": [100, 200, 300, 400],
    })

    new = pd.DataFrame({
        "amount": [100, None, None, 400],
    })

    config = DiffConfig(
        warning_null_rate=0.10,
        critical_null_rate=0.60,
    )

    diff = compare(old, new, config=config)

    amount = diff.column("amount")

    assert amount.null_rate_change == 0.50
    assert amount.severity == "WARNING"

def test_diff_can_be_converted_to_dict():
    old = pd.DataFrame({
        "id": [1, 2, 3],
        "amount": [100, 200, 300],
    })

    new = pd.DataFrame({
        "id": [1, 2, 3, 4],
        "amount": [100, None, 300, 400],
        "country": ["IN", "IN", "US", "IN"],
    })

    diff = compare(old, new)

    result = diff.to_dict()

    assert result["rows"]["old"] == 3
    assert result["rows"]["new"] == 4
    assert result["rows"]["change"] == 1

    assert result["schema"]["added"] == ["country"]

    assert result["columns"]["amount"]["null_rate_old"] == 0.0
    assert result["columns"]["amount"]["null_rate_new"] == 0.25

def test_compare_calculates_numeric_statistics():
    old = pd.DataFrame({
        "amount": [100, 200, 300],
    })

    new = pd.DataFrame({
        "amount": [100, None, 300, 400],
    })

    diff = compare(old, new)

    amount = diff.column("amount")

    assert amount.old_stats is not None
    assert amount.new_stats is not None

    assert amount.old_stats.mean == pytest.approx(200.0)
    assert amount.new_stats.mean == pytest.approx(266.6667)

    assert amount.old_stats.median == pytest.approx(200.0)
    assert amount.new_stats.median == pytest.approx(300.0)

    assert amount.old_stats.min == pytest.approx(100.0)
    assert amount.new_stats.min == pytest.approx(100.0)

    assert amount.old_stats.max == pytest.approx(300.0)
    assert amount.new_stats.max == pytest.approx(400.0)

    assert amount.old_stats.p95 == pytest.approx(290.0)
    assert amount.new_stats.p95 == pytest.approx(390.0)


def test_compare_does_not_calculate_numeric_statistics_for_text():
    old = pd.DataFrame({
        "country": ["IN", "US", "IN"],
    })

    new = pd.DataFrame({
        "country": ["IN", "US", "BD"],
    })

    diff = compare(old, new)

    country = diff.column("country")

    assert country.old_stats is None
    assert country.new_stats is None

def test_numeric_statistics_are_in_dict_report():
    old = pd.DataFrame({
        "amount": [100, 200, 300],
    })

    new = pd.DataFrame({
        "amount": [100, None, 300, 400],
    })

    diff = compare(old, new)

    result = diff.to_dict()

    old_stats = result["columns"]["amount"]["old_stats"]
    new_stats = result["columns"]["amount"]["new_stats"]

    assert old_stats["count"] == 3
    assert old_stats["mean"] == pytest.approx(200.0)
    assert old_stats["median"] == pytest.approx(200.0)
    assert old_stats["min"] == pytest.approx(100.0)
    assert old_stats["max"] == pytest.approx(300.0)
    assert old_stats["p95"] == pytest.approx(290.0)

    assert new_stats["count"] == 3
    assert new_stats["mean"] == pytest.approx(266.6667)
    assert new_stats["median"] == pytest.approx(300.0)

def test_text_report_contains_column_details():
    old = pd.DataFrame({
        "amount": [100, 200, 300],
    })

    new = pd.DataFrame({
        "amount": [100, 200, None, 500],
    })

    diff = compare(old, new)

    text = diff.to_text()

    assert "COLUMN CHANGES" in text
    assert "amount" in text
    assert "Null rate: 0.00% → 25.00%" in text
    assert "Severity:" in text
    assert "CRITICAL" in text
    assert "Mean:    200.00 → 266.67" in text

def test_small_null_rate_change_is_info():
    old = pd.DataFrame({
        "amount": list(range(10)),
    })

    new = pd.DataFrame({
        "amount": [0, 1, 2, 3, 4, 5, 6, 7, 8, None],
    })

    config = DiffConfig(
        warning_null_rate=0.20,
        critical_null_rate=0.50,
    )

    diff = compare(old, new, config=config)

    amount = diff.column("amount")

    assert amount.null_rate_change == 0.10  
    assert amount.severity == "INFO"

def test_numeric_column_detects_distribution_change():
    old = pd.DataFrame({
        "amount": [100, 110, 120, 130, 140],
    })

    new = pd.DataFrame({
        "amount": [200, 220, 240, 260, 280],
    })

    diff = compare(old, new)

    amount = diff.column("amount")

    assert amount.drift is not None

    assert amount.drift.mean_change_pct == pytest.approx(100.0)
    assert amount.drift.median_change_pct == pytest.approx(100.0)
    assert amount.drift.has_drift is True

def test_numeric_drift_is_in_dict_report():
    old = pd.DataFrame({
        "amount": [100, 110, 120, 130, 140],
    })

    new = pd.DataFrame({
        "amount": [200, 220, 240, 260, 280],
    })

    diff = compare(old, new)

    result = diff.to_dict()

    drift = result["columns"]["amount"]["drift"]

    assert drift["mean_change_pct"] == pytest.approx(100.0)
    assert drift["median_change_pct"] == pytest.approx(100.0)
    assert drift["has_drift"] is True

def test_ignored_column_does_not_get_numeric_drift():
    old = pd.DataFrame({
        "customer_id": [1, 2, 3],
        "amount": [100, 200, 300],
    })

    new = pd.DataFrame({
        "customer_id": [1, 2, 3, 4],
        "amount": [100, 200, 300, 400],
    })

    config = DiffConfig(
        ignored_columns={"customer_id"},
    )

    diff = compare(old, new, config=config)

    assert diff.column("customer_id").drift is None
    assert diff.column("amount").drift is not None

def test_compare_calculates_categorical_statistics():
    old = pd.DataFrame({
        "country": ["IN", "IN", "US", "IN"],
    })

    new = pd.DataFrame({
        "country": ["IN", "US", "US", "BD", "IN"],
    })

    diff = compare(old, new)

    country = diff.column("country")

    assert country.old_category_stats is not None
    assert country.new_category_stats is not None

    assert country.old_category_stats.count == 4
    assert country.new_category_stats.count == 5

    assert country.old_category_stats.unique_count == 2
    assert country.new_category_stats.unique_count == 3

    assert country.old_category_stats.top_values["IN"] == 3
    assert country.new_category_stats.top_values["US"] == 2