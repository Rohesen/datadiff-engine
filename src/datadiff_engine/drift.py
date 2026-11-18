"""Drift measures: a summary-statistic heuristic and statistical tests.

The statistical measures are implemented with NumPy only (no SciPy
dependency) and are validated against SciPy in the test suite:

- Population Stability Index (PSI), the standard drift score in credit
  risk and ML monitoring.
- Two-sample Kolmogorov-Smirnov (KS) statistic and asymptotic p-value,
  for numeric columns.
- Jensen-Shannon distance (base 2, between 0 and 1), for categorical
  columns.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from ._utils import finite_or_none

if TYPE_CHECKING:
    from .config import DiffConfig
    from .stats import NumericStats

# Proportions of zero make PSI infinite; this floor is the usual fix.
_PSI_EPSILON = 1e-4


# ---------------------------------------------------------------------------
# Summary-statistic heuristic (unchanged since 0.1)
# ---------------------------------------------------------------------------


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
    ) -> NumericDrift:
        """Calculate drift from two numeric-stat summaries."""
        return cls(
            mean_change_pct=cls._relative_change_pct(old.mean, new.mean),
            median_change_pct=cls._relative_change_pct(
                old.median, new.median
            ),
            p95_change_pct=cls._relative_change_pct(old.p95, new.p95),
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

    def to_dict(self) -> dict[str, Any]:
        """Return drift information as a JSON-friendly dictionary.

        Infinite changes (from a zero baseline) are reported as None,
        with ``from_zero_baseline`` set to True.
        """
        return {
            "mean_change_pct": finite_or_none(self.mean_change_pct),
            "median_change_pct": finite_or_none(self.median_change_pct),
            "p95_change_pct": finite_or_none(self.p95_change_pct),
            "threshold_pct": self.threshold_pct,
            "has_drift": self.has_drift,
            "from_zero_baseline": self.from_zero_baseline,
        }


# ---------------------------------------------------------------------------
# Statistical measures
# ---------------------------------------------------------------------------


def psi_from_proportions(
    expected: np.ndarray, actual: np.ndarray
) -> float:
    """Population Stability Index between two aligned proportion vectors."""
    expected = np.clip(np.asarray(expected, dtype=float), _PSI_EPSILON, None)
    actual = np.clip(np.asarray(actual, dtype=float), _PSI_EPSILON, None)
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def numeric_psi(old: np.ndarray, new: np.ndarray, bins: int = 10) -> float:
    """PSI for numeric values, using quantile bins of the old data.

    Columns with few distinct values (flags, ratings, small counts) are
    compared value by value instead, since quantile bins would collapse.
    """
    old = np.asarray(old, dtype=float)
    new = np.asarray(new, dtype=float)

    distinct = np.unique(np.concatenate([old, new]))
    if distinct.size <= bins:
        return categorical_psi(pd.Series(old), pd.Series(new))

    finite_old = old[np.isfinite(old)]
    if finite_old.size == 0:
        return categorical_psi(pd.Series(old), pd.Series(new))
    edges = np.unique(np.quantile(finite_old, np.linspace(0, 1, bins + 1)))
    # Open-ended outer bins so new values outside the old range are counted.
    edges = np.concatenate([[-np.inf], edges[1:-1], [np.inf]])
    expected = np.histogram(old, edges)[0] / old.size
    actual = np.histogram(new, edges)[0] / new.size
    return psi_from_proportions(expected, actual)


def _aligned_proportions(
    old: pd.Series, new: pd.Series
) -> tuple[np.ndarray, np.ndarray]:
    old_share = old.astype(str).value_counts(normalize=True)
    new_share = new.astype(str).value_counts(normalize=True)
    categories = old_share.index.union(new_share.index)
    return (
        old_share.reindex(categories, fill_value=0.0).to_numpy(dtype=float),
        new_share.reindex(categories, fill_value=0.0).to_numpy(dtype=float),
    )


def categorical_psi(old: pd.Series, new: pd.Series) -> float:
    """PSI over the categories of two columns (null values excluded)."""
    expected, actual = _aligned_proportions(old.dropna(), new.dropna())
    return psi_from_proportions(expected, actual)


def jensen_shannon_distance(old: pd.Series, new: pd.Series) -> float:
    """Jensen-Shannon distance (base 2): 0 = identical, 1 = disjoint."""
    p, q = _aligned_proportions(old.dropna(), new.dropna())
    m = (p + q) / 2

    def _kl(a: np.ndarray, b: np.ndarray) -> float:
        mask = a > 0
        return float(np.sum(a[mask] * np.log2(a[mask] / b[mask])))

    divergence = (_kl(p, m) + _kl(q, m)) / 2
    return float(math.sqrt(max(divergence, 0.0)))


def ks_2samp(old: np.ndarray, new: np.ndarray) -> tuple[float, float]:
    """Two-sample Kolmogorov-Smirnov test (two-sided, asymptotic).

    Returns ``(statistic, p_value)``. The statistic is the largest gap
    between the two empirical CDFs (identical to SciPy). The p-value uses
    the asymptotic Kolmogorov distribution with Stephens' correction,
    which is accurate for the sample sizes this library tests (see
    ``DiffConfig.min_rows_for_tests``).
    """
    a = np.sort(np.asarray(old, dtype=float))
    b = np.sort(np.asarray(new, dtype=float))
    n, m = a.size, b.size
    if n == 0 or m == 0:
        return 0.0, 1.0

    points = np.concatenate([a, b])
    cdf_a = np.searchsorted(a, points, side="right") / n
    cdf_b = np.searchsorted(b, points, side="right") / m
    statistic = float(np.max(np.abs(cdf_a - cdf_b)))

    # Stephens' small-sample correction to the asymptotic distribution
    # (as in Numerical Recipes); within a few percent of SciPy's p-value.
    root_n = math.sqrt(n * m / (n + m))
    p_value = _kolmogorov_sf((root_n + 0.12 + 0.11 / root_n) * statistic)
    return statistic, p_value


def _kolmogorov_sf(x: float) -> float:
    """Survival function of the Kolmogorov distribution."""
    if x <= 0:
        return 1.0
    if x < 0.2:
        # The series converges slowly here and the value is ~1.
        return 1.0
    total = 0.0
    for k in range(1, 101):
        term = 2 * (-1) ** (k - 1) * math.exp(-2 * k * k * x * x)
        total += term
        if abs(term) < 1e-12:
            break
    return float(min(max(total, 0.0), 1.0))


@dataclass
class DistributionDrift:
    """Statistical distribution drift for one column.

    ``method`` is ``"numeric"`` (PSI + Kolmogorov-Smirnov) or
    ``"categorical"`` (PSI + Jensen-Shannon distance).
    """

    method: str
    psi: float
    ks_statistic: float | None = None
    ks_p_value: float | None = None
    js_distance: float | None = None
    severity: str | None = None

    @property
    def has_drift(self) -> bool:
        return self.severity is not None

    @classmethod
    def numeric(
        cls, old: pd.Series, new: pd.Series, config: DiffConfig
    ) -> DistributionDrift:
        old_values = old.dropna().to_numpy(dtype=float)
        new_values = new.dropna().to_numpy(dtype=float)
        psi = numeric_psi(old_values, new_values, bins=config.psi_bins)
        statistic, p_value = ks_2samp(old_values, new_values)

        severity = None
        if p_value < config.ks_alpha:
            severity = _psi_severity(psi, config)
        return cls(
            method="numeric",
            psi=psi,
            ks_statistic=statistic,
            ks_p_value=p_value,
            severity=severity,
        )

    @classmethod
    def categorical(
        cls, old: pd.Series, new: pd.Series, config: DiffConfig
    ) -> DistributionDrift:
        psi = categorical_psi(old, new)
        return cls(
            method="categorical",
            psi=psi,
            js_distance=jensen_shannon_distance(old, new),
            severity=_psi_severity(psi, config),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "psi": finite_or_none(self.psi),
            "ks_statistic": finite_or_none(self.ks_statistic),
            "ks_p_value": finite_or_none(self.ks_p_value),
            "js_distance": finite_or_none(self.js_distance),
            "has_drift": self.has_drift,
            "severity": self.severity,
        }


def _psi_severity(psi: float, config: DiffConfig) -> str | None:
    if psi >= config.psi_critical:
        return "CRITICAL"
    if psi >= config.psi_warning:
        return "WARNING"
    return None
