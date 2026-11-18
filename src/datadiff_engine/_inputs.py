"""Accept DataFrames from pandas, Polars, DuckDB and PyArrow.

Only pandas is a hard dependency. The other libraries are detected by
duck typing, so they never need to be imported unless you use them.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd


def to_pandas(data: Any, name: str) -> pd.DataFrame:
    """Convert a supported table object to a pandas DataFrame."""
    if isinstance(data, pd.DataFrame):
        return data

    module = type(data).__module__.split(".")[0]

    # Polars DataFrame or LazyFrame
    if module == "polars":
        if hasattr(data, "collect") and not hasattr(data, "to_pandas"):
            data = data.collect()
        if hasattr(data, "to_pandas"):
            return data.to_pandas()

    # DuckDB relation (e.g. duckdb.sql("SELECT ...") or con.table("t"))
    if module in {"duckdb", "_duckdb"} and hasattr(data, "df"):
        return data.df()

    # PyArrow Table
    if module == "pyarrow" and hasattr(data, "to_pandas"):
        return data.to_pandas()

    raise TypeError(
        f"{name} must be a pandas DataFrame, a Polars DataFrame/LazyFrame, "
        f"a DuckDB relation or a PyArrow Table (got {type(data).__name__})"
    )


def _hashable_text(value: Any) -> Any:
    """A stable text form for list/array/dict cells (e.g. Parquet lists)."""
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, (list, tuple, dict, set)):
        try:
            return json.dumps(value, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(value)
    return value


def make_hashable(frame: pd.DataFrame) -> pd.DataFrame:
    """Turn columns holding lists, arrays or dicts into comparable text.

    Nested values cannot be counted, grouped or matched, so they are
    compared by their JSON text instead. Other columns are untouched.
    """
    converted: dict[Any, pd.Series] = {}
    for name in frame.columns:
        column = frame[name]
        if not pd.api.types.is_object_dtype(column):
            continue
        try:
            column.nunique()
        except TypeError:
            converted[name] = column.map(_hashable_text)
    if not converted:
        return frame
    frame = frame.copy()
    for name, column in converted.items():
        frame[name] = column
    return frame
