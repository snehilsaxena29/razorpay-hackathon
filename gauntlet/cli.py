"""The command-line interface. The only module that reads argv or exits the process.

Exit codes are part of the contract, not an afterthought — see
:class:`~gauntlet.errors.ExitCode`. A CI job can gate on 1 ("this agent is
unsafe") and alert separately on 2 ("we could not tell"), and conflating those
two would defeat the point of the tool.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from gauntlet import __version__
from gauntlet.attacks import registry
from gauntlet.errors import ExitCode, GauntletError
from gauntlet.ledger import LEDGER_FILENAME, Ledger, new_run_id
from gauntlet.mandate import load_mandate
from gauntlet.report import console as console_report
from gauntlet.report import json_report, markdown_report
from gauntlet.runner import Runner, RunResult, exit_code_for
from subjects import AGENTS, build

DEFAULT_MANDATE = "mandates/ops_default.toml"
DEFAULT_OUT_DIR = "runs"
DEMO_AGENTS = ("naive-stub", "hardened-stub")


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns a process exit code and never raises to the caller."""
    _ensure_utf8_console()
    parser = _build_parser()
    args = parser.parse_args(argv)

    console = console_report.make_console()
    try:
        return int(args.handler(args, console))
    except GauntletError as exc:
        console.print(f"[bold red]{type(exc).__name__}[/bold red]: {exc}")
        return int(ExitCode.CANNOT_START)
    except KeyboardInterrupt:
        console.print(
            "\n[yellow]Interrupted.[/yellow] The ledger holds everything written "
            "so far; regenerate with [bold]gauntlet report <run_id>[/bold]."
        )
        return int(ExitCode.DEGRADED)


def _ensure_utf8_console() -> None:
    """Force UTF-8 on stdout and stderr.

    A Windows terminal defaults to a legacy code page that cannot encode ``₹``,
    and the first formatted rupee amount would otherwise raise
    ``UnicodeEncodeError`` mid-run. Found the hard way; the demo is recorded on
    Windows.
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _cmd_run(args: argparse.Namespace, console: object) -> int:
    """Run a catalogue selection against one agent."""
    from rich.console import Console

    assert isinstance(console, Console)
    mandate = load_mandate(args.mandate)
    attacks = registry.select(attack_ids=args.attack or (), family=args.family)
    agent = build(args.agent)

    result = _execute(agent, attacks, mandate, Path(args.out_dir), args.timeout)
    console_report.print_run(console, result)
    if args.verbose:
        console_report.print_family_breakdown(console, result)

    paths = _write_reports(result, Path(args.out_dir))
    console_report.print_paths(console, paths)
    return exit_code_for([result])


def _cmd_compare(args: argparse.Namespace, console: object) -> int:
    """Run the same catalogue against several agents and show them side by side."""
    from rich.console import Console

    assert isinstance(console, Console)
    mandate = load_mandate(args.mandate)
    attacks = registry.select(attack_ids=args.attack or (), family=args.family)

    results: list[RunResult] = []
    all_paths: list[str] = []
    for name in args.agents.split(","):
        result = _execute(build(name.strip()), attacks, mandate, Path(args.out_dir), args.timeout)
        results.append(result)
        console_report.print_run(console, result)
        all_paths.extend(_write_reports(result, Path(args.out_dir)))

    console_report.print_comparison(console, results)
    console_report.print_paths(console, all_paths)
    return exit_code_for(results)


def _cmd_demo(args: argparse.Namespace, console: object) -> int:
    """The one command a reviewer runs. Works with no API key and no network."""
    from rich.console import Console

    assert isinstance(console, Console)
    console.print(
        "\n[bold]gauntlet[/bold] — an adversarial test harness for payment agents.\n"
        "Running the full catalogue against a naive agent, then a hardened one.\n"
        "No money moves: every payment is captured by a recording sink.\n"
    )
    args.agents = ",".join(DEMO_AGENTS)
    args.attack = ()
    args.family = None
    code = _cmd_compare(args, console)
    console.print(
        "[dim]A PASS means the agent resisted this attack, not that it is safe. "
        "See the markdown report for the transcript excerpt behind each failure.[/dim]\n"
    )
    return code


def _cmd_report(args: argparse.Namespace, console: object) -> int:
    """Regenerate reports from a ledger, proving the ledger is the source of truth."""
    from rich.console import Console

    assert isinstance(console, Console)
    ledger_path = Path(args.out_dir) / args.run_id / LEDGER_FILENAME
    if not ledger_path.exists():
        console.print(f"[bold red]No ledger at[/bold red] {ledger_path}")
        return int(ExitCode.CANNOT_START)

    from gauntlet.ledger import read_ledger

    records = list(read_ledger(ledger_path))
    console.print(f"Ledger {ledger_path} holds {len(records)} record(s).")
    for record in records:
        if record.get("type") == "verdict":
            console.print(
                f"  {record['attack_id']:<9} {record['verdict']:<8} "
                f"{','.join(record.get('predicates_fired', [])) or '—'}"
            )
    return int(ExitCode.CLEAN)


def _cmd_list(args: argparse.Namespace, console: object) -> int:
    """List what is available, so a selector typo is easy to spot."""
    from rich.console import Console

    assert isinstance(console, Console)
    if args.what == "agents":
        for name in sorted(AGENTS):
            console.print(f"  {name}")
        return int(ExitCode.CLEAN)

    total = registry.total_weight()
    console.print(f"[bold]{len(registry.all_attacks())} attacks, total weight {total}[/bold]\n")
    for attack in registry.all_attacks():
        judged = "LLM" if attack.requires_llm else "deterministic"
        console.print(
            f"  {attack.id:<9} {attack.severity!s:<9} {attack.family:<20} "
            f"[dim]{judged}[/dim]  {attack.title}"
        )
    deterministic = sum(1 for a in registry.all_attacks() if a.is_deterministic)
    console.print(
        f"\n[dim]{deterministic} of {len(registry.all_attacks())} are judged with no model "
        "in the loop.[/dim]"
    )
    return int(ExitCode.CLEAN)


# ---------------------------------------------------------------------------
# Shared execution
# ---------------------------------------------------------------------------


def _execute(
    agent: object, attacks: Sequence[object], mandate: object, out_dir: Path, timeout: int
) -> RunResult:
    """Run one agent, writing its ledger before anything else happens."""
    run_id = new_run_id()
    ledger_path = out_dir / run_id / LEDGER_FILENAME
    with Ledger(ledger_path, run_id=run_id) as ledger:
        runner = Runner(
            mandate=mandate,  # type: ignore[arg-type]
            ledger=ledger,
            episode_timeout_s=timeout,
            mode=_mode(),
        )
        runner._run_id = run_id
        return runner.run(agent, attacks)  # type: ignore[arg-type]


def _mode() -> str:
    """LIVE when a provider key is present, REPLAY otherwise.

    Reported in every report header. A replayed run is never presented as a
    live one.
    """
    requested = os.environ.get("GAUNTLET_MODE", "auto").lower()
    has_key = bool(os.environ.get("GROQ_API_KEY"))
    if requested == "live":
        if not has_key:
            from gauntlet.errors import ConfigError

            raise ConfigError(
                "GAUNTLET_MODE=live but GROQ_API_KEY is unset. Refusing to silently "
                "downgrade to REPLAY — set the key, or use GAUNTLET_MODE=auto."
            )
        return "LIVE"
    if requested == "replay":
        return "REPLAY"
    return "LIVE" if has_key else "REPLAY"


def _write_reports(result: RunResult, out_dir: Path) -> list[str]:
    """Write both reports for a run and return their paths."""
    attacks_by_id = {a.id: a for a in registry.all_attacks()}
    run_dir = out_dir / result.run_id
    json_path = json_report.write(result, run_dir / "report.json", attacks_by_id=attacks_by_id)
    md_path = markdown_report.write(result, run_dir / "report.md", attacks_by_id=attacks_by_id)
    return [str(md_path), str(json_path)]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gauntlet",
        description="An adversarial test harness for payment-capable AI agents.",
    )
    parser.add_argument("--version", action="version", version=f"gauntlet {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--mandate", default=DEFAULT_MANDATE, help="path to a mandate TOML")
        sub.add_argument("--out-dir", default=os.environ.get("GAUNTLET_OUT_DIR", DEFAULT_OUT_DIR))
        sub.add_argument(
            "--timeout",
            type=int,
            default=int(os.environ.get("GAUNTLET_EPISODE_TIMEOUT_S", "60")),
            help="wall-clock budget per attack, in seconds",
        )

    run = subparsers.add_parser("run", help="run attacks against one agent")
    run.add_argument("--agent", required=True, help=f"one of: {', '.join(sorted(AGENTS))}")
    run.add_argument("--attack", action="append", help="attack id; repeatable")
    run.add_argument("--family", help="run one family")
    run.add_argument("--verbose", action="store_true")
    add_common(run)
    run.set_defaults(handler=_cmd_run)

    compare = subparsers.add_parser("compare", help="run the same attacks against several agents")
    compare.add_argument("--agents", default=",".join(DEMO_AGENTS))
    compare.add_argument("--attack", action="append")
    compare.add_argument("--family")
    compare.add_argument("--verbose", action="store_true")
    add_common(compare)
    compare.set_defaults(handler=_cmd_compare)

    demo = subparsers.add_parser("demo", help="the full before/after run; no API key needed")
    demo.add_argument("--verbose", action="store_true")
    add_common(demo)
    demo.set_defaults(handler=_cmd_demo)

    report = subparsers.add_parser("report", help="regenerate reports from a ledger")
    report.add_argument("run_id")
    report.add_argument("--out-dir", default=os.environ.get("GAUNTLET_OUT_DIR", DEFAULT_OUT_DIR))
    report.set_defaults(handler=_cmd_report)

    listing = subparsers.add_parser("list", help="list attacks or agents")
    listing.add_argument("what", choices=["attacks", "agents"])
    listing.set_defaults(handler=_cmd_list)

    return parser


if __name__ == "__main__":
    raise SystemExit(main())
