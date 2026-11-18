"""Human-readable reports: plain text, Markdown, HTML and Rich.

Every value that comes from the data (column names, category values,
segment labels) is escaped before it is written into Markdown or HTML,
so a malicious cell cannot inject markup or scripts into a report.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .compare import ColumnDiff, DatasetDiff

SEVERITY_ICON = {"INFO": "🔵", "WARNING": "🟡", "CRITICAL": "🔴"}
SEVERITY_COLOR = {"INFO": "#2563eb", "WARNING": "#b45309", "CRITICAL": "#b91c1c"}


def _overall(diff: DatasetDiff) -> str:
    issues = diff.issues()
    return issues[0].severity if issues else "INFO"


def _column_has_changes(column: ColumnDiff) -> bool:
    return bool(
        column.dtype_changed
        or column.null_rate_change != 0
        or column.unique_count_change != 0
        or (column.distribution is not None and column.distribution.has_drift)
    )


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------


def to_text(diff: DatasetDiff) -> str:
    issues = diff.issues()
    lines = [
        "DATASET DIFF",
        "=" * 40,
        "",
        f"OVERALL SEVERITY: {_overall(diff)}",
    ]

    for issue in issues:
        lines.append(f"  [{issue.severity}] {issue.message}")

    if not issues:
        lines.append("  No notable changes.")

    lines.extend([
        "",
        "ROWS",
        f"  {diff.rows_old:,} → {diff.rows_new:,}",
        f"  Change: {diff.row_change:+,} ({diff.row_change_pct:+.2f}%)",
        "",
        "SCHEMA",
        f"  + Added:   {diff.added_columns or 'none'}",
        f"  - Removed: {diff.removed_columns or 'none'}",
    ])

    if diff.changed_types:
        for name, (old_type, new_type) in diff.changed_types.items():
            lines.append(f"  ~ Changed: {name} ({old_type} → {new_type})")
    else:
        lines.append("  ~ Changed: none")

    lines.extend(["", "COLUMN CHANGES", "-" * 40])

    for name, column in diff.column_diffs.items():
        if not _column_has_changes(column):
            continue

        lines.append(str(name))

        if column.dtype_changed:
            lines.append(
                f"  Data type: {column.old_dtype} → {column.new_dtype}"
            )

        if column.null_rate_change != 0:
            change_points = column.null_rate_change * 100
            lines.append(
                f"  Null rate: {column.null_rate_old:.2%} → "
                f"{column.null_rate_new:.2%} ({change_points:+.2f} pp)"
            )

        if column.unique_count_change != 0:
            lines.append(
                f"  Unique values: {column.unique_count_old:,} → "
                f"{column.unique_count_new:,} "
                f"({column.unique_count_change:+,})"
            )

        lines.append(f"  Severity:  {column.severity}")

        dist = column.distribution
        if dist is not None:
            if dist.method == "numeric":
                lines.append(
                    f"  Distribution: PSI {dist.psi:.3f}, "
                    f"KS {dist.ks_statistic:.3f} (p={dist.ks_p_value:.2g})"
                )
            else:
                lines.append(
                    f"  Distribution: PSI {dist.psi:.3f}, "
                    f"Jensen-Shannon {dist.js_distance:.3f}"
                )

        if column.old_stats is not None and column.new_stats is not None:
            old_stats = column.old_stats
            new_stats = column.new_stats
            lines.extend([
                "",
                "  Statistics",
                f"    Mean:    {old_stats.mean:.2f} → {new_stats.mean:.2f}",
                f"    Median:  {old_stats.median:.2f} → "
                f"{new_stats.median:.2f}",
                f"    Min:     {old_stats.min:.2f} → {new_stats.min:.2f}",
                f"    Max:     {old_stats.max:.2f} → {new_stats.max:.2f}",
                f"    P95:     {old_stats.p95:.2f} → {new_stats.p95:.2f}",
            ])

        if (
            column.old_datetime_stats is not None
            and column.new_datetime_stats is not None
        ):
            old_dt = column.old_datetime_stats.to_dict()
            new_dt = column.new_datetime_stats.to_dict()
            lines.append(
                f"  Date range: {old_dt['min']} … {old_dt['max']} → "
                f"{new_dt['min']} … {new_dt['max']}"
            )

        lines.append("")

    rd = diff.row_diff
    if rd is not None:
        lines.extend([
            f"ROW DIFF (key: {', '.join(map(str, rd.key))})",
            "-" * 40,
            f"  Added:     {rd.rows_added:,}",
            f"  Removed:   {rd.rows_removed:,}",
            f"  Changed:   {rd.rows_changed:,}",
            f"  Unchanged: {rd.rows_unchanged:,}",
        ])
        for name, count in rd.changed_by_column.items():
            lines.append(f"    {name}: {count:,} changed")
        lines.append("")

    sd = diff.segment_diff
    if sd is not None:
        lines.extend([
            f"SEGMENTS (by: {', '.join(map(str, sd.columns))})",
            "-" * 40,
        ])
        for seg in sd.segments[:20]:
            lines.append(
                f"  {seg.label}: {seg.rows_old:,} → {seg.rows_new:,} rows "
                f"({seg.share_old:.1%} → {seg.share_new:.1%})"
            )
        if len(sd.segments) > 20 or sd.truncated:
            lines.append("  ...")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _md(value: Any) -> str:
    """Escape text for a Markdown table cell (and neutralise raw HTML)."""
    text = html.escape(str(value), quote=False)
    for char in ("\\", "|", "`", "*", "_", "[", "]"):
        text = text.replace(char, "\\" + char)
    return text.replace("\n", " ").replace("\r", " ")


def to_markdown(diff: DatasetDiff) -> str:
    overall = _overall(diff)
    issues = diff.issues()
    out = [
        "# Dataset diff",
        "",
        f"**Overall severity:** {SEVERITY_ICON[overall]} {overall} · "
        f"**Rows:** {diff.rows_old:,} → {diff.rows_new:,} "
        f"({diff.row_change_pct:+.1f}%) · **Issues:** {len(issues)}",
        "",
        "## Issues",
        "",
    ]
    if issues:
        out += ["| Severity | Kind | Column | Segment | Message |",
                "|---|---|---|---|---|"]
        for issue in issues:
            out.append(
                f"| {SEVERITY_ICON[issue.severity]} {issue.severity} "
                f"| `{issue.kind}` | {_md(issue.column or '')} "
                f"| {_md(issue.segment or '')} | {_md(issue.message)} |"
            )
    else:
        out.append("No notable changes.")

    out += [
        "",
        "## Schema",
        "",
        f"- Added: {_md(', '.join(map(str, diff.added_columns)) or 'none')}",
        f"- Removed: "
        f"{_md(', '.join(map(str, diff.removed_columns)) or 'none')}",
    ]
    for name, (old_type, new_type) in diff.changed_types.items():
        out.append(f"- Type changed: {_md(name)} ({old_type} → {new_type})")

    changed = [c for c in diff.column_diffs.values() if _column_has_changes(c)]
    if changed:
        out += [
            "",
            "## Column changes",
            "",
            "| Column | Type | Null rate | Unique | PSI |",
            "|---|---|---|---|---|",
        ]
        for c in changed:
            dtype = (
                f"{c.old_dtype} → {c.new_dtype}" if c.dtype_changed
                else c.new_dtype
            )
            psi = f"{c.distribution.psi:.3f}" if c.distribution else ""
            out.append(
                f"| {_md(c.name)} | {_md(dtype)} "
                f"| {c.null_rate_old:.1%} → {c.null_rate_new:.1%} "
                f"| {c.unique_count_old:,} → {c.unique_count_new:,} | {psi} |"
            )

    rd = diff.row_diff
    if rd is not None:
        out += [
            "",
            f"## Row diff (key: {_md(', '.join(map(str, rd.key)))})",
            "",
            "| Added | Removed | Changed | Unchanged |",
            "|---|---|---|---|",
            f"| {rd.rows_added:,} | {rd.rows_removed:,} | "
            f"{rd.rows_changed:,} | {rd.rows_unchanged:,} |",
        ]

    sd = diff.segment_diff
    if sd is not None:
        out += [
            "",
            f"## Segments (by: {_md(', '.join(map(str, sd.columns)))})",
            "",
            "| Segment | Rows | Share |",
            "|---|---|---|",
        ]
        for seg in sd.segments[:50]:
            out.append(
                f"| {_md(seg.label)} | {seg.rows_old:,} → {seg.rows_new:,} "
                f"| {seg.share_old:.1%} → {seg.share_new:.1%} |"
            )

    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_CSS = """
body{font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
margin:2rem auto;max-width:1100px;padding:0 1rem;color:#111827}
h1{font-size:1.5rem}h2{font-size:1.15rem;margin-top:2rem}
table{border-collapse:collapse;width:100%;margin:.5rem 0}
th,td{border-bottom:1px solid #e5e7eb;padding:.4rem .6rem;text-align:left;
vertical-align:top}th{background:#f9fafb}
.sev{font-weight:600;white-space:nowrap}.muted{color:#6b7280}
.badge{display:inline-block;padding:.15rem .6rem;border-radius:999px;
color:#fff;font-weight:600}
code{background:#f3f4f6;padding:0 .25rem;border-radius:4px}
"""


def _h(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{_h(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def to_html(diff: DatasetDiff, title: str = "Dataset diff") -> str:
    """Render a self-contained HTML page.

    Cells are pre-escaped with ``html.escape``; the page has no scripts
    and a Content-Security-Policy that blocks any that might slip in.
    """
    overall = _overall(diff)
    issues = diff.issues()
    parts = [
        f"<h1>{_h(title)}</h1>",
        f'<p><span class="badge" style="background:{SEVERITY_COLOR[overall]}">'
        f"{overall}</span> &nbsp; {diff.rows_old:,} → {diff.rows_new:,} rows "
        f'<span class="muted">({diff.row_change_pct:+.1f}%)</span> · '
        f"{len(issues)} issue(s)</p>",
        "<h2>Issues</h2>",
    ]
    if issues:
        parts.append(_table(
            ["Severity", "Kind", "Column", "Segment", "Message"],
            [
                [
                    f'<span class="sev" style="color:'
                    f'{SEVERITY_COLOR[i.severity]}">{i.severity}</span>',
                    f"<code>{_h(i.kind)}</code>",
                    _h(i.column or ""),
                    _h(i.segment or ""),
                    _h(i.message),
                ]
                for i in issues
            ],
        ))
    else:
        parts.append("<p>No notable changes.</p>")

    parts.append("<h2>Schema</h2>")
    parts.append(_table(
        ["Added", "Removed", "Type changes"],
        [[
            _h(", ".join(map(str, diff.added_columns)) or "none"),
            _h(", ".join(map(str, diff.removed_columns)) or "none"),
            _h("; ".join(
                f"{n}: {a} → {b}" for n, (a, b) in diff.changed_types.items()
            ) or "none"),
        ]],
    ))

    parts.append("<h2>Columns</h2>")
    rows = []
    for c in diff.column_diffs.values():
        dist = c.distribution
        rows.append([
            _h(c.name),
            _h(f"{c.old_dtype} → {c.new_dtype}" if c.dtype_changed
               else c.new_dtype),
            f"{c.null_rate_old:.1%} → {c.null_rate_new:.1%}",
            f"{c.unique_count_old:,} → {c.unique_count_new:,}",
            f"{dist.psi:.3f}" if dist else "",
            (f"{dist.ks_statistic:.3f}" if dist and dist.ks_statistic
             is not None else
             f"{dist.js_distance:.3f}" if dist and dist.js_distance
             is not None else ""),
        ])
    parts.append(_table(
        ["Column", "Type", "Null rate", "Unique", "PSI", "KS / JS"], rows
    ))

    rd = diff.row_diff
    if rd is not None:
        parts.append(f"<h2>Row diff <span class='muted'>(key: "
                     f"{_h(', '.join(map(str, rd.key)))})</span></h2>")
        parts.append(_table(
            ["Added", "Removed", "Changed", "Unchanged"],
            [[f"{rd.rows_added:,}", f"{rd.rows_removed:,}",
              f"{rd.rows_changed:,}", f"{rd.rows_unchanged:,}"]],
        ))
        if rd.changed_by_column:
            parts.append(_table(
                ["Column", "Changed rows"],
                [[_h(n), f"{v:,}"] for n, v in rd.changed_by_column.items()],
            ))

    sd = diff.segment_diff
    if sd is not None:
        parts.append(f"<h2>Segments <span class='muted'>(by: "
                     f"{_h(', '.join(map(str, sd.columns)))})</span></h2>")
        parts.append(_table(
            ["Segment", "Rows", "Share"],
            [
                [_h(s.label), f"{s.rows_old:,} → {s.rows_new:,}",
                 f"{s.share_old:.1%} → {s.share_new:.1%}"]
                for s in sd.segments
            ],
        ))

    return (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src "
        "'none'; style-src 'unsafe-inline'\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{_h(title)}</title><style>{_CSS}</style></head><body>"
        + "".join(parts)
        + '<p class="muted">Generated by datadiff-engine.</p></body></html>\n'
    )


# ---------------------------------------------------------------------------
# Rich (optional dependency)
# ---------------------------------------------------------------------------


def print_rich(diff: DatasetDiff, console: Any = None) -> None:
    """Print a coloured report with Rich (``pip install datadiff-engine[rich]``)."""
    try:
        from rich.console import Console
        from rich.markup import escape
        from rich.table import Table
    except ImportError as error:  # pragma: no cover - depends on extras
        raise ImportError(
            "Rich output needs the 'rich' package: "
            "pip install 'datadiff-engine[rich]'"
        ) from error

    console = console or Console()
    styles = {"INFO": "blue", "WARNING": "yellow", "CRITICAL": "bold red"}
    overall = _overall(diff)

    console.rule("[bold]Dataset diff")
    console.print(
        f"Overall severity: [{styles[overall]}]{overall}[/]   "
        f"Rows: {diff.rows_old:,} → {diff.rows_new:,} "
        f"({diff.row_change_pct:+.1f}%)"
    )

    issues = diff.issues()
    if issues:
        table = Table(show_lines=False)
        for header in ("Severity", "Kind", "Column", "Message"):
            table.add_column(header)
        for issue in issues:
            table.add_row(
                f"[{styles[issue.severity]}]{issue.severity}[/]",
                escape(issue.kind),
                escape(str(issue.column or issue.segment or "")),
                escape(issue.message),
            )
        console.print(table)
    else:
        console.print("[green]No notable changes.[/]")

    if diff.row_diff is not None:
        rd = diff.row_diff
        console.print(
            f"Row diff ({escape(', '.join(map(str, rd.key)))}): "
            f"+{rd.rows_added:,} added, -{rd.rows_removed:,} removed, "
            f"~{rd.rows_changed:,} changed"
        )
