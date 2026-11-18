"""Configuration for dataset comparison."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True)
class DiffConfig:
    """Thresholds and switches for a dataset comparison.

    Every field has a sensible default, so ``DiffConfig()`` works out of the
    box. Percentages (``*_pct``) are on a 0-100 scale; rates and shares
    (``*_rate``, ``*_share``) are on a 0-1 scale.
    """

    # --- null rates -------------------------------------------------------
    warning_null_rate: float = 0.05
    critical_null_rate: float = 0.20

    # --- columns excluded from drift analysis (IDs, hashes, ...) ----------
    ignored_columns: frozenset[str] = frozenset()

    # --- summary-statistic drift heuristic (mean / median / p95) ----------
    drift_threshold_pct: float = 20.0

    # --- row counts -------------------------------------------------------
    warning_row_change_pct: float = 20.0
    critical_row_change_pct: float = 50.0

    # --- new categorical values -------------------------------------------
    # New category values are only checked on low-cardinality columns
    # (status codes, currencies, channels), not on free text or IDs.
    max_categories_for_new_value_check: int = 50
    new_value_min_share: float = 0.01

    # --- statistical distribution drift (PSI, KS, Jensen-Shannon) ---------
    statistical_tests: bool = True
    # Both datasets need at least this many non-null values in a column.
    min_rows_for_tests: int = 50
    # Industry convention: PSI < 0.1 stable, 0.1-0.25 moderate, > 0.25 major.
    psi_warning: float = 0.10
    psi_critical: float = 0.25
    psi_bins: int = 10
    # Numeric drift is only reported when the KS test is also significant,
    # which suppresses noise from small samples.
    ks_alpha: float = 0.01

    # --- key-based row comparison (``compare(..., key=...)``) --------------
    warning_changed_rows_pct: float = 1.0
    critical_changed_rows_pct: float = 10.0
    numeric_abs_tolerance: float = 0.0
    numeric_rel_tolerance: float = 0.0
    sample_size: int = 5

    # --- segment (subgroup) analysis (``compare(..., segment_by=...)``) ---
    max_segments: int = 100
    min_segment_rows: int = 30
    min_segment_share: float = 0.01
    segment_share_shift: float = 0.05

    # --- freshness --------------------------------------------------------
    # Event-time columns whose latest value is expected to move forward.
    freshness_columns: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        # Accept any iterable (list, set) for the column-set fields.
        for name in ("ignored_columns", "freshness_columns"):
            value = getattr(self, name)
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, frozenset):
                object.__setattr__(self, name, frozenset(value))

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

        if self.min_rows_for_tests < 2:
            raise ValueError("min_rows_for_tests must be >= 2")

        if self.psi_warning <= 0:
            raise ValueError("psi_warning must be > 0")

        if self.psi_critical < self.psi_warning:
            raise ValueError("psi_critical must be >= psi_warning")

        if self.psi_bins < 2:
            raise ValueError("psi_bins must be >= 2")

        if not 0 < self.ks_alpha < 1:
            raise ValueError("ks_alpha must be between 0 and 1")

        if self.warning_changed_rows_pct < 0:
            raise ValueError("warning_changed_rows_pct must be >= 0")

        if self.critical_changed_rows_pct < self.warning_changed_rows_pct:
            raise ValueError(
                "critical_changed_rows_pct must be >= warning_changed_rows_pct"
            )

        if self.numeric_abs_tolerance < 0 or self.numeric_rel_tolerance < 0:
            raise ValueError("numeric tolerances must be >= 0")

        if self.sample_size < 0:
            raise ValueError("sample_size must be >= 0")

        if self.max_segments < 1:
            raise ValueError("max_segments must be >= 1")

        if self.min_segment_rows < 1:
            raise ValueError("min_segment_rows must be >= 1")

        if not 0 <= self.min_segment_share <= 1:
            raise ValueError("min_segment_share must be between 0 and 1")

        if not 0 < self.segment_share_shift <= 1:
            raise ValueError("segment_share_shift must be between 0 and 1")

    @classmethod
    def field_names(cls) -> set[str]:
        return {f.name for f in fields(cls)}

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> DiffConfig:
        """Build a config from a plain dictionary (e.g. a TOML table).

        Unknown keys raise ``ValueError`` so typos are not silently ignored.
        """
        unknown = set(values) - cls.field_names()
        if unknown:
            raise ValueError(
                "Unknown config option(s): " + ", ".join(sorted(unknown))
            )
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        """Return the config as a JSON-friendly dictionary."""
        result: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, frozenset):
                value = sorted(value)
            result[f.name] = value
        return result
