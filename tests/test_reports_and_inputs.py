"""Reports (Markdown, HTML, Rich), datetime checks and input types."""

import pandas as pd
import pytest

from datadiff_engine import DiffConfig, compare

XSS = '<script>alert("x")</script>'


@pytest.fixture
def hostile():
    old = pd.DataFrame({XSS: [1, 2], "c": ["a", "b"]})
    new = pd.DataFrame({"c": ["a", XSS], "<img src=x onerror=alert(1)>": [1, 2]})
    return compare(old, new)


def test_html_escapes_data_values(hostile):
    page = hostile.to_html(title=XSS)

    assert "<script>" not in page
    assert "<img" not in page
    assert "&lt;script&gt;" in page
    assert "Content-Security-Policy" in page


def test_markdown_escapes_data_values(hostile):
    text = hostile.to_markdown()

    assert "<script>" not in text
    assert "<img" not in text
    assert text.startswith("# Dataset diff")


def test_markdown_escapes_table_pipes():
    old = pd.DataFrame({"a|b": [1]})
    text = compare(old, pd.DataFrame({"x": [1]})).to_markdown()

    assert "a\\|b" in text


def test_rich_output(hostile):
    rich = pytest.importorskip("rich")
    from io import StringIO

    from datadiff_engine.report import print_rich

    buffer = StringIO()
    print_rich(hostile, console=rich.console.Console(file=buffer, width=120))

    assert "CRITICAL" in buffer.getvalue()


def test_stale_data_detected():
    old = pd.DataFrame({"ts": ["2026-11-01 10:00", "2026-11-02 10:00"]})
    new = pd.DataFrame({"ts": ["2026-11-01 10:00", "2026-11-02 10:00"]})
    fresh = pd.DataFrame({"ts": ["2026-11-02 10:00", "2026-11-03 10:00"]})
    config = DiffConfig(freshness_columns={"ts"})

    stale = [i for i in compare(old, new, config).issues() if i.kind == "stale_data"]
    assert stale and stale[0].severity == "WARNING"
    assert not [
        i for i in compare(old, fresh, config).issues() if i.kind == "stale_data"
    ]


def test_freshness_with_native_and_timezone_datetimes():
    old = pd.DataFrame({"ts": pd.to_datetime(["2026-11-01"]).tz_localize("UTC")})
    new = pd.DataFrame({"ts": pd.to_datetime(["2026-11-02"]).tz_localize("UTC")})

    diff = compare(old, new, DiffConfig(freshness_columns=["ts"]))

    assert diff.column("ts").new_datetime_stats.max == pd.Timestamp("2026-11-02")
    assert not diff.issues()


def test_unknown_freshness_column_raises():
    df = pd.DataFrame({"a": [1]})
    with pytest.raises(ValueError, match="Freshness"):
        compare(df, df, DiffConfig(freshness_columns={"ts"}))


def test_datetime_profile_in_report():
    old = pd.DataFrame({"d": ["2026-01-01", "2026-01-05"]})
    new = pd.DataFrame({"d": ["2026-01-01", "2026-01-09", None]})

    diff = compare(old, new)
    report = diff.to_dict()["columns"]["d"]

    assert report["new_datetime_stats"]["max"] == "2026-01-09T00:00:00"
    assert "Date range" in diff.to_text()


def test_polars_inputs():
    pl = pytest.importorskip("polars")
    pytest.importorskip("pyarrow")
    old = pl.DataFrame({"a": [1, 2, 3]})
    new = pl.DataFrame({"a": [1, 2, None]})

    assert compare(old, new.lazy()).column("a").null_rate_new == pytest.approx(1 / 3)


def test_duckdb_and_arrow_inputs():
    duckdb = pytest.importorskip("duckdb")
    pa = pytest.importorskip("pyarrow")
    old = duckdb.sql("SELECT range AS a FROM range(5)")
    new = pa.table({"a": [0, 1, 2, 3, 4, 5]})

    assert compare(old, new).rows_new == 6


def test_unsupported_input_type():
    with pytest.raises(TypeError, match="old must be"):
        compare([1, 2], pd.DataFrame())


def test_config_accepts_lists_and_round_trips():
    config = DiffConfig(ignored_columns=["id"], freshness_columns="ts")

    assert config.ignored_columns == frozenset({"id"})
    assert config.freshness_columns == frozenset({"ts"})
    assert DiffConfig.from_dict(config.to_dict()) == config
    with pytest.raises(ValueError, match="Unknown"):
        DiffConfig.from_dict({"psi_warnin": 0.1})


@pytest.mark.parametrize("bad", [
    {"warning_null_rate": -1},
    {"critical_null_rate": 0.01},
    {"drift_threshold_pct": 0},
    {"warning_row_change_pct": -1},
    {"critical_row_change_pct": 1},
    {"max_categories_for_new_value_check": -1},
    {"new_value_min_share": 2},
    {"psi_bins": 1},
    {"psi_warning": 0},
    {"warning_changed_rows_pct": -1},
    {"critical_changed_rows_pct": 0.5},
    {"numeric_abs_tolerance": -1},
    {"sample_size": -1},
    {"max_segments": 0},
    {"min_segment_rows": 0},
    {"min_segment_share": 2},
    {"segment_share_shift": 0},
])
def test_invalid_config_values(bad):
    with pytest.raises(ValueError):
        DiffConfig(**bad)


def test_full_reports_with_key_and_segments():
    import numpy as np

    rng = np.random.default_rng(3)
    n = 600
    old = pd.DataFrame({
        "id": range(n),
        "country": rng.choice(["IN", "US"], n),
        "fare": rng.normal(100, 10, n),
        "day": ["2026-01-01"] * n,
    })
    new = old.copy()
    new["fare"] = new["fare"] * 1.4
    new = new[new["id"] > 5]
    diff = compare(old, new, key="id", segment_by="country")

    text = diff.to_text()
    assert "ROW DIFF (key: id)" in text
    assert "SEGMENTS (by: country)" in text
    assert "Distribution: PSI" in text
    markdown = diff.to_markdown()
    assert "## Row diff" in markdown and "## Segments" in markdown
    assert "## Column changes" in markdown
    page = diff.to_html()
    assert "Row diff" in page and "Segments" in page
    assert str(diff) == text
    issue = next(i for i in diff.issues() if i.kind == "distribution_drift")
    assert issue.to_dict()["details"]["method"] == "numeric"
