"""Key-based, row-level comparison: which rows were added, removed or changed."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ._utils import is_numeric
from .config import DiffConfig


@dataclass
class RowDiff:
    """Row-level comparison of two datasets matched on key columns."""

    key: list[str]
    rows_added: int
    rows_removed: int
    rows_changed: int
    rows_unchanged: int
    # column -> number of matched rows whose value changed
    changed_by_column: dict[str, int]
    duplicate_keys_old: int = 0
    duplicate_keys_new: int = 0
    null_keys_old: int = 0
    null_keys_new: int = 0
    sample_added: list[dict[str, Any]] = field(default_factory=list)
    sample_removed: list[dict[str, Any]] = field(default_factory=list)
    # Each changed sample: {"key": {...}, "changes": {col: [old, new]}}
    sample_changed: list[dict[str, Any]] = field(default_factory=list)

    @property
    def rows_matched(self) -> int:
        return self.rows_changed + self.rows_unchanged

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "rows_added": self.rows_added,
            "rows_removed": self.rows_removed,
            "rows_changed": self.rows_changed,
            "rows_unchanged": self.rows_unchanged,
            "changed_by_column": self.changed_by_column,
            "duplicate_keys_old": self.duplicate_keys_old,
            "duplicate_keys_new": self.duplicate_keys_new,
            "null_keys_old": self.null_keys_old,
            "null_keys_new": self.null_keys_new,
            "sample_added": self.sample_added,
            "sample_removed": self.sample_removed,
            "sample_changed": self.sample_changed,
        }


def _json_value(value: Any) -> Any:
    """Convert a pandas/NumPy scalar into a JSON-friendly Python value."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _records(frame: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    return [
        {str(k): _json_value(v) for k, v in row.items()}
        for row in frame.head(limit).to_dict(orient="records")
    ]


def _cell_differs(x: Any, y: Any) -> bool:
    try:
        return bool(x != y)
    except (TypeError, ValueError):
        return str(x) != str(y)


def _values_differ(
    old: pd.Series, new: pd.Series, config: DiffConfig
) -> np.ndarray:
    """Element-wise "value changed" mask; two missing values are equal."""
    old_na = old.isna().to_numpy()
    new_na = new.isna().to_numpy()
    both_na = old_na & new_na
    one_na = old_na ^ new_na

    if is_numeric(old) and is_numeric(new):
        a = old.to_numpy(dtype=float, na_value=np.nan)
        b = new.to_numpy(dtype=float, na_value=np.nan)
        with np.errstate(invalid="ignore"):
            tolerance = np.maximum(
                config.numeric_abs_tolerance,
                config.numeric_rel_tolerance * np.abs(a),
            )
            differ = np.abs(a - b) > tolerance
        differ = np.where(old_na | new_na, False, differ)
    else:
        a_obj = np.array(old.astype(object).to_numpy(), dtype=object, copy=True)
        b_obj = np.array(new.astype(object).to_numpy(), dtype=object, copy=True)
        # pd.NA cannot be compared; missing positions are masked below.
        a_obj[old_na] = None
        b_obj[new_na] = None
        try:
            differ = np.asarray(a_obj != b_obj, dtype=bool)
        except (TypeError, ValueError):
            # Exotic values (e.g. arrays inside cells): compare one by one.
            differ = np.fromiter(
                (_cell_differs(x, y) for x, y in zip(a_obj, b_obj, strict=True)),
                dtype=bool,
                count=len(a_obj),
            )
        differ = np.where(old_na | new_na, False, differ)

    return (differ | one_na) & ~both_na


def compare_rows(
    old: pd.DataFrame,
    new: pd.DataFrame,
    key: list[str],
    config: DiffConfig,
) -> RowDiff:
    """Match rows on ``key`` and count added, removed and changed rows.

    Rows with a missing key value cannot be matched and are left out.
    When a key is duplicated, only its first row is compared; the
    duplicates are reported separately.
    """
    missing = [
        name
        for name in key
        if name not in old.columns or name not in new.columns
    ]
    if missing:
        raise ValueError(
            "Key column(s) not present in both datasets: "
            + ", ".join(missing)
        )

    null_old = old[key].isna().any(axis=1)
    null_new = new[key].isna().any(axis=1)
    old_valid = old.loc[~null_old]
    new_valid = new.loc[~null_new]

    dup_old = int(old_valid.duplicated(key).sum())
    dup_new = int(new_valid.duplicated(key).sum())
    old_valid = old_valid.drop_duplicates(key)
    new_valid = new_valid.drop_duplicates(key)

    # Align key dtypes (e.g. int64 vs float64 after nulls, or int vs text)
    # so that the merge can match equal keys.
    old_keys = old_valid[key].copy()
    new_keys = new_valid[key].copy()
    for name in key:
        if old_keys[name].dtype != new_keys[name].dtype:
            if is_numeric(old_keys[name]) and is_numeric(new_keys[name]):
                old_keys[name] = old_keys[name].astype(float)
                new_keys[name] = new_keys[name].astype(float)
            else:
                old_keys[name] = old_keys[name].astype(str)
                new_keys[name] = new_keys[name].astype(str)

    old_indexed = old_valid.set_axis(
        pd.MultiIndex.from_frame(old_keys), axis=0
    )
    new_indexed = new_valid.set_axis(
        pd.MultiIndex.from_frame(new_keys), axis=0
    )

    added_index = new_indexed.index.difference(old_indexed.index)
    removed_index = old_indexed.index.difference(new_indexed.index)
    common_index = old_indexed.index.intersection(new_indexed.index)

    value_columns = [
        name
        for name in old.columns
        if name in new.columns and name not in key
    ]

    old_common = old_indexed.loc[common_index, value_columns]
    new_common = new_indexed.loc[common_index, value_columns]

    changed_by_column: dict[str, int] = {}
    any_changed = np.zeros(len(common_index), dtype=bool)
    masks: dict[str, np.ndarray] = {}
    for name in value_columns:
        mask = _values_differ(old_common[name], new_common[name], config)
        masks[name] = mask
        count = int(mask.sum())
        if count:
            changed_by_column[name] = count
        any_changed |= mask

    sample_changed: list[dict[str, Any]] = []
    for position in np.flatnonzero(any_changed)[: config.sample_size]:
        key_values = common_index[position]
        if not isinstance(key_values, tuple):
            key_values = (key_values,)
        sample_changed.append({
            "key": {
                name: _json_value(value)
                for name, value in zip(key, key_values, strict=True)
            },
            "changes": {
                name: [
                    _json_value(old_common[name].iloc[position]),
                    _json_value(new_common[name].iloc[position]),
                ]
                for name in value_columns
                if masks[name][position]
            },
        })

    rows_changed = int(any_changed.sum())

    return RowDiff(
        key=key,
        rows_added=len(added_index),
        rows_removed=len(removed_index),
        rows_changed=rows_changed,
        rows_unchanged=len(common_index) - rows_changed,
        changed_by_column=dict(
            sorted(changed_by_column.items(), key=lambda item: -item[1])
        ),
        duplicate_keys_old=dup_old,
        duplicate_keys_new=dup_new,
        null_keys_old=int(null_old.sum()),
        null_keys_new=int(null_new.sum()),
        sample_added=_records(
            new_indexed.loc[added_index].reset_index(drop=True),
            config.sample_size,
        ),
        sample_removed=_records(
            old_indexed.loc[removed_index].reset_index(drop=True),
            config.sample_size,
        ),
        sample_changed=sample_changed,
    )
