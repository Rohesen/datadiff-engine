"""Command-line interface: ``datadiff OLD NEW [options]``."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from . import __version__
from . import report as _report
from ._utils import SEVERITY_ORDER
from .compare import DatasetDiff, compare
from .config import DiffConfig

# Exit codes
EXIT_OK = 0
EXIT_THRESHOLD = 1  # --fail-on threshold reached
EXIT_ERROR = 2      # bad input (missing file, unsupported type, ...)

FORMATS = ("text", "json", "markdown", "html", "rich")

# CLI option name -> DiffConfig field, for options that map one-to-one.
_THRESHOLD_OPTIONS = {
    "warning_null_rate": "warning_null_rate",
    "critical_null_rate": "critical_null_rate",
    "drift_threshold": "drift_threshold_pct",
    "warning_row_change": "warning_row_change_pct",
    "critical_row_change": "critical_row_change_pct",
    "psi_warning": "psi_warning",
    "psi_critical": "psi_critical",
    "warning_changed_rows": "warning_changed_rows_pct",
    "critical_changed_rows": "critical_changed_rows_pct",
    "abs_tolerance": "numeric_abs_tolerance",
    "rel_tolerance": "numeric_rel_tolerance",
}

# Settings a config file may hold besides DiffConfig fields.
_RUN_SETTINGS = {"key", "segment_by", "fail_on", "format"}

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$")


# ---------------------------------------------------------------------------
# Loading data
# ---------------------------------------------------------------------------


def load_dataframe(path: str) -> pd.DataFrame:
    """Load a CSV, TSV, Parquet, JSON, JSON Lines or Feather file."""
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    if not file_path.is_file():
        raise ValueError(f"Not a file: {path}")

    suffix = file_path.suffix.lower()

    if suffix == ".csv":
        return pd.read_csv(file_path)

    if suffix == ".tsv":
        return pd.read_csv(file_path, sep="\t")

    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(file_path)

    if suffix in {".jsonl", ".ndjson"}:
        return pd.read_json(file_path, lines=True)

    if suffix == ".json":
        return pd.read_json(file_path)

    if suffix in {".feather", ".arrow"}:
        return pd.read_feather(file_path)

    raise ValueError(
        f"Unsupported file type: {suffix}. "
        "Use .csv, .tsv, .parquet, .json, .jsonl or .feather."
    )


def load_duckdb(database: str, source: str) -> pd.DataFrame:
    """Read a table name or a SELECT query from a DuckDB database.

    The database is opened read-only, with access to external files and
    the network disabled, so a query can only read what is inside it.
    """
    try:
        import duckdb
    except ImportError as error:
        raise ValueError(
            "DuckDB support needs the 'duckdb' package: "
            "pip install 'datadiff-engine[duckdb]'"
        ) from error

    if database != ":memory:" and not Path(database).is_file():
        raise FileNotFoundError(f"DuckDB database not found: {database}")

    source = source.strip()
    is_table = bool(_IDENTIFIER.match(source))
    if not is_table and not re.match(r"^(select|with|from)\b", source, re.IGNORECASE):
        raise ValueError(
            "With --duckdb, OLD and NEW must be table names or SELECT queries."
        )

    connection = duckdb.connect(
        database,
        read_only=database != ":memory:",
        config={"enable_external_access": False},
    )
    try:
        connection.execute("SET lock_configuration = true")
        if is_table:
            # Relation API: the name is never spliced into SQL text.
            return connection.table(source).df()
        return connection.execute(source).df()
    except duckdb.Error as error:
        raise ValueError(f"DuckDB error: {error}") from error
    finally:
        connection.close()


def load_config_file(path: str) -> dict[str, Any]:
    """Read settings from a TOML file.

    Settings may live at the top level, in a ``[datadiff]`` table, or in
    ``[tool.datadiff]`` (so they can sit in ``pyproject.toml``).
    """
    if sys.version_info >= (3, 11):
        import tomllib
    else:  # pragma: no cover - Python 3.10
        import tomli as tomllib

    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")

    try:
        with file_path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"Invalid TOML in {path}: {error}") from error

    if isinstance(data.get("tool"), dict) and "datadiff" in data["tool"]:
        data = data["tool"]["datadiff"]
    elif "datadiff" in data:
        data = data["datadiff"]

    if not isinstance(data, dict):
        raise ValueError(f"{path}: settings must be a table")

    allowed = DiffConfig.field_names() | _RUN_SETTINGS
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(
            f"{path}: unknown setting(s): " + ", ".join(sorted(unknown))
        )
    return dict(data)


# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="datadiff",
        description="Compare two datasets and report what changed.",
    )

    parser.add_argument("old", help="Old/baseline dataset (file, or table/query with --duckdb).")
    parser.add_argument("new", help="New/current dataset (file, or table/query with --duckdb).")

    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    out = parser.add_argument_group("output")
    out.add_argument(
        "--format", choices=FORMATS, default=None,
        help="Report format (default: text).",
    )
    out.add_argument(
        "--json", action="store_true",
        help="Output the report as JSON (same as --format json).",
    )
    out.add_argument(
        "-o", "--output", metavar="PATH",
        help="Write the report to a file instead of standard output.",
    )

    analysis = parser.add_argument_group("analysis")
    analysis.add_argument(
        "--key", nargs="+", metavar="COL",
        help="Key column(s) for a row-level diff (added/removed/changed rows).",
    )
    analysis.add_argument(
        "--segment-by", nargs="+", metavar="COL",
        help="Column(s) to segment by; reports changes hidden in subgroups.",
    )
    analysis.add_argument(
        "--freshness-column", nargs="+", metavar="COL", default=None,
        help="Timestamp column(s) whose latest value must move forward.",
    )
    analysis.add_argument(
        "--ignore", nargs="*", default=None, metavar="COL",
        help="Columns to exclude from drift analysis (IDs, hashes, ...).",
    )
    analysis.add_argument(
        "--no-stats", action="store_true",
        help="Skip statistical drift tests (PSI, KS, Jensen-Shannon).",
    )

    th = parser.add_argument_group("thresholds")
    th.add_argument("--warning-null-rate", type=float,
                    help="Null-rate increase that counts as WARNING (default 0.05).")
    th.add_argument("--critical-null-rate", type=float,
                    help="Null-rate increase that counts as CRITICAL (default 0.20).")
    th.add_argument("--drift-threshold", type=float,
                    help="Percent change in mean/median/p95 that counts as drift "
                    "(default 20).")
    th.add_argument("--warning-row-change", type=float,
                    help="Percent row-count change that counts as WARNING (default 20).")
    th.add_argument("--critical-row-change", type=float,
                    help="Percent row-count change that counts as CRITICAL (default 50).")
    th.add_argument("--psi-warning", type=float,
                    help="PSI that counts as WARNING drift (default 0.10).")
    th.add_argument("--psi-critical", type=float,
                    help="PSI that counts as CRITICAL drift (default 0.25).")
    th.add_argument("--warning-changed-rows", type=float,
                    help="Percent of rows removed/changed (with --key) that counts "
                    "as WARNING (default 1).")
    th.add_argument("--critical-changed-rows", type=float,
                    help="Percent of rows removed/changed (with --key) that counts "
                    "as CRITICAL (default 10).")
    th.add_argument("--abs-tolerance", type=float,
                    help="Absolute tolerance for numeric values in the row diff.")
    th.add_argument("--rel-tolerance", type=float,
                    help="Relative tolerance for numeric values in the row diff.")

    src = parser.add_argument_group("sources")
    src.add_argument(
        "--duckdb", metavar="DATABASE",
        help="Read OLD and NEW as table names or SELECT queries from this "
        "DuckDB database file (opened read-only).",
    )
    src.add_argument(
        "--config", metavar="FILE",
        help="TOML file with settings ([datadiff] or [tool.datadiff] table). "
        "Command-line options take precedence.",
    )

    parser.add_argument(
        "--fail-on", choices=["warning", "critical"], default=None,
        help="Exit with code 1 when the overall severity reaches this "
        "level. Useful as a quality gate in pipelines and CI.",
    )

    return parser


def _settings(args: argparse.Namespace) -> tuple[DiffConfig, dict[str, Any]]:
    """Merge config-file settings with command-line options."""
    file_settings = load_config_file(args.config) if args.config else {}

    run = {k: file_settings.pop(k) for k in list(file_settings) if k in _RUN_SETTINGS}
    values: dict[str, Any] = dict(file_settings)

    for option, field_name in _THRESHOLD_OPTIONS.items():
        value = getattr(args, option)
        if value is not None:
            values[field_name] = value

    if args.ignore is not None:
        values["ignored_columns"] = args.ignore
    if args.freshness_column is not None:
        values["freshness_columns"] = args.freshness_column
    if args.no_stats:
        values["statistical_tests"] = False

    if args.key:
        run["key"] = args.key
    if args.segment_by:
        run["segment_by"] = args.segment_by
    if args.fail_on:
        run["fail_on"] = args.fail_on
    if args.json:
        run["format"] = "json"
    elif args.format:
        run["format"] = args.format

    try:
        config = DiffConfig.from_dict(values)
    except TypeError as error:
        raise ValueError(f"Invalid config value: {error}") from error

    fmt = run.get("format", "text")
    if fmt not in FORMATS:
        raise ValueError(f"Unknown format: {fmt}")
    fail_on = run.get("fail_on")
    if fail_on is not None and fail_on not in ("warning", "critical"):
        raise ValueError(f"fail_on must be 'warning' or 'critical', not {fail_on!r}")
    return config, run


def render(diff: DatasetDiff, fmt: str) -> str:
    if fmt == "json":
        # allow_nan=False guarantees strictly valid JSON output.
        return json.dumps(diff.to_dict(), indent=2, allow_nan=False)
    if fmt == "markdown":
        return diff.to_markdown()
    if fmt == "html":
        return diff.to_html()
    return diff.to_text()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config, run = _settings(args)

        if args.duckdb:
            old = load_duckdb(args.duckdb, args.old)
            new = load_duckdb(args.duckdb, args.new)
        else:
            old = load_dataframe(args.old)
            new = load_dataframe(args.new)

        diff = compare(
            old,
            new,
            config=config,
            key=run.get("key"),
            segment_by=run.get("segment_by"),
        )
    except (FileNotFoundError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR

    fmt = run.get("format", "text")

    if fmt == "rich" and not args.output:
        try:
            _report.print_rich(diff)
        except ImportError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_ERROR
    else:
        output = render(diff, "text" if fmt == "rich" else fmt)
        if args.output:
            try:
                Path(args.output).write_text(output + "\n", encoding="utf-8")
            except OSError as error:
                print(f"error: cannot write {args.output}: {error}", file=sys.stderr)
                return EXIT_ERROR
        else:
            print(output)

    fail_on = run.get("fail_on")
    if fail_on is not None:
        threshold = SEVERITY_ORDER[fail_on.upper()]
        if SEVERITY_ORDER[diff.overall_severity] >= threshold:
            return EXIT_THRESHOLD

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
