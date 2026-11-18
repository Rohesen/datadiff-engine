"""Segment (subgroup) analysis.

Aggregate checks can miss problems that only affect one subgroup: a 40%
null rate in one country barely moves the overall null rate, and a price
shift in one channel can be cancelled out by the others. This module
repeats the key checks inside each segment and reports changes that are
visible in a segment but hidden in the overall numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ._utils import finite_or_none, is_numeric
from .config import DiffConfig
from .drift import ks_2samp
from .issues import Issue

# At most this many issues of each segment kind are reported, largest first.
MAX_ISSUES_PER_KIND = 25
# A segment change that is also visible overall is still reported when it
# is at least this many times the overall change, i.e. concentrated in
# the segment rather than spread evenly across all of them.
CONCENTRATION_FACTOR = 1.5
NULL_LABEL = "<null>"


@dataclass
class SegmentStats:
    """Row counts of one segment in both datasets."""

    label: str
    rows_old: int
    rows_new: int
    share_old: float
    share_new: float

    @property
    def share_change(self) -> float:
        return self.share_new - self.share_old

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment": self.label,
            "rows_old": self.rows_old,
            "rows_new": self.rows_new,
            "share_old": self.share_old,
            "share_new": self.share_new,
            "share_change": self.share_change,
        }


@dataclass
class SegmentDiff:
    """Result of comparing two datasets segment by segment."""

    columns: list[str]
    segments: list[SegmentStats]
    segment_count_old: int
    segment_count_new: int
    truncated: bool = False
    findings: list[Issue] = field(default_factory=list)
    suppressed_findings: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "segment_count_old": self.segment_count_old,
            "segment_count_new": self.segment_count_new,
            "truncated": self.truncated,
            "suppressed_findings": self.suppressed_findings,
            "segments": [segment.to_dict() for segment in self.segments],
        }


def segment_labels(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    """One readable label per row, e.g. ``"country=IN, channel=web"``."""
    label: pd.Series | None = None
    for name in columns:
        values = frame[name].astype(object)
        text = values.where(values.notna(), NULL_LABEL).astype(str)
        part = f"{name}=" + text
        label = part if label is None else label + ", " + part
    if label is None:
        raise ValueError("segment_by needs at least one column")
    return label


def _cap(found: list[tuple[float, Issue]]) -> tuple[list[Issue], int]:
    """Keep the largest findings (by magnitude) up to the per-kind limit."""
    found.sort(key=lambda item: -item[0])
    kept = [issue for _, issue in found[:MAX_ISSUES_PER_KIND]]
    return kept, max(len(found) - MAX_ISSUES_PER_KIND, 0)


def compare_segments(
    old: pd.DataFrame,
    new: pd.DataFrame,
    segment_by: list[str],
    config: DiffConfig,
    aggregate_null_change: dict[str, float],
    aggregate_mean_change: dict[str, float | None],
    aggregate_drift: dict[str, bool] | None = None,
) -> SegmentDiff:
    """Compare segment sizes, null rates and numeric drift per segment.

    ``aggregate_null_change`` (null-rate change) and
    ``aggregate_mean_change`` (relative mean change, %) hold the
    dataset-level results per column; ``aggregate_drift`` says whether a
    column already has a dataset-level drift issue. A segment change is reported when
    it is hidden in the overall numbers, or concentrated in the segment
    (``CONCENTRATION_FACTOR`` times the overall change or more).
    """
    missing = [
        name
        for name in segment_by
        if name not in old.columns or name not in new.columns
    ]
    if missing:
        raise ValueError(
            "Segment column(s) not present in both datasets: "
            + ", ".join(missing)
        )

    old_labels = segment_labels(old, segment_by)
    new_labels = segment_labels(new, segment_by)
    old_counts = old_labels.value_counts()
    new_counts = new_labels.value_counts()

    all_labels = old_counts.index.union(new_counts.index)
    counts = pd.DataFrame({
        "old": old_counts.reindex(all_labels, fill_value=0),
        "new": new_counts.reindex(all_labels, fill_value=0),
    })
    counts["size"] = counts[["old", "new"]].max(axis=1)
    counts = counts.sort_values(["size", "old"], ascending=False)
    truncated = len(counts) > config.max_segments
    counts = counts.head(config.max_segments)

    total_old = max(len(old), 1)
    total_new = max(len(new), 1)
    segments = [
        SegmentStats(
            label=str(label),
            rows_old=int(row["old"]),
            rows_new=int(row["new"]),
            share_old=int(row["old"]) / total_old,
            share_new=int(row["new"]) / total_new,
        )
        for label, row in counts.iterrows()
    ]

    findings: list[Issue] = []
    suppressed = 0

    # --- segment presence and size ---------------------------------------
    missing_found: list[tuple[float, Issue]] = []
    new_found: list[tuple[float, Issue]] = []
    shift_found: list[tuple[float, Issue]] = []
    for seg in segments:
        if (
            seg.rows_new == 0
            and len(new) > 0
            and seg.share_old >= config.min_segment_share
        ):
            missing_found.append((seg.share_old, Issue(
                kind="segment_missing",
                severity="WARNING",
                segment=seg.label,
                message=(
                    f"Segment {seg.label} has no rows now "
                    f"(was {seg.rows_old:,} rows, {seg.share_old:.1%})."
                ),
                details={"rows_old": seg.rows_old,
                         "share_old": seg.share_old},
            )))
        elif (
            seg.rows_old == 0
            and len(old) > 0
            and seg.share_new >= config.min_segment_share
        ):
            new_found.append((seg.share_new, Issue(
                kind="segment_new",
                severity="INFO",
                segment=seg.label,
                message=(
                    f"New segment {seg.label}: {seg.rows_new:,} rows "
                    f"({seg.share_new:.1%})."
                ),
                details={"rows_new": seg.rows_new,
                         "share_new": seg.share_new},
            )))
        elif (
            seg.rows_old > 0
            and seg.rows_new > 0
            and abs(seg.share_change) >= config.segment_share_shift
        ):
            shift_found.append((abs(seg.share_change), Issue(
                kind="segment_share_shift",
                severity="WARNING",
                segment=seg.label,
                message=(
                    f"Segment {seg.label} share moved "
                    f"{seg.share_old:.1%} → {seg.share_new:.1%} of rows."
                ),
                details={"share_old": seg.share_old,
                         "share_new": seg.share_new},
            )))

    for group in (missing_found, new_found, shift_found):
        kept, dropped = _cap(group)
        findings.extend(kept)
        suppressed += dropped

    # --- per-segment column checks ------------------------------------------
    comparable = [
        seg for seg in segments
        if seg.rows_old >= config.min_segment_rows
        and seg.rows_new >= config.min_segment_rows
    ]
    labels = [seg.label for seg in comparable]
    value_columns = [
        name for name in old.columns
        if name in new.columns and name not in segment_by
    ]

    if labels and value_columns:
        old_nulls = old[value_columns].isna().groupby(old_labels).mean()
        new_nulls = new[value_columns].isna().groupby(new_labels).mean()

        null_found: list[tuple[float, Issue]] = []
        for name in value_columns:
            overall = aggregate_null_change.get(name, 0.0)
            for label in labels:
                before = float(old_nulls.at[label, name])
                after = float(new_nulls.at[label, name])
                change = after - before
                if change >= config.critical_null_rate:
                    severity = "CRITICAL"
                elif change >= config.warning_null_rate:
                    severity = "WARNING"
                else:
                    continue
                if overall < config.warning_null_rate:
                    note = "hidden in the overall null rate"
                elif change >= CONCENTRATION_FACTOR * overall:
                    note = f"concentrated here; overall +{overall:.1%}"
                else:
                    continue  # spread evenly; the overall issue covers it
                null_found.append((change, Issue(
                    kind="segment_null_rate_increase",
                    severity=severity,
                    column=name,
                    segment=label,
                    message=(
                        f"Null rate in '{name}' for {label} rose "
                        f"{before:.1%} → {after:.1%} ({note})."
                    ),
                    details={"null_rate_old": before,
                             "null_rate_new": after},
                )))
        kept, dropped = _cap(null_found)
        findings.extend(kept)
        suppressed += dropped

        numeric_columns = [
            name for name in value_columns
            if name not in config.ignored_columns
            and is_numeric(old[name]) and is_numeric(new[name])
        ]
        drift_found: list[tuple[float, Issue]] = []
        old_groups = old.groupby(old_labels)
        new_groups = new.groupby(new_labels)
        for name in numeric_columns:
            overall_pct = aggregate_mean_change.get(name)
            for label in labels:
                a = old_groups.get_group(label)[name].dropna()
                b = new_groups.get_group(label)[name].dropna()
                if (
                    len(a) < config.min_segment_rows
                    or len(b) < config.min_segment_rows
                ):
                    continue
                with np.errstate(invalid="ignore", over="ignore"):
                    mean_old = float(a.mean())
                    mean_new = float(b.mean())
                if (
                    mean_old == 0
                    or not np.isfinite(mean_old)
                    or not np.isfinite(mean_new)
                ):
                    continue
                change_pct = (mean_new - mean_old) / abs(mean_old) * 100
                if abs(change_pct) < config.drift_threshold_pct:
                    continue
                if not (aggregate_drift or {}).get(name, False):
                    note = "hidden in the overall numbers"
                elif overall_pct is None or not np.isfinite(overall_pct):
                    continue
                elif abs(change_pct) >= CONCENTRATION_FACTOR * abs(overall_pct):
                    note = f"concentrated here; overall mean {overall_pct:+.1f}%"
                else:
                    continue  # spread evenly; the overall issue covers it
                details: dict[str, Any] = {
                    "mean_old": finite_or_none(mean_old),
                    "mean_new": finite_or_none(mean_new),
                    "mean_change_pct": finite_or_none(change_pct),
                }
                if config.statistical_tests:
                    statistic, p_value = ks_2samp(
                        a.to_numpy(dtype=float), b.to_numpy(dtype=float)
                    )
                    if p_value >= config.ks_alpha:
                        continue  # not distinguishable from noise
                    details["ks_statistic"] = statistic
                    details["ks_p_value"] = p_value
                drift_found.append((abs(change_pct), Issue(
                    kind="segment_drift",
                    severity="WARNING",
                    column=name,
                    segment=label,
                    message=(
                        f"Mean of '{name}' for {label} moved "
                        f"{mean_old:,.2f} → {mean_new:,.2f} "
                        f"({change_pct:+.1f}%; {note})."
                    ),
                    details=details,
                )))
        kept, dropped = _cap(drift_found)
        findings.extend(kept)
        suppressed += dropped

    return SegmentDiff(
        columns=segment_by,
        segments=segments,
        segment_count_old=int(old_counts.size),
        segment_count_new=int(new_counts.size),
        truncated=truncated,
        findings=findings,
        suppressed_findings=suppressed,
    )


__all__ = [
    "SegmentDiff",
    "SegmentStats",
    "compare_segments",
    "segment_labels",
]
