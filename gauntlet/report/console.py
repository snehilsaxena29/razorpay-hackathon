"""Terminal output. The only module permitted to import ``rich``.

This is what a reviewer sees first and what the demo video shows, so it earns
the dependency. Everything here is presentation: no decision, no verdict, and no
number is computed in this file.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from gauntlet.judge.verdict import Verdict
from gauntlet.report.summary import family_breakdown
from gauntlet.runner import RunResult

_VERDICT_STYLE: dict[Verdict, tuple[str, str]] = {
    Verdict.PASS: ("PASS", "bold green"),
    Verdict.FAIL: ("FAIL", "bold red"),
    Verdict.UNKNOWN: ("UNKNOWN", "bold yellow"),
    Verdict.ERROR: ("ERROR", "bold magenta"),
    Verdict.SKIPPED: ("skipped", "dim"),
}

_SEVERITY_STYLE = {
    "CRITICAL": "bold red",
    "HIGH": "red",
    "MEDIUM": "yellow",
    "LOW": "dim",
}


def ensure_utf8_streams() -> None:
    """Force UTF-8 on stdout and stderr.

    A Windows terminal defaults to a legacy code page that cannot encode ``₹``,
    and the first formatted rupee amount would otherwise raise
    ``UnicodeEncodeError`` mid-run. Found the hard way; the demo is recorded on
    Windows.

    Called by the CLI before anything prints, and by any standalone script that
    writes to a terminal.
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def make_console() -> Console:
    """A console that survives a Windows terminal in a legacy code page.

    ``rich`` handles most of this, but the underlying stream still has to be
    able to encode ``₹``, which is what :func:`ensure_utf8_streams` guarantees.
    """
    return Console(file=sys.stdout, highlight=False, soft_wrap=False)


def print_run(console: Console, result: RunResult) -> None:
    """Print the per-attack table and the score for one agent."""
    score = result.score

    table = Table(
        title=f"[bold]{result.agent_name}[/bold] vs {len(result.records)} attacks",
        title_justify="left",
        header_style="bold",
        expand=False,
    )
    table.add_column("ID", no_wrap=True)
    table.add_column("Family")
    table.add_column("Severity", no_wrap=True)
    table.add_column("Verdict", no_wrap=True)
    table.add_column("Checks that fired")
    table.add_column("ms", justify="right", no_wrap=True)

    for record in sorted(result.records, key=lambda r: r.attack_id):
        label, style = _VERDICT_STYLE[record.verdict]
        detail = ", ".join(record.predicates_fired)
        if record.verdict is Verdict.ERROR and record.error:
            detail = record.error
        elif record.verdict is Verdict.UNKNOWN and record.unknown_reason:
            detail = record.unknown_reason

        table.add_row(
            record.attack_id,
            record.family.replace("_", " "),
            Text(str(record.severity), style=_SEVERITY_STYLE.get(str(record.severity), "")),
            Text(label, style=style),
            detail or "—",
            str(record.duration_ms),
        )

    console.print(table)

    style = "green" if score.failed == 0 and not score.is_degraded else "red"
    headline = Text(f"Safety score: {score.display}", style=f"bold {style}")
    subtitle = Text(
        f"\n{score.failed} of {score.resolved_count} resolved attacks succeeded against "
        f"this agent."
        f"\nWeighted {score.weighted_resisted}/{score.weighted_resolved} · "
        f"passed {score.passed} · failed {score.failed} · "
        f"unknown {score.unknown} · error {score.errored}",
        style="",
    )
    console.print(Panel(headline + subtitle, expand=False, border_style=style))

    if score.is_degraded:
        console.print(
            "[yellow]DEGRADED[/yellow] — unresolved attacks are excluded from the score "
            "in both the numerator and the denominator. They are not passes.\n"
        )
    if result.mode != "LIVE":
        console.print(f"[dim]Mode: {result.mode} (recorded exchanges replayed).[/dim]\n")


def print_family_breakdown(console: Console, result: RunResult) -> None:
    """Print the per-family rollup."""
    table = Table(title="By family", title_justify="left", header_style="bold", expand=False)
    table.add_column("Family")
    table.add_column("Run", justify="right")
    table.add_column("Resisted", justify="right")
    table.add_column("Succeeded", justify="right")
    table.add_column("Unresolved", justify="right")

    for row in family_breakdown(result.records):
        table.add_row(
            row.family.replace("_", " "),
            str(row.run),
            Text(str(row.passed), style="green" if row.passed else ""),
            Text(str(row.failed), style="red" if row.failed else ""),
            Text(str(row.unresolved), style="yellow" if row.unresolved else ""),
        )
    console.print(table)


def print_comparison(console: Console, results: Sequence[RunResult]) -> None:
    """Print the side-by-side table. This is the frame the demo video lands on."""
    if not results:
        return

    table = Table(
        title="[bold]Before and after[/bold]",
        title_justify="left",
        header_style="bold",
        expand=False,
    )
    table.add_column("Attack", no_wrap=True)
    table.add_column("Severity", no_wrap=True)
    for result in results:
        table.add_column(result.agent_name, justify="center", no_wrap=True)

    attack_ids = sorted({r.attack_id for result in results for r in result.records})
    for attack_id in attack_ids:
        cells: list[Text] = []
        severity = ""
        for result in results:
            record = next((r for r in result.records if r.attack_id == attack_id), None)
            if record is None:
                cells.append(Text("—", style="dim"))
                continue
            severity = str(record.severity)
            label, style = _VERDICT_STYLE[record.verdict]
            cells.append(Text(label, style=style))
        table.add_row(
            attack_id,
            Text(severity, style=_SEVERITY_STYLE.get(severity, "")),
            *cells,
        )

    table.add_section()
    table.add_row(
        Text("SAFETY SCORE", style="bold"),
        "",
        *[
            Text(
                r.score.display,
                style="bold green" if (r.score.score or 0) > 0.8 else "bold red",
            )
            for r in results
        ],
    )
    console.print(table)


def print_paths(console: Console, paths: Sequence[str]) -> None:
    """Tell the user where the full reports are."""
    console.print("\n[bold]Reports written:[/bold]")
    for path in paths:
        console.print(f"  {path}")
    console.print("")
