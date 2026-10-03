import argparse
import json
from pathlib import Path

import pandas as pd

from .compare import DiffConfig, compare


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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare two datasets."
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

    args = parser.parse_args()

    config = DiffConfig(
        ignored_columns=frozenset(args.ignore),
    )

    diff = compare(
        load_dataframe(args.old),
        load_dataframe(args.new),
        config=config,
    )

    if args.json:
        print(json.dumps(diff.to_dict(), indent=2))
    else:
        print(diff)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())