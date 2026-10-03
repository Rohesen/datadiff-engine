from dataclasses import dataclass

import pandas as pd

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
        """Return statistics as a JSON-friendly dictionary."""
        return {
            "count": self.count,
            "min": self.min,
            "max": self.max,
            "mean": self.mean,
            "median": self.median,
            "p95": self.p95,
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
        )

    def to_dict(self) -> dict:
        """Return drift information as a JSON-friendly dictionary."""
        return {
            "mean_change_pct": self.mean_change_pct,
            "median_change_pct": self.median_change_pct,
            "p95_change_pct": self.p95_change_pct,
            "threshold_pct": self.threshold_pct,
            "has_drift": self.has_drift,
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

    def __post_init__(self) -> None:
        if self.warning_null_rate < 0:
            raise ValueError("warning_null_rate must be >= 0")

        if self.critical_null_rate < self.warning_null_rate:
            raise ValueError(
                "critical_null_rate must be >= warning_null_rate"
            )


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

    def to_dict(self) -> dict:
        """Return the dataset comparison as a JSON-friendly dictionary."""
        return {
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
        lines = [
            "DATASET DIFF",
            "=" * 40,
            "",
            "ROWS",
            f"  {self.rows_old:,} → {self.rows_new:,}",
            f"  Change: {self.row_change:+,} "
            f"({self.row_change_pct:+.2f}%)",
            "",
            "SCHEMA",
            f"  + Added:   {self.added_columns or 'none'}",
            f"  - Removed: {self.removed_columns or 'none'}",
        ]

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
            NumericDrift.from_stats(old_stats, new_stats)
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
    )