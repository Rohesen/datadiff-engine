# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.3.x | ✅ |
| < 0.3 | ❌ |

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Report them privately through GitHub's [private vulnerability reporting](https://github.com/Rohesen/datadiff-engine/security/advisories/new).

Please include the affected version, a description of the issue and, if possible, steps to reproduce it. You can expect an acknowledgement within 7 days.

## How the project stays secure

- **No code execution from data.** The library never uses `eval`, `exec`, `pickle` or shell commands, and the CLI only reads data files in plain data formats.
- **Escaped reports.** Every value taken from the data (column names, category values, segment labels) is escaped before it is written into Markdown or HTML reports. HTML reports contain no scripts and set a Content-Security-Policy that blocks them.
- **Sandboxed DuckDB access.** With `--duckdb`, the database is opened read-only, with access to external files and the network disabled and the configuration locked. Table names are read through DuckDB's relation API, never by inserting them into SQL text.
- **Safe dependency versions.** The Parquet and Polars extras require `pyarrow >= 14.0.1`, which fixes CVE-2023-47248 (remote code execution when reading untrusted Parquet/IPC files).
- **Automated checks in CI.** Every change is checked with Bandit (static security analysis), pip-audit (known vulnerabilities in dependencies), Ruff (including its security rules) and mypy. Dependabot keeps dependencies and GitHub Actions up to date.
- **Least-privilege CI.** Workflows only read the repository by default, and releases use PyPI Trusted Publishing, so no long-lived PyPI token is stored.

## Handling untrusted files

When comparing files from sources you do not trust, keep in mind that a very large or crafted file can still use a lot of memory, as with any pandas-based tool. Run such comparisons with resource limits (for example in a container).
