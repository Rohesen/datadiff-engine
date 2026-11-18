"""Small helpers shared by the comparison modules."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from .config import DiffConfig

SEVERITY_ORDER: dict[str, int] = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}


def max_severity(*severities: str | None) -> str | None:
    """Return the highest of the given severities, ignoring None."""
    present = [s for s in severities if s is not None]
    if not present:
        return None
    return max(present, key=lambda s: SEVERITY_ORDER[s])


def finite_or_none(value: float | None) -> float | None:
    """Return the value if it is a finite number, otherwise None.

    JSON has no representation for infinity or NaN, so reports use None
    for those values.
    """
    if value is None:
        return None
    return value if math.isfinite(value) else None


def as_list(columns: Any) -> list[Any]:
    """Normalise a column name or a list of names into a list."""
    if columns is None:
        return []
    if isinstance(columns, (list, tuple)):
        return list(columns)
    # A single name: strings, but also integers or other hashable labels.
    return [columns]


def is_bool(series: pd.Series) -> bool:
    return pd.api.types.is_bool_dtype(series)


def is_numeric(series: pd.Series) -> bool:
    """Numeric, excluding booleans (which behave like categories)."""
    return pd.api.types.is_numeric_dtype(series) and not is_bool(series)


def is_categorical(series: pd.Series) -> bool:
    return (
        pd.api.types.is_object_dtype(series)
        or pd.api.types.is_string_dtype(series)
        or isinstance(series.dtype, pd.CategoricalDtype)
    )


def is_null_induced_float(old: pd.Series, new: pd.Series) -> bool:
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


def looks_like_dates(series: pd.Series, sample_size: int = 50) -> bool:
    """Whether a column holds dates or timestamps (e.g. "2026-10-02")."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return True

    if not is_categorical(series):
        return False

    sample = series.dropna().astype(str).head(sample_size)
    if sample.empty:
        return False

    # Require something date-shaped (digits plus a separator) so that
    # short codes like "MCT" or numbers like "42" are never treated as dates.
    if not sample.str.contains(r"\d{1,4}[-/.]\d{1,2}", regex=True).all():
        return False

    parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
    return bool(parsed.notna().all())


def to_datetime(series: pd.Series) -> pd.Series:
    """Parse a column as timezone-naive datetimes (unparseable → NaT)."""
    if pd.api.types.is_datetime64_any_dtype(series):
        parsed = series
    else:
        parsed = pd.to_datetime(series, errors="coerce", format="mixed")
    if isinstance(parsed.dtype, pd.DatetimeTZDtype):
        parsed = parsed.dt.tz_convert("UTC").dt.tz_localize(None)
    return parsed


def new_values(
    old: pd.Series,
    new: pd.Series,
    config: DiffConfig,
) -> dict[str, float]:
    """Values in a categorical column that did not exist before.

    Returns {value: share of non-null new rows}, ignoring values rarer than
    ``config.new_value_min_share``.
    """
    if looks_like_dates(old) or looks_like_dates(new):
        # Dates stored as text get new values every day by design.
        return {}

    old_values = set(old.dropna().astype(str))
    new_counts = new.dropna().astype(str).value_counts(normalize=True)
    return {
        str(value): float(share)
        for value, share in new_counts.items()
        if value not in old_values and share >= config.new_value_min_share
    }
