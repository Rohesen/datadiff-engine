"""CLI: formats, output files, config files, DuckDB and error handling."""

import json

import numpy as np
import pandas as pd
import pytest

from datadiff_engine.cli import EXIT_ERROR, EXIT_OK, EXIT_THRESHOLD, main


@pytest.fixture
def files(tmp_path):
    old = pd.DataFrame({"id": [1, 2, 3], "status": ["ok", "ok", "ok"]})
    new = pd.DataFrame({"id": [1, 2, 4], "status": ["ok", "late", "ok"]})
    old_path, new_path = tmp_path / "old.csv", tmp_path / "new.csv"
    old.to_csv(old_path, index=False)
    new.to_csv(new_path, index=False)
    return str(old_path), str(new_path)


@pytest.mark.parametrize("fmt, marker", [
    ("text", "DATASET DIFF"),
    ("markdown", "# Dataset diff"),
    ("html", "<!DOCTYPE html>"),
    ("json", '"schema_version"'),
])
def test_formats(files, capsys, fmt, marker):
    assert main([*files, "--format", fmt]) == EXIT_OK
    assert marker in capsys.readouterr().out


def test_output_file(files, tmp_path):
    target = tmp_path / "report.json"

    assert main([*files, "--json", "--key", "id", "-o", str(target)]) == EXIT_OK

    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["row_diff"]["rows_changed"] == 1


def test_errors_go_to_stderr(capsys):
    assert main(["missing.csv", "other.csv"]) == EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err


def test_bad_key_is_a_clean_error(files, capsys):
    assert main([*files, "--key", "nope"]) == EXIT_ERROR
    assert "Key column" in capsys.readouterr().err


def test_more_file_formats(tmp_path):
    pytest.importorskip("pyarrow")
    df = pd.DataFrame({"a": [1, 2]})
    for name, write in [
        ("d.tsv", lambda p: df.to_csv(p, sep="\t", index=False)),
        ("d.jsonl", lambda p: df.to_json(p, orient="records", lines=True)),
        ("d.json", lambda p: df.to_json(p, orient="records")),
        ("d.feather", lambda p: df.to_feather(p)),
    ]:
        path = tmp_path / name
        write(path)
        assert main([str(path), str(path)]) == EXIT_OK


def test_config_file(files, tmp_path, capsys):
    config = tmp_path / "pyproject.toml"
    config.write_text(
        '[tool.datadiff]\nkey = ["id"]\nfail_on = "warning"\n'
        'format = "json"\nwarning_changed_rows_pct = 1.0\n',
        encoding="utf-8",
    )

    assert main([*files, "--config", str(config)]) == EXIT_THRESHOLD
    report = json.loads(capsys.readouterr().out)
    assert report["row_diff"]["key"] == ["id"]


def test_cli_overrides_config_file(files, tmp_path, capsys):
    config = tmp_path / "datadiff.toml"
    config.write_text('[datadiff]\nformat = "json"\n', encoding="utf-8")

    assert main([*files, "--config", str(config), "--format", "markdown"]) == EXIT_OK
    assert capsys.readouterr().out.startswith("# Dataset diff")


@pytest.mark.parametrize("content, message", [
    ("[datadiff]\nbogus = 1\n", "unknown setting"),
    ("[datadiff]\npsi_warning = 'high'\n", "error"),
    ("not toml = = =", "Invalid TOML"),
])
def test_bad_config_files(files, tmp_path, capsys, content, message):
    config = tmp_path / "c.toml"
    config.write_text(content, encoding="utf-8")

    assert main([*files, "--config", str(config)]) == EXIT_ERROR
    assert message in capsys.readouterr().err


@pytest.fixture
def warehouse(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    path = tmp_path / "w.duckdb"
    rng = np.random.default_rng(0)
    orders = pd.DataFrame({"id": range(100), "amount": rng.normal(50, 5, 100)})  # noqa: F841
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE orders AS SELECT * FROM orders")
    con.execute("CREATE SCHEMA staging")
    con.execute("CREATE TABLE staging.orders AS SELECT * FROM orders WHERE id < 90")
    con.close()
    return str(path)


def test_duckdb_tables_and_queries(warehouse, capsys):
    assert main(["--duckdb", warehouse, "orders", "staging.orders",
                 "--key", "id", "--json"]) == EXIT_OK
    report = json.loads(capsys.readouterr().out)
    assert report["row_diff"]["rows_removed"] == 10

    assert main(["--duckdb", warehouse, "orders",
                 "SELECT * FROM orders WHERE id < 10"]) == EXIT_OK


@pytest.mark.parametrize("source", [
    "DROP TABLE orders",
    "orders; DROP TABLE orders",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT 1; DROP TABLE orders",
])
def test_duckdb_is_read_only_and_sandboxed(warehouse, capsys, source):
    import duckdb

    assert main(["--duckdb", warehouse, "orders", source]) == EXIT_ERROR

    con = duckdb.connect(warehouse, read_only=True)
    assert con.execute("SELECT count(*) FROM orders").fetchone()[0] == 100
    con.close()


def test_duckdb_missing_database(capsys):
    pytest.importorskip("duckdb")
    assert main(["--duckdb", "nope.duckdb", "a", "b"]) == EXIT_ERROR


def test_rich_format(files, capsys):
    pytest.importorskip("rich")
    assert main([*files, "--format", "rich"]) == EXIT_OK
