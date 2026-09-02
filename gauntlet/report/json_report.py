"""The machine-readable report. A projection of the ledger, never the source of truth.

Written with ``schema_version`` so a consumer can tell whether it understands
the file. The run block carries mode, degraded state and provider status, so a
report can never be mistaken for something it is not: a replayed run and a live
one look different at the top of the file, deliberately.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gauntlet import __version__
from gauntlet.attacks.base import Attack
from gauntlet.errors import LedgerError
from gauntlet.report.summary import excerpt, family_breakdown, truncate
from gauntlet.runner import AttackRecord, RunResult

SCHEMA_VERSION = "1.0"


def build(result: RunResult, *, attacks_by_id: dict[str, Attack] | None = None) -> dict[str, Any]:
    """Assemble the full JSON report for one run."""
    attacks_by_id = attacks_by_id or {}
    score = result.score

    return {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "run_id": result.run_id,
            "started_at": result.started_at.isoformat(),
            "finished_at": result.finished_at.isoformat(),
            "duration_s": round(result.duration_s, 2),
            "mode": result.mode,
            "degraded": score.is_degraded,
            "gauntlet_version": __version__,
            "llm": {"status": result.llm_status},
            "ledger": str(result.ledger_path) if result.ledger_path else None,
        },
        "agent": {"name": result.agent_name},
        "mandate": result.mandate.to_dict(),
        "summary": score.to_dict(),
        "by_family": [row.to_dict() for row in family_breakdown(result.records)],
        "attacks": [
            _attack_block(record, attacks_by_id.get(record.attack_id))
            for record in sorted(result.records, key=lambda r: r.attack_id)
        ],
    }


def _attack_block(record: AttackRecord, attack: Attack | None) -> dict[str, Any]:
    """One attack's entry, including the evidence that makes it checkable."""
    block: dict[str, Any] = record.to_dict()
    block["transcript_excerpt"] = [
        {**message.to_dict(), "turned_here": is_pivot}
        for message, is_pivot in excerpt(record.transcript)
    ]
    if attack is not None:
        block["injections"] = [
            {
                "tool": injection.tool,
                "match": injection.match,
                "provenance": str(injection.provenance),
                "payload": truncate(injection.payload, 600),
            }
            for injection in attack.injections
        ]
        block["real_world_analogue"] = attack.real_world_analogue
        block["turns"] = list(attack.turns)
    return block


def write(result: RunResult, path: Path, *, attacks_by_id: dict[str, Attack] | None = None) -> Path:
    """Write ``report.json`` beside the ledger.

    Raises:
        LedgerError: if the report cannot be written. The run's findings are
            already durable in the ledger, so this is recoverable with
            ``gauntlet report <run_id>`` — but it must still be loud.
    """
    payload = build(result, attacks_by_id=attacks_by_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        raise LedgerError(f"cannot write JSON report to {path}: {exc}") from exc
    return path
