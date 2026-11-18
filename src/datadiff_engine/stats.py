"""Per-column summary statistics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ._utils import finite_or_none, to_datetime


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
    def from_series(cls, series: pd.Series) -> NumericStats:
        """Calculate numeric statistics from a pandas Series."""
        values = series.dropna()
        if pd.api.types.is_bool_dtype(values):
            values = values.astype(float)

        # Infinite values make some statistics NaN; that is reported as
        # None in to_dict(), so NumPy's warnings are just noise here.
        with np.errstate(invalid="ignore", over="ignore"):
            return cls(
                count=int(values.count()),
                min=float(values.min()),
                max=float(values.max()),
                mean=float(values.mean()),
                median=float(values.median()),
                p95=float(values.quantile(0.95)),
            )

    def to_dict(self) -> dict[str, Any]:
        """Return statistics as a JSON-friendly dictionary.

        Statistics of an all-null column are NaN; they are reported as None.
        """
        return {
            "count": self.count,
            "min": finite_or_none(self.min),
            "max": finite_or_none(self.max),
            "mean": finite_or_none(self.mean),
            "median": finite_or_none(self.median),
            "p95": finite_or_none(self.p95),
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
    ) -> CategoryStats:
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

    def to_dict(self) -> dict[str, Any]:
        """Return categorical statistics as a JSON-friendly dictionary."""
        return {
            "count": self.count,
            "unique_count": self.unique_count,
            "top_values": self.top_values,
        }


@dataclass
class DatetimeStats:
    """Range of a date/time column (native datetimes or date-like text)."""

    count: int
    min: pd.Timestamp | None
    max: pd.Timestamp | None

    @classmethod
    def from_series(cls, series: pd.Series) -> DatetimeStats:
        values = to_datetime(series).dropna()
        if values.empty:
            return cls(count=0, min=None, max=None)
        return cls(
            count=int(values.count()),
            min=pd.Timestamp(values.min()),
            max=pd.Timestamp(values.max()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "min": self.min.isoformat() if self.min is not None else None,
            "max": self.max.isoformat() if self.max is not None else None,
        }
