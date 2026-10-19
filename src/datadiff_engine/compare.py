import math
from dataclasses import dataclass, field

import pandas as pd

SEVERITY_ORDER = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}


def _is_null_induced_float(old: pd.Series, new: pd.Series) -> bool:
    """Whether an int → float change is only caused by new missing values.

    pandas cannot store missing values in an int64 column, so it converts
    the column to float64. If the new column has nulls and every non-null
    value is still a whole number, the "type change" is a side effect.
    """
    if not (
        pd.api.types.is_integer_dtype(old)
        and pd.api.types.is_float_dtype(new)
    ):
        return False

    if not new.isna().any():
        return False

    values = new.dropna()
    return bool((values == values.round()).all())


def _looks_like_dates(series: pd.Series, sample_size: int = 50) -> bool:
    """Whether a text column holds dates or timestamps (e.g. "2026-10-02")."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return True

    sample = series.dropna().astype(str).head(sample_size)
    if sample.empty:
        return False

    # Require something date-shaped (digits plus a separator) so that
    # short codes like "MCT" or numbers like "42" are never treated as dates.
    if not sample.str.contains(r"\d{1,4}[-/.]\d{1,2}", regex=True).all():
        return False

    parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
    return bool(parsed.notna().all())


def _new_values(
    old: pd.Series,
    new: pd.Series,
    config: "DiffConfig",
) -> dict[str, float]:
    """Values in a categorical column that did not exist before.

    Returns {value: share of non-null new rows}, ignoring values rarer than
    ``config.new_value_min_share``.
    """
    if _looks_like_dates(old) or _looks_like_dates(new):
        # Dates stored as text get new values every day by design.
        return {}

    old_values = set(old.dropna().astype(str))
    new_counts = new.dropna().astype(str).value_counts(normalize=True)
    return {
        str(value): float(share)
        for value, share in new_counts.items()
        if value not in old_values and share >= config.new_value_min_share
    }


def _finite_or_none(value: float) -> float | None:
    """Return the value if it is a finite number, otherwise None.

    JSON has no representation for infinity or NaN, so reports use None
    for those values.
    """
    return value if math.isfinite(value) else None

@dataclass
class NumericStats:
    """Statistical summary for a numeric column."""

    count: int
    min: float
    max: float
    mean: float
    median: float
    p95: float

    @classmethod
    def from_series(cls, series: pd.Series) -> "NumericStats":
        """Calculate numeric statistics from a pandas Series."""
        values = series.dropna()

        return cls(
            count=int(values.count()),
            min=float(values.min()),
            max=float(values.max()),
            mean=float(values.mean()),
            median=float(values.median()),
            p95=float(values.quantile(0.95)),
        )
    def to_dict(self) -> dict:
        """Return statistics as a JSON-friendly dictionary.

        Statistics of an all-null column are NaN; they are reported as None.
        """
        return {
            "count": self.count,
            "min": _finite_or_none(self.min),
            "max": _finite_or_none(self.max),
            "mean": _finite_or_none(self.mean),
            "median": _finite_or_none(self.median),
            "p95": _finite_or_none(self.p95),
        }

@dataclass
class NumericDrift:
    """Describe relative changes in numeric statistics."""

    mean_change_pct: float
    median_change_pct: float
    p95_change_pct: float
    threshold_pct: float = 20.0

    @property
    def has_drift(self) -> bool:
        """Whether any tracked statistic changed beyond the threshold."""
        return any(
            abs(change) >= self.threshold_pct
            for change in (
                self.mean_change_pct,
                self.median_change_pct,
                self.p95_change_pct,
            )
        )

    @staticmethod
    def _relative_change_pct(old: float, new: float) -> float:
        """Calculate relative percentage change."""
        if old == 0:
            if new == 0:
                return 0.0
            return float("inf")

        return ((new - old) / abs(old)) * 100

    @classmethod
    def from_stats(
        cls,
        old: NumericStats,
        new: NumericStats,
        threshold_pct: float = 20.0,
    ) -> "NumericDrift":
        """Calculate drift from two numeric-stat summaries."""
        return cls(
            mean_change_pct=cls._relative_change_pct(
                old.mean,
                new.mean,
            ),
            median_change_pct=cls._relative_change_pct(
                old.median,
                new.median,
            ),
            p95_change_pct=cls._relative_change_pct(
                old.p95,
                new.p95,
            ),
            threshold_pct=threshold_pct,
        )

    @property
    def from_zero_baseline(self) -> bool:
        """Whether a statistic moved away from a baseline of zero.

        Relative change from zero is infinite, so it is reported
        separately instead of as a percentage.
        """
        return any(
            math.isinf(change)
            for change in (
                self.mean_change_pct,
                self.median_change_pct,
                self.p95_change_pct,
            )
        )

    def to_dict(self) -> dict:
        """Return drift information as a JSON-friendly dictionary.

        Infinite changes (from a zero baseline) are reported as None,
        with ``from_zero_baseline`` set to True.
        """
        return {
            "mean_change_pct": _finite_or_none(self.mean_change_pct),
            "median_change_pct": _finite_or_none(self.median_change_pct),
            "p95_change_pct": _finite_or_none(self.p95_change_pct),
            "threshold_pct": self.threshold_pct,
            "has_drift": self.has_drift,
            "from_zero_baseline": self.from_zero_baseline,
        }

@dataclass
class CategoryStats:
    """Statistical summary for a categorical column."""

    count: int
    unique_count: int
    top_values: dict[str, int]

    @classmethod
    def from_series(
        cls,
        series: pd.Series,
        top_n: int = 10,
    ) -> "CategoryStats":
        """Calculate categorical statistics from a pandas Series."""
        values = series.dropna()

        counts = values.value_counts().head(top_n)

        return cls(
            count=int(values.count()),
            unique_count=int(values.nunique()),
            top_values={
                str(value): int(count)
                for value, count in counts.items()
            },
        )

    def to_dict(self) -> dict:
        """Return categorical statistics as a JSON-friendly dictionary."""
        return {
            "count": self.count,
            "unique_count": self.unique_count,
            "top_values": self.top_values,
        }

@dataclass(frozen=True)
class DiffConfig:
    """Configuration for dataset comparison."""

    warning_null_rate: float = 0.05
    critical_null_rate: float = 0.20
    ignored_columns: frozenset[str] = frozenset()
    drift_threshold_pct: float = 20.0
    warning_row_change_pct: float = 20.0
    critical_row_change_pct: float = 50.0
    # New category values are only checked on low-cardinality columns
    # (status codes, currencies, channels), not on free text or IDs.
    max_categories_for_new_value_check: int = 50
    new_value_min_share: float = 0.01

    def __post_init__(self) -> None:
        if self.warning_null_rate < 0:
            raise ValueError("warning_null_rate must be >= 0")

        if self.critical_null_rate < self.warning_null_rate:
            raise ValueError(
                "critical_null_rate must be >= warning_null_rate"
            )

        if self.drift_threshold_pct <= 0:
            raise ValueError("drift_threshold_pct must be > 0")

        if self.warning_row_change_pct < 0:
            raise ValueError("warning_row_change_pct must be >= 0")

        if self.critical_row_change_pct < self.warning_row_change_pct:
            raise ValueError(
                "critical_row_change_pct must be >= warning_row_change_pct"
            )

        if self.max_categories_for_new_value_check < 0:
            raise ValueError("max_categories_for_new_value_check must be >= 0")

        if not 0 <= self.new_value_min_share <= 1:
            raise ValueError("new_value_min_share must be between 0 and 1")


@dataclass(frozen=True)
class Issue:
    """One notable change found in a dataset comparison.

    Issues are designed to be read by people, CI checks and automated
    agents: each has a stable ``kind``, the affected ``column`` (or None
    for dataset-level issues), a ``severity`` and a readable ``message``.
    """

    kind: str
    severity: str
    message: str
    column: str | None = None

    def to_dict(self) -> dict:
        """Return the issue as a JSON-friendly dictionary."""
        return {
            "kind": self.kind,
            "severity": self.severity,
            "column": self.column,
            "message": self.message,
        }


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

    def to_dict(self) -> dict:
        """Return this column comparison as a JSON-friendly dictionary."""
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
            "old_stats": (
                self.old_stats.to_dict()
                if self.old_stats is not None
                else None
            ),
            "new_stats": (
                self.new_stats.to_dict()
                if self.new_stats is not None
                else None
            ),
            "drift": (
                self.drift.to_dict()
                if self.drift is not None
                else None
            ),

            "old_category_stats": (
                self.old_category_stats.to_dict()
                if self.old_category_stats is not None
                else None
            ),
            "new_category_stats": (
                self.new_category_stats.to_dict()
                if self.new_category_stats is not None
                else None
            ),            
        }

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

    def issues(self) -> list[Issue]:
        """Return every notable change, most severe first.

        Rules:
        - new dataset is empty while the old one was not: CRITICAL
        - row count changed by at least the configured percentages:
          WARNING / CRITICAL
        - column removed: CRITICAL (downstream code usually depends on it)
        - column added: INFO
        - data type changed: WARNING
        - null rate rose past the configured thresholds:
          WARNING / CRITICAL (same rule as ``ColumnDiff.severity``)
        - numeric drift beyond ``drift_threshold_pct``: WARNING
        """
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
                severity = "CRITICAL"
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

            new_values = self.new_category_values.get(name)
            if new_values:
                listed = ", ".join(
                    f"'{value}' ({share:.0%})"
                    for value, share in sorted(
                        new_values.items(), key=lambda item: -item[1]
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

        return sorted(
            found,
            key=lambda issue: -SEVERITY_ORDER[issue.severity],
        )

    @property
    def overall_severity(self) -> str:
        """The highest severity among all issues ("INFO" if none)."""
        issues = self.issues()
        if not issues:
            return "INFO"
        return issues[0].severity

    def to_dict(self) -> dict:
        """Return the dataset comparison as a JSON-friendly dictionary."""
        issues = self.issues()
        return {
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
        }

    def to_text(self) -> str:
        issues = self.issues()
        lines = [
            "DATASET DIFF",
            "=" * 40,
            "",
            f"OVERALL SEVERITY: {issues[0].severity if issues else 'INFO'}",
        ]

        for issue in issues:
            lines.append(f"  [{issue.severity}] {issue.message}")

        if not issues:
            lines.append("  No notable changes.")

        lines.extend([
            "",
            "ROWS",
            f"  {self.rows_old:,} → {self.rows_new:,}",
            f"  Change: {self.row_change:+,} "
            f"({self.row_change_pct:+.2f}%)",
            "",
            "SCHEMA",
            f"  + Added:   {self.added_columns or 'none'}",
            f"  - Removed: {self.removed_columns or 'none'}",
        ])

        if self.changed_types:
            for name, (old_type, new_type) in self.changed_types.items():
                lines.append(
                    f"  ~ Changed: {name} ({old_type} → {new_type})"
                )
        else:
            lines.append("  ~ Changed: none")

        lines.extend([
            "",
            "COLUMN CHANGES",
            "-" * 40,
        ])

        for name, column in self.column_diffs.items():
            has_changes = (
                column.dtype_changed
                or column.null_rate_change != 0
                or column.unique_count_change != 0
            )

            if not has_changes:
                continue

            lines.append(name)

            if column.dtype_changed:
                lines.append(
                    f"  Data type: {column.old_dtype} → "
                    f"{column.new_dtype}"
                )

            if column.null_rate_change != 0:
                change_points = column.null_rate_change * 100

                lines.append(
                    f"  Null rate: {column.null_rate_old:.2%} → "
                    f"{column.null_rate_new:.2%} "
                    f"({change_points:+.2f} pp)"
                )

            if column.unique_count_change != 0:
                lines.append(
                    f"  Unique values: {column.unique_count_old:,} → "
                    f"{column.unique_count_new:,} "
                    f"({column.unique_count_change:+,})"
                )

            lines.append(f"  Severity:  {column.severity}")

            if column.old_stats is not None and column.new_stats is not None:
                old_stats = column.old_stats
                new_stats = column.new_stats

                lines.extend([
                    "",
                    "  Statistics",
                    f"    Mean:    {old_stats.mean:.2f} → "
                    f"{new_stats.mean:.2f}",
                    f"    Median:  {old_stats.median:.2f} → "
                    f"{new_stats.median:.2f}",
                    f"    Min:     {old_stats.min:.2f} → "
                    f"{new_stats.min:.2f}",
                    f"    Max:     {old_stats.max:.2f} → "
                    f"{new_stats.max:.2f}",
                    f"    P95:     {old_stats.p95:.2f} → "
                    f"{new_stats.p95:.2f}",
                ])

            lines.append("")

        return "\n".join(lines)

    # ----Change----------------------

    def __str__(self) -> str:
        return self.to_text()


def compare(
    old: pd.DataFrame,
    new: pd.DataFrame,
    config: DiffConfig | None = None,
) -> DatasetDiff:
    """Compare two pandas DataFrames and return a structured diff."""

    if not isinstance(old, pd.DataFrame):
        raise TypeError("old must be a pandas DataFrame")

    if not isinstance(new, pd.DataFrame):
        raise TypeError("new must be a pandas DataFrame")

    if config is None:
        config = DiffConfig()

    old_columns = set(old.columns)
    new_columns = set(new.columns)

    common_columns = sorted(old_columns & new_columns)

    added_columns = sorted(new_columns - old_columns)
    removed_columns = sorted(old_columns - new_columns)

    changed_types: dict[str, tuple[str, str]] = {}
    null_rate_changes: dict[str, tuple[float, float]] = {}
    unique_count_changes: dict[str, tuple[int, int]] = {}
    column_diffs: dict[str, ColumnDiff] = {}
    null_induced: set[str] = set()
    new_values_by_column: dict[str, dict[str, float]] = {}

    for column in common_columns:
        old_type = str(old[column].dtype)
        new_type = str(new[column].dtype)

        old_null_rate = float(old[column].isna().mean())
        new_null_rate = float(new[column].isna().mean())

        old_unique = int(old[column].nunique(dropna=True))
        new_unique = int(new[column].nunique(dropna=True))

        old_stats = (
            NumericStats.from_series(old[column])
            if pd.api.types.is_numeric_dtype(old[column])
            else None
        )

        new_stats = (
            NumericStats.from_series(new[column])
            if pd.api.types.is_numeric_dtype(new[column])
            else None
        )
        old_category_stats = (
            CategoryStats.from_series(old[column])
            if (
                pd.api.types.is_object_dtype(old[column])
                or pd.api.types.is_string_dtype(old[column])
                or isinstance(old[column].dtype, pd.CategoricalDtype)
            )
            else None
        )

        new_category_stats = (
            CategoryStats.from_series(new[column])
            if (
                pd.api.types.is_object_dtype(new[column])
                or pd.api.types.is_string_dtype(new[column])
                or isinstance(new[column].dtype, pd.CategoricalDtype)
            )
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
        )

        if old_type != new_type:
            changed_types[column] = (old_type, new_type)

            if _is_null_induced_float(old[column], new[column]):
                null_induced.add(column)

        if (
            old_category_stats is not None
            and new_category_stats is not None
            and old_unique <= config.max_categories_for_new_value_check
        ):
            appeared = _new_values(old[column], new[column], config)
            if appeared:
                new_values_by_column[column] = appeared

        if old_null_rate != new_null_rate:
            null_rate_changes[column] = (
                old_null_rate,
                new_null_rate,
            )

        if old_unique != new_unique:
            unique_count_changes[column] = (
                old_unique,
                new_unique,
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
    )