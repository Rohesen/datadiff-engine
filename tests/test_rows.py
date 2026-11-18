"""Key-based row diff."""

import json

import numpy as np
import pandas as pd
import pytest

from datadiff_engine import DiffConfig, compare


def by_kind(diff):
    return {issue.kind: issue for issue in diff.issues()}


def test_added_removed_and_changed_rows():
    old = pd.DataFrame({"id": [1, 2, 3, 4], "fare": [10.0, 20.0, 30.0, 40.0],
                        "status": ["ok", "ok", "ok", "ok"]})
    new = pd.DataFrame({"id": [2, 3, 4, 5], "fare": [20.0, 35.0, 40.0, 50.0],
                        "status": ["ok", "ok", "cancelled", "ok"]})

    rd = compare(old, new, key="id").row_diff

    assert rd.rows_added == 1
    assert rd.rows_removed == 1
    assert rd.rows_changed == 2
    assert rd.rows_unchanged == 1
    assert rd.changed_by_column == {"fare": 1, "status": 1}
    assert rd.sample_added == [{"id": 5, "fare": 50.0, "status": "ok"}]
    assert rd.sample_removed == [{"id": 1, "fare": 10.0, "status": "ok"}]
    changes = {
        sample["key"]["id"]: sample["changes"] for sample in rd.sample_changed
    }
    assert changes == {3: {"fare": [30.0, 35.0]},
                       4: {"status": ["ok", "cancelled"]}}


def test_identical_data_with_key_has_no_issues():
    df = pd.DataFrame({"id": [1, 2, 3], "v": ["a", None, "c"]})

    diff = compare(df, df.copy(), key="id")

    assert diff.issues() == []
    assert diff.row_diff.rows_unchanged == 3


def test_missing_values_compare_equal_and_null_changes_count():
    old = pd.DataFrame({"id": [1, 2, 3], "v": [1.0, np.nan, 3.0]})
    new = pd.DataFrame({"id": [1, 2, 3], "v": [1.0, np.nan, np.nan]})

    rd = compare(old, new, key="id").row_diff

    assert rd.rows_changed == 1
    assert rd.sample_changed[0]["changes"] == {"v": [3.0, None]}


def test_composite_key_and_row_order_does_not_matter():
    old = pd.DataFrame({"flight": ["AI1", "AI1", "6E2"],
                        "date": ["d1", "d2", "d1"], "pax": [100, 120, 90]})
    new = old.iloc[::-1].copy()
    new.loc[new["flight"] == "6E2", "pax"] = 95

    rd = compare(old, new, key=["flight", "date"]).row_diff

    assert rd.rows_changed == 1
    assert rd.sample_changed[0]["key"] == {"flight": "6E2", "date": "d1"}


def test_numeric_tolerance():
    old = pd.DataFrame({"id": [1, 2], "amount": [100.0, 200.0]})
    new = pd.DataFrame({"id": [1, 2], "amount": [100.001, 210.0]})

    strict = compare(old, new, key="id").row_diff
    tolerant = compare(
        old, new, DiffConfig(numeric_abs_tolerance=0.01), key="id"
    ).row_diff
    relative = compare(
        old, new, DiffConfig(numeric_rel_tolerance=0.1), key="id"
    ).row_diff

    assert strict.rows_changed == 2
    assert tolerant.rows_changed == 1
    assert relative.rows_changed == 0


def test_key_with_different_dtypes_still_matches():
    old = pd.DataFrame({"id": [1, 2, 3], "v": ["a", "b", "c"]})
    new = pd.DataFrame({"id": [1.0, 2.0, np.nan], "v": ["a", "b", "c"]})

    rd = compare(old, new, key="id").row_diff

    assert rd.rows_unchanged == 2
    assert rd.null_keys_new == 1
    assert "null_keys" in by_kind(compare(old, new, key="id"))


def test_duplicate_keys_are_critical_in_new_data():
    old = pd.DataFrame({"id": [1, 2, 3], "v": [1, 2, 3]})
    new = pd.DataFrame({"id": [1, 2, 2, 3], "v": [1, 2, 2, 3]})

    diff = compare(old, new, key="id")
    issue = by_kind(diff)["duplicate_keys"]

    assert issue.severity == "CRITICAL"
    assert diff.row_diff.duplicate_keys_new == 1


def test_change_severity_follows_thresholds():
    old = pd.DataFrame({"id": range(100), "v": [0] * 100})
    new = old.copy()
    new.loc[:4, "v"] = 1  # 5 rows changed → 5%

    issue = by_kind(compare(old, new, key="id"))["rows_changed"]
    assert issue.severity == "WARNING"

    relaxed = DiffConfig(warning_changed_rows_pct=10, critical_changed_rows_pct=20)
    issue = by_kind(compare(old, new, relaxed, key="id"))["rows_changed"]
    assert issue.severity == "INFO"


def test_missing_key_column_raises():
    df = pd.DataFrame({"id": [1]})
    with pytest.raises(ValueError, match="Key column"):
        compare(df, df, key="booking_id")


def test_sample_size_limits_samples():
    old = pd.DataFrame({"id": range(50), "v": [0] * 50})
    new = pd.DataFrame({"id": range(50), "v": [1] * 50})

    rd = compare(old, new, DiffConfig(sample_size=2), key="id").row_diff

    assert len(rd.sample_changed) == 2


def test_row_diff_is_strict_json_with_timestamps():
    old = pd.DataFrame({"id": [1, 2], "ts": pd.to_datetime(["2026-01-01", "2026-01-02"])})
    new = pd.DataFrame({"id": [1, 3], "ts": pd.to_datetime(["2026-01-05", "2026-01-03"])})

    report = compare(old, new, key="id").to_dict()

    text = json.dumps(report, allow_nan=False)
    assert "2026-01-05T00:00:00" in text


def test_awkward_columns_do_not_break_the_diff():
    old = pd.DataFrame({
        0: [1, 2, 3],
        "s": pd.array(["a", None, "c"], dtype="string"),
        "tags": [np.array([1, 2]), np.array([3]), np.array([])],
        "meta": [{"k": 1}, {"k": 2}, None],
        "inf": [1.0, np.inf, -np.inf],
    })
    new = old.copy()
    new["tags"] = [np.array([1, 2]), np.array([4]), np.array([])]
    new["s"] = pd.array(["a", "b", "c"], dtype="string")

    diff = compare(old, new, key=0)

    assert diff.row_diff.changed_by_column == {"s": 1, "tags": 1}
    json.dumps(diff.to_dict(), allow_nan=False)
    assert "ROW DIFF (key: 0)" in diff.to_text()
