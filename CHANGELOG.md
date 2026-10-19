# Changelog

## 0.2.0

Backward compatible: existing code and the 0.1.0 test suite keep working.

### Added
- `DatasetDiff.issues()`: a list of `Issue` objects (`kind`, `severity`, `column`, `message`), most severe first. Covers empty datasets, row-count changes, removed/added columns, type changes, null-rate increases and numeric drift.
- `DatasetDiff.overall_severity`: the highest severity among all issues.
- `summary` block at the top of `to_dict()` output, and an "OVERALL SEVERITY" section at the top of the text report.
- `DiffConfig.drift_threshold_pct` (default 20.0): numeric drift threshold, previously fixed at 20%.
- `DiffConfig.warning_row_change_pct` / `critical_row_change_pct` (defaults 20 / 50): row-count change thresholds.
- `new_category_values` issue: values in a low-cardinality text column (e.g. currency `OMR` → `USD`, a new status code) that never appeared in the old dataset. Configured by `max_categories_for_new_value_check` (default 50) and `new_value_min_share` (default 1%). Exposed as `DatasetDiff.new_category_values`. Columns holding dates as text (e.g. `2026-10-02`) are skipped, since they get new values every day.
- `NumericDrift.from_zero_baseline`: true when a statistic moved away from zero, where a percentage change is infinite.
- CLI: `--fail-on {warning,critical}` quality gate (exit code 1), threshold options (`--warning-null-rate`, `--critical-null-rate`, `--drift-threshold`, `--warning-row-change`, `--critical-row-change`), and exit code 2 with a clear message for bad input.
- `datadiff_engine.__version__`.

### Changed
- An int → float type change that only happens because the new data has missing values (pandas stores such columns as float64) is reported as an INFO issue with an explanation, not a WARNING.

### Fixed
- `to_dict()` could contain `Infinity` (drift from a zero baseline) or `NaN` (statistics of an all-null column), which is not valid JSON. These are now reported as `null`, and the CLI emits strict JSON.

## 0.1.0

- Initial release: row, schema, null-rate and unique-value comparison; numeric statistics and drift heuristic; categorical statistics; configurable null-rate severity; JSON output; CLI for CSV and Parquet.
