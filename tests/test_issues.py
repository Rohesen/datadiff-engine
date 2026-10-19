"""Tests for the issues list, overall severity, JSON safety and CLI gating."""

import json

import pandas as pd
import pytest

from datadiff_engine import DiffConfig, Issue, compare
from datadiff_engine.cli import EXIT_ERROR, EXIT_OK, EXIT_THRESHOLD, main


def kinds(diff):
    return {(issue.kind, issue.column) for issue in diff.issues()}


def test_identical_datasets_have_no_issues():
    df = pd.DataFrame({"amount": [1.0, 2.0, 3.0], "city": ["a", "b", "c"]})

    diff = compare(df, df.copy())

    assert diff.issues() == []
    assert diff.overall_severity == "INFO"


def test_removed_column_is_critical():
    old = pd.DataFrame({"id": [1, 2], "fare": [10.0, 20.0]})
    new = pd.DataFrame({"id": [1, 2]})

    diff = compare(old, new)

    assert ("column_removed", "fare") in kinds(diff)
    assert diff.overall_severity == "CRITICAL"


def test_added_column_is_info():
    old = pd.DataFrame({"id": [1, 2]})
    new = pd.DataFrame({"id": [1, 2], "channel": ["web", "app"]})

    diff = compare(old, new)

    added = [i for i in diff.issues() if i.kind == "column_added"]
    assert added == [
        Issue(
            kind="column_added",
            severity="INFO",
            column="channel",
            message="Column 'channel' was added.",
        )
    ]
    assert diff.overall_severity == "INFO"


def test_type_change_is_warning():
    old = pd.DataFrame({"fare": [10, 20, 30]})
    new = pd.DataFrame({"fare": ["10", "20", "30"]})

    diff = compare(old, new)

    assert ("type_changed", "fare") in kinds(diff)
    assert diff.overall_severity == "WARNING"


def test_null_rate_issue_matches_column_severity():
    old = pd.DataFrame({"email": ["a", "b", "c", "d"]})
    new = pd.DataFrame({"email": ["a", None, None, "d"]})

    diff = compare(old, new)

    issue = next(i for i in diff.issues() if i.kind == "null_rate_increase")
    assert issue.severity == diff.column("email").severity == "CRITICAL"


def test_numeric_drift_uses_configured_threshold():
    old = pd.DataFrame({"fare": [100.0, 110.0, 120.0, 130.0]})
    new = pd.DataFrame({"fare": [115.0, 126.5, 138.0, 149.5]})  # +15%

    default = compare(old, new)
    strict = compare(old, new, DiffConfig(drift_threshold_pct=10.0))

    assert ("numeric_drift", "fare") not in kinds(default)
    assert ("numeric_drift", "fare") in kinds(strict)
    assert strict.column("fare").drift.threshold_pct == 10.0


@pytest.mark.parametrize(
    ("rows_new", "expected"),
    [(95, None), (75, "WARNING"), (40, "CRITICAL")],
)
def test_row_count_change_thresholds(rows_new, expected):
    old = pd.DataFrame({"id": range(100)})
    new = pd.DataFrame({"id": range(rows_new)})

    diff = compare(old, new)

    row_issues = [i for i in diff.issues() if i.kind == "row_count_change"]
    if expected is None:
        assert row_issues == []
    else:
        assert row_issues[0].severity == expected


def test_empty_new_dataset_is_critical():
    old = pd.DataFrame({"id": [1, 2, 3]})
    new = pd.DataFrame({"id": pd.Series([], dtype="int64")})

    diff = compare(old, new)

    assert ("empty_dataset", None) in kinds(diff)
    assert diff.overall_severity == "CRITICAL"


def test_issues_are_sorted_most_severe_first():
    old = pd.DataFrame({"id": [1, 2], "fare": [1.0, 2.0]})
    new = pd.DataFrame({"id": [1, 2], "channel": ["a", "b"]})

    severities = [i.severity for i in compare(old, new).issues()]

    assert severities == sorted(
        severities,
        key=lambda s: {"CRITICAL": 0, "WARNING": 1, "INFO": 2}[s],
    )


def test_drift_from_zero_baseline_is_json_safe():
    old = pd.DataFrame({"refunds": [0.0, 0.0, 0.0]})
    new = pd.DataFrame({"refunds": [5.0, 5.0, 5.0]})

    diff = compare(old, new)
    report = diff.to_dict()

    drift = report["columns"]["refunds"]["drift"]
    assert drift["from_zero_baseline"] is True
    assert drift["mean_change_pct"] is None
    # Must serialise as strict JSON (no Infinity / NaN).
    json.dumps(report, allow_nan=False)


def test_all_null_numeric_column_is_json_safe():
    old = pd.DataFrame({"fare": [1.0, 2.0]})
    new = pd.DataFrame({"fare": [float("nan"), float("nan")]})

    json.dumps(compare(old, new).to_dict(), allow_nan=False)


def test_dict_report_contains_summary():
    old = pd.DataFrame({"id": [1, 2], "fare": [1.0, 2.0]})
    new = pd.DataFrame({"id": [1, 2]})

    summary = compare(old, new).to_dict()["summary"]

    assert summary["overall_severity"] == "CRITICAL"
    assert summary["issue_count"] == 1
    assert summary["issues"][0]["kind"] == "column_removed"


def test_text_report_starts_with_overall_severity():
    old = pd.DataFrame({"id": [1, 2], "fare": [1.0, 2.0]})
    new = pd.DataFrame({"id": [1, 2]})

    text = compare(old, new).to_text()

    assert "OVERALL SEVERITY: CRITICAL" in text
    assert "[CRITICAL] Column 'fare' was removed." in text


def test_config_rejects_inverted_row_thresholds():
    with pytest.raises(ValueError):
        DiffConfig(warning_row_change_pct=60, critical_row_change_pct=50)


def test_config_rejects_non_positive_drift_threshold():
    with pytest.raises(ValueError):
        DiffConfig(drift_threshold_pct=0)


# --- CLI -----------------------------------------------------------------


@pytest.fixture
def csv_pair(tmp_path):
    old = tmp_path / "old.csv"
    new = tmp_path / "new.csv"
    pd.DataFrame({"id": [1, 2, 3], "fare": [1.0, 2.0, 3.0]}).to_csv(
        old, index=False
    )
    pd.DataFrame({"id": [1, 2, 3]}).to_csv(new, index=False)
    return str(old), str(new)


def test_cli_fail_on_critical_returns_threshold_code(csv_pair, capsys):
    assert main([*csv_pair, "--fail-on", "critical"]) == EXIT_THRESHOLD


def test_cli_without_fail_on_returns_ok(csv_pair, capsys):
    assert main(list(csv_pair)) == EXIT_OK


def test_cli_json_is_strict(csv_pair, capsys):
    main([*csv_pair, "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["overall_severity"] == "CRITICAL"


def test_cli_missing_file_returns_error_code(tmp_path, capsys):
    missing = str(tmp_path / "nope.csv")
    assert main([missing, missing]) == EXIT_ERROR


def test_int_to_float_caused_by_nulls_is_info():
    old = pd.DataFrame({"pax": [1, 2, 3, 4]})
    new = pd.DataFrame({"pax": [1, None, 3, 4]})  # pandas makes this float64

    diff = compare(old, new)

    issue = next(i for i in diff.issues() if i.kind == "type_changed")
    assert issue.severity == "INFO"
    assert "missing values" in issue.message


def test_int_to_real_float_values_is_warning():
    old = pd.DataFrame({"fare": [10, 20, 30]})
    new = pd.DataFrame({"fare": [10.5, None, 30.25]})

    diff = compare(old, new)

    issue = next(i for i in diff.issues() if i.kind == "type_changed")
    assert issue.severity == "WARNING"


def test_new_category_value_is_warning():
    old = pd.DataFrame({"currency": ["OMR"] * 10})
    new = pd.DataFrame({"currency": ["USD"] * 10})

    diff = compare(old, new)

    issue = next(i for i in diff.issues() if i.kind == "new_category_values")
    assert issue.severity == "WARNING"
    assert issue.column == "currency"
    assert "'USD' (100%)" in issue.message
    assert diff.new_category_values == {"currency": {"USD": 1.0}}


def test_rare_new_category_value_is_ignored():
    old = pd.DataFrame({"channel": ["web", "app"] * 100})
    new = pd.DataFrame({"channel": ["web", "app"] * 100 + ["kiosk"]})

    diff = compare(old, new, DiffConfig(new_value_min_share=0.01))

    assert ("new_category_values", "channel") not in kinds(diff)


def test_high_cardinality_columns_skip_new_value_check():
    old = pd.DataFrame({"email": [f"a{i}@x.com" for i in range(100)]})
    new = pd.DataFrame({"email": [f"b{i}@x.com" for i in range(100)]})

    diff = compare(old, new)

    assert ("new_category_values", "email") not in kinds(diff)


def test_config_rejects_bad_new_value_share():
    with pytest.raises(ValueError):
        DiffConfig(new_value_min_share=1.5)


def test_new_dates_in_text_date_column_are_not_new_categories():
    old = pd.DataFrame({"booking_date": ["2026-10-01"] * 10})
    new = pd.DataFrame({"booking_date": ["2026-10-02"] * 10})

    diff = compare(old, new)

    assert ("new_category_values", "booking_date") not in kinds(diff)
    assert diff.issues() == []


def test_codes_are_still_checked_for_new_values():
    old = pd.DataFrame({"origin": ["MCT", "SLL", "DXB"] * 5})
    new = pd.DataFrame({"origin": ["MCT", "SLL", "XXX"] * 5})

    diff = compare(old, new)

    assert ("new_category_values", "origin") in kinds(diff)
