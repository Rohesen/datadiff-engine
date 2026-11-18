"""Segment (subgroup) analysis: changes hidden in the overall numbers."""

import numpy as np
import pandas as pd
import pytest

from datadiff_engine import DiffConfig, compare


@pytest.fixture
def bookings():
    rng = np.random.default_rng(7)
    n = 4000
    return pd.DataFrame({
        "country": rng.choice(["IN", "US", "UK", "AE"], n, p=[0.5, 0.3, 0.15, 0.05]),
        "fare": rng.normal(100, 10, n),
        "channel": rng.choice(["web", "app"], n),
    })


def issues_of(diff, kind):
    return [issue for issue in diff.issues() if issue.kind == kind]


def test_null_spike_in_small_segment_is_hidden_overall(bookings):
    new = bookings.copy()
    new.loc[new["country"] == "AE", "channel"] = None  # ~5% of rows

    plain = compare(bookings, new, DiffConfig(warning_null_rate=0.10))
    segmented = compare(
        bookings, new, DiffConfig(warning_null_rate=0.10), segment_by="country"
    )

    assert not issues_of(plain, "null_rate_increase")
    found = issues_of(segmented, "segment_null_rate_increase")
    assert [(i.column, i.segment, i.severity) for i in found] == [
        ("channel", "country=AE", "CRITICAL")
    ]
    assert "hidden" in found[0].message


def test_opposite_shifts_cancel_out_overall(bookings):
    # UK fares up 30%, US fares down ~15%: the overall mean barely moves.
    new = bookings.copy()
    new.loc[new["country"] == "UK", "fare"] *= 1.3
    new.loc[new["country"] == "US", "fare"] *= 0.85

    diff = compare(
        bookings, new, DiffConfig(statistical_tests=False), segment_by="country"
    )

    assert not issues_of(diff, "numeric_drift")
    drifted = {i.segment for i in issues_of(diff, "segment_drift")}
    assert drifted == {"country=UK"}  # US moved 15%, below the 20% threshold


def test_concentrated_change_is_reported_with_overall_context(bookings):
    new = bookings.copy()
    new.loc[new["country"] == "UK", "fare"] *= 2

    diff = compare(bookings, new, segment_by="country")

    found = issues_of(diff, "segment_drift")
    assert [i.segment for i in found] == ["country=UK"]
    assert "concentrated" in found[0].message


def test_uniform_change_is_not_repeated_per_segment(bookings):
    new = bookings.copy()
    new["fare"] *= 1.5

    diff = compare(bookings, new, segment_by="country")

    assert issues_of(diff, "numeric_drift")
    assert not issues_of(diff, "segment_drift")


def test_missing_new_and_shifted_segments(bookings):
    new = bookings[bookings["country"] != "AE"].copy()
    extra = new.head(400).assign(country="SG")
    new = pd.concat([new, extra])

    diff = compare(bookings, new, segment_by="country")

    assert [i.segment for i in issues_of(diff, "segment_missing")] == ["country=AE"]
    assert [i.segment for i in issues_of(diff, "segment_new")] == ["country=SG"]


def test_share_shift(bookings):
    new = pd.concat([bookings, bookings[bookings["country"] == "US"]])

    diff = compare(bookings, new, segment_by="country")

    shifted = {i.segment for i in issues_of(diff, "segment_share_shift")}
    assert "country=US" in shifted


def test_multiple_segment_columns_and_null_segments(bookings):
    old = bookings.copy()
    old.loc[:9, "channel"] = None
    diff = compare(old, old.copy(), segment_by=["country", "channel"])

    labels = {s.label for s in diff.segment_diff.segments}
    assert "country=IN, channel=web" in labels
    assert any("channel=<null>" in label for label in labels)
    assert diff.issues() == []


def test_max_segments_truncates(bookings):
    diff = compare(bookings, bookings, DiffConfig(max_segments=2), segment_by="country")

    assert diff.segment_diff.truncated
    assert len(diff.segment_diff.segments) == 2


def test_unknown_segment_column_raises(bookings):
    with pytest.raises(ValueError, match="Segment column"):
        compare(bookings, bookings, segment_by="region")
