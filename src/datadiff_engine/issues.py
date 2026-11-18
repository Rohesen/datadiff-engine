"""The ``Issue`` type: one notable change found in a comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Every issue kind the library can produce, with a one-line description.
# Kinds are a stable public contract: new kinds may be added in minor
# releases, existing kinds are never renamed.
ISSUE_KINDS: dict[str, str] = {
    "empty_dataset": "The new dataset has no rows while the old one had some.",
    "row_count_change": "Row count moved past the configured percentage.",
    "column_removed": "A column disappeared.",
    "column_added": "A new column appeared.",
    "type_changed": "A column's data type changed.",
    "null_rate_increase": "A column's null rate rose past the thresholds.",
    "new_category_values": "A low-cardinality column has never-seen values.",
    "numeric_drift": "Mean, median or p95 moved past the drift threshold.",
    "distribution_drift": "PSI / KS / Jensen-Shannon detected a shift in "
    "a column's distribution.",
    "stale_data": "The latest timestamp in a freshness column did not "
    "move forward.",
    "duplicate_keys": "Key columns are not unique.",
    "null_keys": "Key columns contain missing values.",
    "rows_added": "Rows whose key is new.",
    "rows_removed": "Rows whose key disappeared.",
    "rows_changed": "Rows with the same key but different values.",
    "segment_missing": "A segment present before has no rows now.",
    "segment_new": "A segment appeared that did not exist before.",
    "segment_share_shift": "A segment's share of rows moved significantly.",
    "segment_null_rate_increase": "Null rate rose inside a segment, hidden "
    "in the overall numbers.",
    "segment_drift": "A numeric column drifted inside a segment, hidden in "
    "the overall numbers.",
}


@dataclass(frozen=True)
class Issue:
    """One notable change found in a dataset comparison.

    Issues are designed to be read by people, CI checks and automated
    agents: each has a stable ``kind``, the affected ``column`` (or None
    for dataset-level issues), a ``severity`` and a readable ``message``.
    ``segment`` names the subgroup for segment-level issues and ``details``
    carries the measured values for machines.
    """

    kind: str
    severity: str
    message: str
    column: str | None = None
    segment: str | None = None
    details: dict[str, Any] = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return the issue as a JSON-friendly dictionary."""
        result: dict[str, Any] = {
            "kind": self.kind,
            "severity": self.severity,
            "column": self.column,
            "message": self.message,
        }
        if self.segment is not None:
            result["segment"] = self.segment
        if self.details:
            result["details"] = self.details
        return result
