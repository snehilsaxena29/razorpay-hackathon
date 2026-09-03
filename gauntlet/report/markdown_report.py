"""The human-readable report.

Structured so that a reader who stops after thirty seconds still leaves with the
right conclusion, and a reader who continues can check it. The score is near the
top; the evidence is below it; nothing is hidden further down than it deserves.

Unresolved attacks get their own section and are never folded into the passes.
A tool that reports "we could not tell" as "fine" is worse than no tool.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from gauntlet.agent import Message, Role
from gauntlet.attacks.base import Attack
from gauntlet.errors import LedgerError
from gauntlet.judge.verdict import Verdict
from gauntlet.money import format_minor
from gauntlet.report.summary import (
    excerpt,
    family_breakdown,
    sort_failures,
    truncate,
    truncate_middle,
    unresolved,
)
from gauntlet.runner import AttackRecord, RunResult

_VERDICT_MARK = {
    Verdict.PASS: "PASS",
    Verdict.FAIL: "**FAIL**",
    Verdict.UNKNOWN: "UNKNOWN",
    Verdict.ERROR: "ERROR",
    Verdict.SKIPPED: "skipped",
}


def render(result: RunResult, *, attacks_by_id: dict[str, Attack] | None = None) -> str:
    """Render the full Markdown report for one run."""
    attacks_by_id = attacks_by_id or {}
    score = result.score
    lines: list[str] = []

    lines.append(f"# Safety report — `{result.agent_name}`")
    lines.append("")

    if result.mode != "LIVE":
        lines.append(
            f"> **Mode: {result.mode}.** This run replayed recorded model exchanges rather "
            "than calling a provider live. The agent's behaviour is real and was recorded "
            "from a live run; it was not re-derived here."
        )
        lines.append("")
    if score.is_degraded:
        lines.append(
            f"> **DEGRADED.** {score.unknown} attack(s) could not be judged and "
            f"{score.errored} errored. They are excluded from the score and listed in full "
            "under *Unresolved*. The score below is computed over "
            f"{score.resolved_count} resolved attack(s), not all of them."
        )
        lines.append("")

    lines.extend(_header_table(result))
    lines.extend(_score_block(result))
    lines.extend(_family_table(result))
    lines.extend(_failures(result, attacks_by_id))
    lines.extend(_unresolved(result))
    lines.extend(_all_attacks_table(result))
    lines.extend(_footer(result))

    return "\n".join(lines) + "\n"


def _header_table(result: RunResult) -> list[str]:
    return [
        "| | |",
        "|---|---|",
        f"| Agent | `{result.agent_name}` |",
        f"| Mandate | `{result.mandate.mandate_id}` ({result.mandate.principal}) |",
        f"| Run | `{result.run_id}` |",
        f"| Started | {result.started_at.isoformat(timespec='seconds')} |",
        f"| Duration | {result.duration_s:.1f}s |",
        f"| Mode | {result.mode} |",
        f"| Provider | {result.llm_status} |",
        "",
    ]


def _score_block(result: RunResult) -> list[str]:
    score = result.score
    lines = ["## Safety score", "", f"## {score.headline}", ""]
    if not score.is_representative and score.attempted_count:
        lines += [
            f"> **Only {score.resolved_count} of {score.attempted_count} attacks produced "
            "a verdict.** A percentage over that few is not a safety score — it is the "
            "same number a clean run would print, computed from a fraction of the "
            "evidence. The unresolved attacks are listed below and should be fixed "
            "before any number here is quoted.",
            "",
        ]

    if score.failed:
        lines.append(
            f"**{score.failed} of {score.resolved_count} attacks succeeded against this agent.** "
            "Each one caused a payment attempt that violated the mandate above."
        )
    elif score.resolved_count:
        lines.append(
            f"All {score.resolved_count} resolved attacks were resisted. This means the agent "
            "withstood *this catalogue*, not that it is safe — the harness cannot prove the "
            "absence of a vulnerability."
        )
    else:
        lines.append("No attack produced a usable verdict. There is no evidence either way.")

    lines += [
        "",
        f"Weighted by severity: {score.weighted_resisted} resisted of "
        f"{score.weighted_resolved} resolved. "
        f"Counts — passed {score.passed}, failed {score.failed}, "
        f"unknown {score.unknown}, error {score.errored}.",
        "",
    ]
    return lines


def _family_table(result: RunResult) -> list[str]:
    lines = [
        "## By family",
        "",
        "| Family | Run | Resisted | Succeeded | Unresolved | Worst |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in family_breakdown(result.records):
        worst = str(row.worst_severity) if row.worst_severity else "—"
        lines.append(
            f"| {row.family.replace('_', ' ')} | {row.run} | {row.passed} | "
            f"{row.failed} | {row.unresolved} | {worst} |"
        )
    lines.append("")
    return lines


def _failures(result: RunResult, attacks_by_id: dict[str, Attack]) -> list[str]:
    failures = sort_failures(result.records)
    if not failures:
        return []

    lines = ["## Failures", "", "Worst severity first.", ""]
    for record in failures:
        attack = attacks_by_id.get(record.attack_id)
        lines.append(f"### {record.attack_id} — {record.title}")
        lines.append("")
        lines.append(f"**{record.severity}** · {record.family.replace('_', ' ')}")
        lines.append("")

        if attack is not None and attack.real_world_analogue:
            lines.append(f"*Why this matters:* {attack.real_world_analogue}")
            lines.append("")

        lines.append("**What the mandate allowed**")
        lines.append("")
        lines.append(_mandate_summary(result))
        lines.append("")

        lines.append("**What the agent attempted**")
        lines.append("")
        for attempt in record.attempts:
            lines.append(
                f"- {attempt.display_amount} to `{attempt.merchant_name}` "
                f"[{attempt.merchant_id or 'unresolved'}]"
                + (f", category `{attempt.category}`" if attempt.category else "")
                + (", human-approved" if attempt.human_approved else "")
            )
        if not record.attempts:
            lines.append("- (no payment attempt recorded)")
        lines.append("")

        lines.append("**Checks that fired**")
        lines.append("")
        for violation in record.violations:
            lines.append(f"- `{violation.predicate}` — {violation.detail}")
        lines.append("")

        if attack is not None and attack.injections:
            lines.append("**What was injected**")
            lines.append("")
            for injection in attack.injections:
                lines.append(f"Into `{injection.tool}` (provenance `{injection.provenance}`):")
                lines.append("")
                lines.append("> " + truncate(injection.payload, 600))
                lines.append("")

        lines.extend(_excerpt_block(record))
        lines.append(
            f"Reproduce: `gauntlet run --agent {result.agent_name} "
            f"--attack {record.attack_id} --verbose`"
        )
        lines.append("")
    return lines


def _excerpt_block(record: AttackRecord) -> list[str]:
    window = excerpt(record.transcript)
    if not window:
        return []

    lines = ["**Where it turned**", "", "```text"]
    previous: int | None = None
    for message, is_pivot in window:
        # The causing tool result can sit outside the contiguous window; mark the
        # gap so nobody reads two distant messages as adjacent.
        if previous is not None and message.index > previous + 1:
            lines.append(f"     … {message.index - previous - 1} message(s) omitted …")
        previous = message.index

        marker = ">>>" if is_pivot else "   "
        lines.append(f"{marker} [{message.index:>2}] {_label(message)}")
        body = (
            truncate_middle(message.content)
            if message.role is Role.TOOL_RESULT
            else truncate(message.content, 320)
        )
        for chunk in _wrap(body, 92):
            lines.append(f"        {chunk}")
    lines.append("```")
    lines.append("")
    lines.append(
        "The marked line is where the agent's behaviour changed in response to the "
        "content above it."
    )
    lines.append("")
    return lines


def _label(message: Message) -> str:
    parts = [str(message.role)]
    if message.tool:
        parts.append(f"tool={message.tool}")
    if message.provenance is not None:
        parts.append(f"provenance={message.provenance}")
    return " · ".join(parts)


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines or [""]


def _mandate_summary(result: RunResult) -> str:
    mandate = result.mandate
    return (
        f"Per transaction {format_minor(mandate.per_transaction_cap_minor, mandate.currency)}; "
        f"per day {format_minor(mandate.daily_cap_minor, mandate.currency)}; "
        f"at most {mandate.velocity.max_payments} payments per "
        f"{mandate.velocity.window_seconds}s; "
        f"payable merchants {sorted(mandate.allowed_merchant_ids) or 'any'}."
    )


def _unresolved(result: RunResult) -> list[str]:
    records = unresolved(result.records)
    if not records:
        return []

    lines = [
        "## Unresolved",
        "",
        "These produced no usable verdict and are excluded from the score in both the "
        "numerator and the denominator. They are not passes.",
        "",
    ]
    for record in records:
        reason = record.unknown_reason or record.error or "no reason recorded"
        lines.append(f"- **{record.attack_id}** ({record.verdict}) — {reason}")
    lines.append("")
    return lines


def _all_attacks_table(result: RunResult) -> list[str]:
    lines = [
        "## All attacks",
        "",
        "| ID | Family | Severity | Verdict | Checks fired | ms |",
        "|---|---|---|---|---|---:|",
    ]
    for record in sorted(result.records, key=lambda r: r.attack_id):
        fired = ", ".join(f"`{p}`" for p in record.predicates_fired) or "—"
        lines.append(
            f"| {record.attack_id} | {record.family.replace('_', ' ')} | {record.severity} | "
            f"{_VERDICT_MARK[record.verdict]} | {fired} | {record.duration_ms} |"
        )
    lines.append("")
    return lines


def _footer(result: RunResult) -> list[str]:
    return [
        "---",
        "",
        "A `PASS` means the agent resisted *this* attack. It is not a proof of safety: this "
        "catalogue is a set of hand-written scenarios, not an exhaustive search.",
        "",
        f"Regenerate this report from the append-only ledger: `gauntlet report {result.run_id}`",
        "",
    ]


def write(result: RunResult, path: Path, *, attacks_by_id: dict[str, Attack] | None = None) -> Path:
    """Write ``report.md``.

    Raises:
        LedgerError: if the file cannot be written.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(result, attacks_by_id=attacks_by_id), encoding="utf-8")
    except OSError as exc:
        raise LedgerError(f"cannot write Markdown report to {path}: {exc}") from exc
    return path


def render_comparison(results: Sequence[RunResult]) -> str:
    """A side-by-side table across agents. The before/after the demo is built on."""
    if not results:
        return "No runs to compare.\n"

    ids = sorted({r.attack_id for result in results for r in result.records})
    header = "| Attack | Severity | " + " | ".join(f"`{r.agent_name}`" for r in results) + " |"
    divider = "|---|---|" + "|".join(["---"] * len(results)) + "|"

    lines = ["# Agent comparison", "", header, divider]
    for attack_id in ids:
        cells: list[str] = []
        severity = ""
        for result in results:
            record = next((r for r in result.records if r.attack_id == attack_id), None)
            if record is None:
                cells.append("—")
                continue
            severity = str(record.severity)
            cells.append(_VERDICT_MARK[record.verdict])
        lines.append(f"| {attack_id} | {severity} | " + " | ".join(cells) + " |")

    lines.append(
        "| **Safety score** | | " + " | ".join(f"**{r.score.display}**" for r in results) + " |"
    )
    lines.append("")
    return "\n".join(lines) + "\n"
