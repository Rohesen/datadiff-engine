"""Compare two datasets and describe what changed.

This module holds the result types (``ColumnDiff``, ``DatasetDiff``) and
the ``compare`` entry point. Names that lived here before 0.3.0 are
re-exported, so ``from datadiff_engine.compare import X`` keeps working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from . import report as _report
from ._inputs import make_hashable, to_pandas
from ._utils import (
    SEVERITY_ORDER,
    as_list,
    finite_or_none,
    is_categorical,
    is_null_induced_float,
    is_numeric,
    looks_like_dates,
    new_values,
)
from .config import DiffConfig
from .drift import DistributionDrift, NumericDrift
from .issues import Issue
from .rows import RowDiff, compare_rows
from .segments import SegmentDiff, compare_segments
from .stats import CategoryStats, DatetimeStats, NumericStats

# Version of the structure returned by ``DatasetDiff.to_dict()``.
REPORT_SCHEMA_VERSION = "1.1"

# Backward-compatible private aliases (used before 0.3.0).
_is_null_induced_float = is_null_induced_float
_looks_like_dates = looks_like_dates
_finite_or_none = finite_or_none


def _new_values(old: pd.Series, new: pd.Series, config: DiffConfig) -> dict[str, float]:
    return new_values(old, new, config)


@dataclass
class ColumnDiff:
    """Comparison details for one column."""

    name: str
    old_dtype: str
    new_dtype: str
    null_rate_old: float
    null_rate_new: float
    unique_count_old: int
    unique_count_new: int
    old_stats: NumericStats | None
    new_stats: NumericStats | None
    drift: NumericDrift | None
    old_category_stats: CategoryStats | None
    new_category_stats: CategoryStats | None
    config: DiffConfig
    distribution: DistributionDrift | None = None
    old_datetime_stats: DatetimeStats | None = None
    new_datetime_stats: DatetimeStats | None = None

    @property
    def null_rate_change(self) -> float:
        """Change in null rate from old dataset to new dataset."""
        return self.null_rate_new - self.null_rate_old

    @property
    def unique_count_change(self) -> int:
        """Change in unique value count."""
        return self.unique_count_new - self.unique_count_old

    @property
    def dtype_changed(self) -> bool:
        """Whether the column data type changed."""
        return self.old_dtype != self.new_dtype

    @property
    def severity(self) -> str:
        """Return severity based on configured null-rate thresholds."""
        if self.null_rate_change >= self.config.critical_null_rate:
            return "CRITICAL"

        if self.null_rate_change >= self.config.warning_null_rate:
            return "WARNING"

        return "INFO"

    def to_dict(self) -> dict[str, Any]:
        """Return this column comparison as a JSON-friendly dictionary."""

        def _opt(value: Any) -> Any:
            return value.to_dict() if value is not None else None

        return {
            "name": self.name,
            "old_dtype": self.old_dtype,
            "new_dtype": self.new_dtype,
            "dtype_changed": self.dtype_changed,
            "null_rate_old": self.null_rate_old,
            "null_rate_new": self.null_rate_new,
            "null_rate_change": self.null_rate_change,
            "unique_count_old": self.unique_count_old,
            "unique_count_new": self.unique_count_new,
            "unique_count_change": self.unique_count_change,
            "severity": self.severity,
            "old_stats": _opt(self.old_stats),
            "new_stats": _opt(self.new_stats),
            "drift": _opt(self.drift),
            "old_category_stats": _opt(self.old_category_stats),
            "new_category_stats": _opt(self.new_category_stats),
            "distribution": _opt(self.distribution),
            "old_datetime_stats": _opt(self.old_datetime_stats),
            "new_datetime_stats": _opt(self.new_datetime_stats),
        }


def _change_severity(pct: float, config: DiffConfig) -> str:
    if pct >= config.critical_changed_rows_pct:
        return "CRITICAL"
    if pct >= config.warning_changed_rows_pct:
        return "WARNING"
    return "INFO"


@dataclass
class DatasetDiff:
    rows_old: int
    rows_new: int
    added_columns: list[str]
    removed_columns: list[str]
    changed_types: dict[str, tuple[str, str]]
    null_rate_changes: dict[str, tuple[float, float]]
    unique_count_changes: dict[str, tuple[int, int]]
    column_diffs: dict[str, ColumnDiff]
    config: DiffConfig = field(default_factory=DiffConfig)
    null_induced_type_changes: frozenset[str] = frozenset()
    # column -> {new value: share of non-null rows in the new dataset}
    new_category_values: dict[str, dict[str, float]] = field(
        default_factory=dict
    )
    row_diff: RowDiff | None = None
    segment_diff: SegmentDiff | None = None
    # column -> (latest timestamp before, latest timestamp now)
    stale_columns: dict[str, tuple[pd.Timestamp | None, pd.Timestamp | None]] = (
        field(default_factory=dict)
    )

    @property
    def row_change(self) -> int:
        """Return the difference in row count."""
        return self.rows_new - self.rows_old

    @property
    def row_change_pct(self) -> float:
        """Return the percentage change in row count."""
        if self.rows_old == 0:
            return 0.0

        return (self.row_change / self.rows_old) * 100

    def column(self, name: str) -> ColumnDiff:
        """Return the comparison details for a common column."""
        try:
            return self.column_diffs[name]
        except KeyError:
            raise KeyError(
                f"Column '{name}' was not present in both datasets."
            ) from None

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    def issues(self) -> list[Issue]:
        """Return every notable change, most severe first.

        See ``datadiff_engine.ISSUE_KINDS`` for the full list of kinds.
        """
        found: list[Issue] = []
        found.extend(self._dataset_issues())
        found.extend(self._column_issues())
        found.extend(self._row_issues())
        if self.segment_diff is not None:
            found.extend(self.segment_diff.findings)

        # Stable sort: most severe first, original order otherwise.
        return sorted(
            found,
            key=lambda issue: -SEVERITY_ORDER[issue.severity],
        )

    def _dataset_issues(self) -> list[Issue]:
        cfg = self.config
        found: list[Issue] = []

        if self.rows_old > 0 and self.rows_new == 0:
            found.append(Issue(
                kind="empty_dataset",
                severity="CRITICAL",
                message=f"New dataset is empty (was {self.rows_old:,} rows).",
            ))
        elif self.rows_old > 0:
            change = abs(self.row_change_pct)
            if change >= cfg.critical_row_change_pct:
                severity: str | None = "CRITICAL"
            elif change >= cfg.warning_row_change_pct:
                severity = "WARNING"
            else:
                severity = None

            if severity:
                found.append(Issue(
                    kind="row_count_change",
                    severity=severity,
                    message=(
                        f"Row count changed {self.rows_old:,} → "
                        f"{self.rows_new:,} ({self.row_change_pct:+.1f}%)."
                    ),
                ))

        for name in self.removed_columns:
            found.append(Issue(
                kind="column_removed",
                severity="CRITICAL",
                column=name,
                message=f"Column '{name}' was removed.",
            ))

        for name in self.added_columns:
            found.append(Issue(
                kind="column_added",
                severity="INFO",
                column=name,
                message=f"Column '{name}' was added.",
            ))

        return found

    def _column_issues(self) -> list[Issue]:
        found: list[Issue] = []

        for name, column in self.column_diffs.items():
            if column.dtype_changed and name in self.null_induced_type_changes:
                # pandas stores integers with missing values as float64.
                # The values themselves are still whole numbers, so this
                # is a side effect of the nulls, not a real type change.
                found.append(Issue(
                    kind="type_changed",
                    severity="INFO",
                    column=name,
                    message=(
                        f"Column '{name}' changed type "
                        f"{column.old_dtype} → {column.new_dtype} because "
                        "it now contains missing values (values are still "
                        "whole numbers)."
                    ),
                ))
            elif column.dtype_changed:
                found.append(Issue(
                    kind="type_changed",
                    severity="WARNING",
                    column=name,
                    message=(
                        f"Column '{name}' changed type "
                        f"{column.old_dtype} → {column.new_dtype}."
                    ),
                ))

            if column.severity in ("WARNING", "CRITICAL"):
                found.append(Issue(
                    kind="null_rate_increase",
                    severity=column.severity,
                    column=name,
                    message=(
                        f"Null rate in '{name}' rose "
                        f"{column.null_rate_old:.1%} → "
                        f"{column.null_rate_new:.1%}."
                    ),
                ))

            appeared = self.new_category_values.get(name)
            if appeared:
                listed = ", ".join(
                    f"'{value}' ({share:.0%})"
                    for value, share in sorted(
                        appeared.items(), key=lambda item: -item[1]
                    )[:5]
                )
                found.append(Issue(
                    kind="new_category_values",
                    severity="WARNING",
                    column=name,
                    message=(
                        f"New value(s) in '{name}' not seen before: "
                        f"{listed} of rows."
                    ),
                ))

            if column.drift is not None and column.drift.has_drift:
                if column.drift.from_zero_baseline:
                    detail = "moved away from a zero baseline"
                else:
                    detail = (
                        f"mean {column.drift.mean_change_pct:+.1f}%, "
                        f"median {column.drift.median_change_pct:+.1f}%, "
                        f"p95 {column.drift.p95_change_pct:+.1f}%"
                    )
                found.append(Issue(
                    kind="numeric_drift",
                    severity="WARNING",
                    column=name,
                    message=f"Numeric drift in '{name}': {detail}.",
                ))

            dist = column.distribution
            if dist is not None and dist.severity is not None:
                if dist.method == "numeric":
                    detail = (
                        f"PSI {dist.psi:.3f}, KS {dist.ks_statistic:.3f} "
                        f"(p={dist.ks_p_value:.2g})"
                    )
                else:
                    detail = (
                        f"PSI {dist.psi:.3f}, "
                        f"Jensen-Shannon {dist.js_distance:.3f}"
                    )
                found.append(Issue(
                    kind="distribution_drift",
                    severity=dist.severity,
                    column=name,
                    message=f"Distribution of '{name}' shifted: {detail}.",
                    details=dist.to_dict(),
                ))

        for name, (before, after) in self.stale_columns.items():
            found.append(Issue(
                kind="stale_data",
                severity="WARNING",
                column=name,
                message=(
                    f"Latest '{name}' did not move forward "
                    f"({_fmt_ts(before)} → {_fmt_ts(after)})."
                ),
                details={"max_old": _fmt_ts(before), "max_new": _fmt_ts(after)},
            ))

        return found

    def _row_issues(self) -> list[Issue]:
        rd = self.row_diff
        if rd is None:
            return []

        found: list[Issue] = []
        key = ", ".join(map(str, rd.key))

        if rd.duplicate_keys_new or rd.duplicate_keys_old:
            found.append(Issue(
                kind="duplicate_keys",
                severity="CRITICAL" if rd.duplicate_keys_new else "WARNING",
                message=(
                    f"Key ({key}) is not unique: "
                    f"{rd.duplicate_keys_old:,} duplicate(s) before, "
                    f"{rd.duplicate_keys_new:,} now."
                ),
                details={"old": rd.duplicate_keys_old,
                         "new": rd.duplicate_keys_new},
            ))

        if rd.null_keys_new or rd.null_keys_old:
            found.append(Issue(
                kind="null_keys",
                severity="WARNING",
                message=(
                    f"Key ({key}) has missing values: "
                    f"{rd.null_keys_old:,} row(s) before, "
                    f"{rd.null_keys_new:,} now."
                ),
                details={"old": rd.null_keys_old, "new": rd.null_keys_new},
            ))

        matched_old = rd.rows_matched + rd.rows_removed
        if rd.rows_removed:
            pct = rd.rows_removed / max(matched_old, 1) * 100
            found.append(Issue(
                kind="rows_removed",
                severity=_change_severity(pct, self.config),
                message=(
                    f"{rd.rows_removed:,} row(s) removed ({pct:.1f}% of "
                    "the old keys)."
                ),
                details={"count": rd.rows_removed, "pct": pct},
            ))

        if rd.rows_changed:
            pct = rd.rows_changed / max(rd.rows_matched, 1) * 100
            columns = ", ".join(
                f"'{name}' ({count:,})"
                for name, count in list(rd.changed_by_column.items())[:5]
            )
            found.append(Issue(
                kind="rows_changed",
                severity=_change_severity(pct, self.config),
                message=(
                    f"{rd.rows_changed:,} matched row(s) changed "
                    f"({pct:.1f}%), most in {columns}."
                ),
                details={
                    "count": rd.rows_changed,
                    "pct": pct,
                    "by_column": rd.changed_by_column,
                },
            ))

        if rd.rows_added:
            found.append(Issue(
                kind="rows_added",
                severity="INFO",
                message=f"{rd.rows_added:,} new row(s) by key.",
                details={"count": rd.rows_added},
            ))

        return found

    @property
    def overall_severity(self) -> str:
        """The highest severity among all issues ("INFO" if none)."""
        issues = self.issues()
        if not issues:
            return "INFO"
        return issues[0].severity

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return the dataset comparison as a JSON-friendly dictionary."""
        issues = self.issues()
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "summary": {
                "overall_severity": (
                    issues[0].severity if issues else "INFO"
                ),
                "issue_count": len(issues),
                "issues": [issue.to_dict() for issue in issues],
            },
            "rows": {
                "old": self.rows_old,
                "new": self.rows_new,
                "change": self.row_change,
                "change_pct": self.row_change_pct,
            },
            "schema": {
                "added": self.added_columns,
                "removed": self.removed_columns,
                "changed_types": {
                    name: [old_type, new_type]
                    for name, (old_type, new_type)
                    in self.changed_types.items()
                },
            },
            "columns": {
                name: column_diff.to_dict()
                for name, column_diff in self.column_diffs.items()
            },
            "row_diff": (
                self.row_diff.to_dict() if self.row_diff is not None else None
            ),
            "segments": (
                self.segment_diff.to_dict()
                if self.segment_diff is not None
                else None
            ),
            "config": self.config.to_dict(),
        }

    def to_text(self) -> str:
        """Plain-text report (what ``print(diff)`` shows)."""
        return _report.to_text(self)

    def to_markdown(self) -> str:
        """Markdown report, e.g. for a pull-request comment or a wiki."""
        return _report.to_markdown(self)

    def to_html(self, title: str = "Dataset diff") -> str:
        """Self-contained HTML report (no external assets or scripts)."""
        return _report.to_html(self, title=title)

    def __str__(self) -> str:
        return self.to_text()


def _fmt_ts(value: pd.Timestamp | None) -> str:
    return value.isoformat() if value is not None else "none"


def compare(
    old: Any,
    new: Any,
    config: DiffConfig | None = None,
    *,
    key: str | list[str] | None = None,
    segment_by: str | list[str] | None = None,
) -> DatasetDiff:
    """Compare two datasets and return a structured diff.

    Args:
        old: The baseline dataset: a pandas DataFrame, a Polars
            DataFrame/LazyFrame, a DuckDB relation or a PyArrow Table.
        new: The dataset to check, in any of the same formats.
        config: Thresholds and switches; ``DiffConfig()`` if omitted.
        key: Column(s) that identify a row. When given, rows are matched
            and added, removed and changed rows are reported.
        segment_by: Column(s) to split the data into segments (e.g.
            ``"country"``). Changes hidden inside a segment are reported.
    """
    old = make_hashable(to_pandas(old, "old"))
    new = make_hashable(to_pandas(new, "new"))

    if config is None:
        config = DiffConfig()

    key_columns = as_list(key)
    segment_columns = as_list(segment_by)

    old_columns = set(old.columns)
    new_columns = set(new.columns)

    common_columns = sorted(old_columns & new_columns, key=str)

    added_columns = sorted(new_columns - old_columns, key=str)
    removed_columns = sorted(old_columns - new_columns, key=str)

    changed_types: dict[str, tuple[str, str]] = {}
    null_rate_changes: dict[str, tuple[float, float]] = {}
    unique_count_changes: dict[str, tuple[int, int]] = {}
    column_diffs: dict[str, ColumnDiff] = {}
    null_induced: set[str] = set()
    new_values_by_column: dict[str, dict[str, float]] = {}
    stale: dict[str, tuple[pd.Timestamp | None, pd.Timestamp | None]] = {}

    for column in common_columns:
        old_col = old[column]
        new_col = new[column]

        old_type = str(old_col.dtype)
        new_type = str(new_col.dtype)

        old_null_rate = float(old_col.isna().mean()) if len(old_col) else 0.0
        new_null_rate = float(new_col.isna().mean()) if len(new_col) else 0.0

        old_unique = int(old_col.nunique(dropna=True))
        new_unique = int(new_col.nunique(dropna=True))

        old_stats = (
            NumericStats.from_series(old_col)
            if pd.api.types.is_numeric_dtype(old_col)
            else None
        )
        new_stats = (
            NumericStats.from_series(new_col)
            if pd.api.types.is_numeric_dtype(new_col)
            else None
        )
        old_category_stats = (
            CategoryStats.from_series(old_col)
            if is_categorical(old_col)
            else None
        )
        new_category_stats = (
            CategoryStats.from_series(new_col)
            if is_categorical(new_col)
            else None
        )
        drift = (
            NumericDrift.from_stats(
                old_stats,
                new_stats,
                threshold_pct=config.drift_threshold_pct,
            )
            if (
                column not in config.ignored_columns
                and old_stats is not None
                and new_stats is not None
            )
            else None
        )

        old_is_date = looks_like_dates(old_col)
        new_is_date = looks_like_dates(new_col)
        old_dt = DatetimeStats.from_series(old_col) if old_is_date else None
        new_dt = DatetimeStats.from_series(new_col) if new_is_date else None

        distribution = _distribution(
            column, old_col, new_col, old_unique, old_is_date or new_is_date,
            config,
        )

        column_diffs[column] = ColumnDiff(
            name=column,
            old_dtype=old_type,
            new_dtype=new_type,
            null_rate_old=old_null_rate,
            null_rate_new=new_null_rate,
            unique_count_old=old_unique,
            unique_count_new=new_unique,
            old_stats=old_stats,
            new_stats=new_stats,
            drift=drift,
            old_category_stats=old_category_stats,
            new_category_stats=new_category_stats,
            config=config,
            distribution=distribution,
            old_datetime_stats=old_dt,
            new_datetime_stats=new_dt,
        )

        if old_type != new_type:
            changed_types[column] = (old_type, new_type)

            if is_null_induced_float(old_col, new_col):
                null_induced.add(column)

        if (
            old_category_stats is not None
            and new_category_stats is not None
            and old_unique <= config.max_categories_for_new_value_check
        ):
            appeared = new_values(old_col, new_col, config)
            if appeared:
                new_values_by_column[column] = appeared

        if old_null_rate != new_null_rate:
            null_rate_changes[column] = (old_null_rate, new_null_rate)

        if old_unique != new_unique:
            unique_count_changes[column] = (old_unique, new_unique)

        if column in config.freshness_columns and len(new) > 0:
            before = (old_dt or DatetimeStats.from_series(old_col)).max
            after = (new_dt or DatetimeStats.from_series(new_col)).max
            if before is not None and (after is None or after <= before):
                stale[column] = (before, after)

    missing_freshness = sorted(config.freshness_columns - set(common_columns))
    if missing_freshness:
        raise ValueError(
            "Freshness column(s) not present in both datasets: "
            + ", ".join(missing_freshness)
        )

    row_diff = (
        compare_rows(old, new, key_columns, config) if key_columns else None
    )

    segment_diff = None
    if segment_columns:
        segment_diff = compare_segments(
            old,
            new,
            segment_columns,
            config,
            aggregate_null_change={
                name: diff.null_rate_change
                for name, diff in column_diffs.items()
            },
            aggregate_mean_change={
                name: (diff.drift.mean_change_pct if diff.drift else None)
                for name, diff in column_diffs.items()
            },
            aggregate_drift={
                name: bool(
                    (diff.drift is not None and diff.drift.has_drift)
                    or (
                        diff.distribution is not None
                        and diff.distribution.has_drift
                    )
                )
                for name, diff in column_diffs.items()
            },
        )

    return DatasetDiff(
        rows_old=len(old),
        rows_new=len(new),
        added_columns=added_columns,
        removed_columns=removed_columns,
        changed_types=changed_types,
        null_rate_changes=null_rate_changes,
        unique_count_changes=unique_count_changes,
        column_diffs=column_diffs,
        config=config,
        null_induced_type_changes=frozenset(null_induced),
        new_category_values=new_values_by_column,
        row_diff=row_diff,
        segment_diff=segment_diff,
        stale_columns=stale,
    )


def _distribution(
    column: str,
    old_col: pd.Series,
    new_col: pd.Series,
    old_unique: int,
    is_date: bool,
    config: DiffConfig,
) -> DistributionDrift | None:
    """Statistical drift for one column, or None when it does not apply."""
    if not config.statistical_tests or column in config.ignored_columns:
        return None
    if is_date:
        return None  # dates move forward by design; see freshness checks
    if (
        old_col.notna().sum() < config.min_rows_for_tests
        or new_col.notna().sum() < config.min_rows_for_tests
    ):
        return None

    if is_numeric(old_col) and is_numeric(new_col):
        return DistributionDrift.numeric(old_col, new_col, config)

    categorical = (
        (is_categorical(old_col) or pd.api.types.is_bool_dtype(old_col))
        and (is_categorical(new_col) or pd.api.types.is_bool_dtype(new_col))
    )
    if categorical and old_unique <= config.max_categories_for_new_value_check:
        return DistributionDrift.categorical(old_col, new_col, config)

    return None


__all__ = [
    "SEVERITY_ORDER",
    "CategoryStats",
    "ColumnDiff",
    "DatasetDiff",
    "DatetimeStats",
    "DiffConfig",
    "DistributionDrift",
    "Issue",
    "NumericDrift",
    "NumericStats",
    "RowDiff",
    "SegmentDiff",
    "compare",
]
