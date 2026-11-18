# Changelog

## 0.3.0

Backward compatible: all existing code, issue kinds and the 0.2 test suite keep working. Every new check has a default and can be configured or turned off.

### Added
- **Statistical drift** (`distribution_drift` issue, `ColumnDiff.distribution`): PSI and the two-sample Kolmogorov–Smirnov test for numeric columns, and PSI and Jensen–Shannon distance for categorical columns. Implemented with NumPy only and checked against SciPy in the tests. Configured by `statistical_tests`, `min_rows_for_tests`, `psi_warning`, `psi_critical`, `psi_bins` and `ks_alpha`.
- **Key-based row diff** (`compare(..., key=...)`, `DatasetDiff.row_diff`): added, removed, changed and unchanged rows, changed-row counts per column, samples of each, numeric tolerances, and `duplicate_keys`, `null_keys`, `rows_added`, `rows_removed` and `rows_changed` issues.
- **Segment analysis** (`compare(..., segment_by=...)`, `DatasetDiff.segment_diff`): the checks are repeated inside each subgroup, and changes hidden in or concentrated beyond the overall numbers are reported, via `segment_missing`, `segment_new`, `segment_share_shift`, `segment_null_rate_increase` and `segment_drift`.
- **Datetime profiling** (`DatetimeStats`, `ColumnDiff.old_datetime_stats` / `new_datetime_stats`) and a **freshness check** (`freshness_columns`, `stale_data` issue).
- **Reports**: `DatasetDiff.to_markdown()`, `DatasetDiff.to_html()` (self-contained, escaped, no scripts) and coloured terminal output with Rich.
- **More input types**: Polars DataFrames and LazyFrames, DuckDB relations and PyArrow tables, as well as pandas.
- **CLI**: `--format {text,json,markdown,html,rich}`, `-o/--output`, `--key`, `--segment-by`, `--freshness-column`, `--no-stats`, PSI and row-diff thresholds, tolerances, `--duckdb DATABASE` (tables or `SELECT` queries, opened read-only and sandboxed), `--config FILE` (TOML, `[datadiff]` or `[tool.datadiff]`), `--version`, and support for `.tsv`, `.json`, `.jsonl` and `.feather` files.
- `ISSUE_KINDS`: every issue kind with a description. `Issue.segment` and `Issue.details` (measured values for machines).
- `DiffConfig.from_dict()` / `to_dict()`. Unknown keys are rejected. Column-set options accept lists and sets.
- `schema_version` and the effective `config` in `to_dict()` output.
- Optional extras: `parquet`, `polars`, `duckdb`, `rich`, `all`.
- Type hints throughout, and a `py.typed` marker.
- `SECURITY.md`; Bandit, pip-audit, Ruff, mypy and a 90% coverage minimum in CI; a test job on the oldest supported pandas (2.0); Dependabot.

### Changed
- The code is split into focused modules (`config`, `stats`, `drift`, `rows`, `segments`, `issues`, `report`). Everything stays importable from `datadiff_engine` and from `datadiff_engine.compare` as before.
- CLI error messages go to standard error, so standard output only ever holds the report.
- Statistical drift tests treat boolean columns as categories.

### Security
- The `parquet` and `polars` extras require `pyarrow >= 14.0.1` (CVE-2023-47248).
- GitHub Actions workflows use least-privilege permissions and do not persist credentials.

## 0.2.2

- Replaced the Mermaid flowchart in the README with an image: PyPI does not render Mermaid, so it showed the raw diagram code. The diagram now also reflects 0.2 (issues list and overall severity).

## 0.2.1

- Fixed the README image and license link on PyPI: they used repository-relative paths, which PyPI cannot resolve. They now use absolute URLs.
- Updated the CLI demo screenshot to show 0.2 output (overall severity and issues list).

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
