import argparse
import json
from pathlib import Path

import pandas as pd

from .compare import SEVERITY_ORDER, DiffConfig, compare

# Exit codes
EXIT_OK = 0
EXIT_THRESHOLD = 1  # --fail-on threshold reached
EXIT_ERROR = 2      # bad input (missing file, unsupported type, ...)


def load_dataframe(path: str) -> pd.DataFrame:
    """Load a CSV or Parquet file."""
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = file_path.suffix.lower()

    if suffix == ".csv":
        return pd.read_csv(file_path)

    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(file_path)

    raise ValueError(
        f"Unsupported file type: {suffix}. "
        "Use .csv or .parquet."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare two datasets.",
    )

    parser.add_argument(
        "old",
        help="Path to the old/baseline dataset.",
    )

    parser.add_argument(
        "new",
        help="Path to the new/current dataset.",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output the report as JSON.",
    )

    parser.add_argument(
        "--ignore",
        nargs="*",
        default=[],
        help="Columns to exclude from numeric drift analysis.",
    )

    parser.add_argument(
        "--warning-null-rate",
        type=float,
        default=0.05,
        help="Null-rate increase that counts as WARNING (default 0.05).",
    )

    parser.add_argument(
        "--critical-null-rate",
        type=float,
        default=0.20,
        help="Null-rate increase that counts as CRITICAL (default 0.20).",
    )

    parser.add_argument(
        "--drift-threshold",
        type=float,
        default=20.0,
        help="Percent change in mean/median/p95 that counts as drift "
        "(default 20).",
    )

    parser.add_argument(
        "--warning-row-change",
        type=float,
        default=20.0,
        help="Percent row-count change that counts as WARNING (default 20).",
    )

    parser.add_argument(
        "--critical-row-change",
        type=float,
        default=50.0,
        help="Percent row-count change that counts as CRITICAL (default 50).",
    )

    parser.add_argument(
        "--fail-on",
        choices=["warning", "critical"],
        default=None,
        help="Exit with code 1 when the overall severity reaches this "
        "level. Useful as a quality gate in pipelines and CI.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = DiffConfig(
            warning_null_rate=args.warning_null_rate,
            critical_null_rate=args.critical_null_rate,
            ignored_columns=frozenset(args.ignore),
            drift_threshold_pct=args.drift_threshold,
            warning_row_change_pct=args.warning_row_change,
            critical_row_change_pct=args.critical_row_change,
        )

        diff = compare(
            load_dataframe(args.old),
            load_dataframe(args.new),
            config=config,
        )
    except (FileNotFoundError, ValueError) as error:
        print(f"error: {error}")
        return EXIT_ERROR

    if args.json:
        # allow_nan=False guarantees strictly valid JSON output.
        print(json.dumps(diff.to_dict(), indent=2, allow_nan=False))
    else:
        print(diff)

    if args.fail_on is not None:
        threshold = SEVERITY_ORDER[args.fail_on.upper()]
        if SEVERITY_ORDER[diff.overall_severity] >= threshold:
            return EXIT_THRESHOLD

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
