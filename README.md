# datadiff-engine

[![PyPI](https://img.shields.io/pypi/v/datadiff-engine.svg)](https://pypi.org/project/datadiff-engine/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Tests](https://github.com/Rohesen/datadiff-engine/actions/workflows/tests.yml/badge.svg)](https://github.com/Rohesen/datadiff-engine/actions/workflows/tests.yml)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE.txt)

A Python library and CLI for **comparing datasets, detecting schema changes, profiling columns, and identifying simple numeric data drift**.

Built for data engineers who want a quick answer to:

> **What changed between yesterday's dataset and today's dataset?**

---

## Why datadiff-engine?

Data pipelines frequently produce datasets that look valid but have unexpected changes:

- Row counts suddenly increase or decrease
- Columns are added or removed
- Data types change
- Null rates increase
- Unique values change
- Numeric distributions shift

`datadiff-engine` provides a structured comparison so these changes can be inspected programmatically or directly from the command line.

---

## Features

- Compare row counts
- Detect added columns
- Detect removed columns
- Detect data-type changes
- Compare null rates
- Compare unique-value counts
- Generate numeric statistics
- Detect simple numeric drift
- Analyze categorical columns
- Configure null-rate severity thresholds
- Ignore selected columns for numeric drift analysis
- Python API
- Command-line interface
- JSON output
- CSV support
- Parquet support

---

## Installation

```bash
pip install datadiff-engine
```

---

## Python usage

```python
import pandas as pd

from datadiff_engine import compare

old = pd.DataFrame({
    "customer_id": [1, 2, 3],
    "amount": [100, 200, 300],
})

new = pd.DataFrame({
    "customer_id": [1, 2, 3, 4],
    "amount": [100, 200, None, 500],
    "country": ["IN", "IN", "US", "IN"],
})

diff = compare(old, new)

print(diff)
```

Example output:

```text
DATASET DIFF
========================================

ROWS
  3 → 4
  Change: +1 (+33.33%)

SCHEMA
  + Added:   ['country']
  - Removed: none
  ~ Changed: amount (int64 → float64)

COLUMN CHANGES
----------------------------------------
amount
  Data type: int64 → float64
  Null rate: 0.00% → 25.00% (+25.00 pp)
  Severity:  CRITICAL

  Statistics
    Mean:    200.00 → 266.67
    Median:  200.00 → 200.00
    Min:     100.00 → 100.00
    Max:     300.00 → 500.00
    P95:     290.00 → 470.00
```

---

## Column-level analysis

Access details for an individual column:

```python
amount = diff.column("amount")

print(amount.name)
print(amount.old_dtype)
print(amount.new_dtype)

print(amount.null_rate_old)
print(amount.null_rate_new)
print(amount.null_rate_change)

print(amount.severity)
```

For numeric columns, statistics are available:

```python
print(amount.old_stats.mean)
print(amount.new_stats.mean)

print(amount.old_stats.median)
print(amount.new_stats.median)

print(amount.old_stats.min)
print(amount.new_stats.max)

print(amount.old_stats.p95)
print(amount.new_stats.p95)
```

Numeric drift information is also available:

```python
if amount.drift:
    print(amount.drift.mean_change_pct)
    print(amount.drift.median_change_pct)
    print(amount.drift.p95_change_pct)
    print(amount.drift.has_drift)
```

---

## Custom severity thresholds

The default null-rate thresholds can be customized:

```python
from datadiff_engine import DiffConfig, compare

config = DiffConfig(
    warning_null_rate=0.10,
    critical_null_rate=0.50,
)

diff = compare(
    old,
    new,
    config=config,
)
```

This allows different projects or pipelines to define their own thresholds.

---

## Ignoring columns for numeric drift

Some numeric columns represent identifiers rather than measurements.

For example:

```text
customer_id
order_id
account_id
```

These columns may not be appropriate for numeric drift analysis.

You can exclude them:

```python
from datadiff_engine import DiffConfig, compare

config = DiffConfig(
    ignored_columns={"customer_id"},
)

diff = compare(
    old,
    new,
    config=config,
)
```

The column is still part of the comparison, but numeric drift analysis is skipped for the ignored column.

---

## JSON output

The comparison can be converted into a machine-readable dictionary:

```python
result = diff.to_dict()

print(result)
```

This is useful when integrating the library into:

- Data pipelines
- Airflow tasks
- CI/CD pipelines
- Logging systems
- APIs
- Monitoring tools

Example:

```python
{
    "rows": {
        "old": 3,
        "new": 4,
        "change": 1,
        "change_pct": 33.33
    },
    "schema": {
        "added": ["country"],
        "removed": [],
        "changed_types": {
            "amount": ["int64", "float64"]
        }
    }
}
```

---

## Command-line interface

`datadiff-engine` also provides a CLI.

Compare two CSV files:

```bash
datadiff old.csv new.csv
```

Compare Parquet files:

```bash
datadiff old.parquet new.parquet
```

Output JSON:

```bash
datadiff old.csv new.csv --json
```

Ignore columns for numeric drift:

```bash
datadiff old.csv new.csv --ignore customer_id
```

Show help:

```bash
datadiff --help
```

---

## Example

Suppose yesterday's dataset contains:

```csv
customer_id,amount,country
1,100,IN
2,200,IN
3,300,US
```

and today's dataset contains:

```csv
customer_id,amount,country
1,100,IN
2,200,US
3,,US
4,500,BD
```

Running:

```bash
datadiff old.csv new.csv
```

can identify:

```text
Rows: 3 → 4

amount
  Data type: int64 → float64
  Null rate: 0.00% → 25.00%

country
  Unique values: 2 → 3

customer_id
  Unique values: 3 → 4
```

---

## Drift methodology

The current release uses a **lightweight heuristic** for numeric drift.

It compares relative changes in selected summary statistics:

- Mean
- Median
- P95

A configurable percentage threshold is then used to determine whether the tracked statistics changed beyond the configured level.

This is intentionally simple and lightweight.

It is **not intended to replace formal statistical distribution-drift tests**.

---

## Supported input formats

### Python API

```text
pandas.DataFrame
```

### CLI

```text
CSV
Parquet
```

---

## Development

Clone the repository:

```bash
git clone https://github.com/rohesen/datadiff-engine.git
cd datadiff-engine
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.venv\Scripts\activate
```

Install the project with development dependencies:

```bash
pip install -e ".[dev]"
```

Run the test suite:

```bash
pytest
```

Expected result for the current development checkpoint:

```text
14 passed
```

---

## Building the package

Install the build tools:

```bash
pip install build twine
```

Build the package:

```bash
python -m build
```

This creates distribution files inside:

```text
dist/
```

Validate them:

```bash
python -m twine check dist/*
```

---

## Project structure

```text
datadiff-engine/
│
├── src/
│   └── datadiff_engine/
│       ├── __init__.py
│       ├── compare.py
│       └── cli.py
│
├── tests/
│   └── test_compare.py
│
├── demo.py
├── README.md
├── LICENSE
├── pyproject.toml
└── .gitignore
```

---

## Roadmap

Future versions may include:

- More advanced statistical drift methods
- Better categorical drift analysis
- Datetime-aware profiling
- Polars support
- DuckDB integration
- Rich terminal output
- Markdown reports
- Additional CI/CD integrations
- More configurable analysis rules

---

## Contributing

Contributions, ideas, bug reports, and improvements are welcome.

Before submitting a change, please run:

```bash
pytest
```

---

## License

MIT License.

See [LICENSE](LICENSE.txt) for details.

---

## Author

**Rohesen Rajkamal Maurya**

Built as an open-source data-engineering utility for comparing datasets and understanding changes in pipeline outputs.
