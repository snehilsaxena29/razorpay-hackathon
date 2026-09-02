"""The append-only run log. Every report in this tool is a projection of it.

Two properties matter, and both are about what survives a bad day:

- **Durable.** Every record is flushed and ``fsync``-ed before the write returns.
  A ``SIGKILL`` mid-run leaves a valid, readable, partial ledger rather than an
  empty file with everything still sitting in a buffer.
- **Append-only.** Nothing is ever rewritten. The report can be regenerated from
  the ledger at any time, which means the ledger — not the report — is the
  audit trail.

If the ledger cannot be written, the run does not start. A run with no audit
trail is not a run.
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from gauntlet.errors import LedgerError

LEDGER_FILENAME = "ledger.jsonl"


def new_run_id() -> str:
    """A sortable, collision-resistant run id, e.g. ``run_20260904T110219_3f8b``.

    Sortable because operators list run directories and expect chronological
    order; suffixed because two runs started in the same second must not
    silently share a directory.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    return f"run_{stamp}_{secrets.token_hex(2)}"


class Ledger:
    """Append-only JSONL writer for one run.

    Use as a context manager so the file is closed even when the run raises.
    """

    def __init__(self, path: Path, *, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = path.open("a", encoding="utf-8", newline="\n")
        except OSError as exc:
            raise LedgerError(f"cannot open ledger at {path}: {exc}") from exc
        self._closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def write(self, record_type: str, **fields: Any) -> None:
        """Append one record and force it to disk before returning.

        Raises:
            LedgerError: if the record cannot be serialised or written. Fatal —
                a safety tool that loses its audit trail should stop, not carry
                on producing unverifiable verdicts.
        """
        if self._closed:
            raise LedgerError("ledger is closed")

        record = {
            "ts": datetime.now(UTC).isoformat(),
            "type": record_type,
            "run_id": self.run_id,
            **fields,
        }
        try:
            line = json.dumps(record, ensure_ascii=False, default=_fallback_encoder)
        except (TypeError, ValueError) as exc:
            raise LedgerError(f"cannot serialise {record_type} record: {exc}") from exc

        try:
            self._handle.write(line + "\n")
            self._handle.flush()
            os.fsync(self._handle.fileno())
        except OSError as exc:
            raise LedgerError(f"cannot write to ledger {self.path}: {exc}") from exc

    def close(self) -> None:
        """Close the underlying file. Idempotent."""
        if not self._closed:
            self._handle.close()
            self._closed = True


def read_ledger(path: Path) -> Iterator[dict[str, Any]]:
    """Yield records from a ledger, tolerating a truncated final line.

    A process killed mid-write leaves a partial last line. Skipping it — and
    only it — recovers everything that was durably written. A malformed line
    anywhere *other* than the end is a corrupted ledger and raises, because
    silently dropping records from the middle of an audit trail would be exactly
    the kind of quiet degradation this tool exists to catch.

    Raises:
        LedgerError: if the file cannot be read, or a non-final line is malformed.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LedgerError(f"cannot read ledger {path}: {exc}") from exc

    lines = [line for line in raw.split("\n") if line.strip()]
    for i, line in enumerate(lines):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            if i == len(lines) - 1:
                # Truncated tail from a hard kill. Everything before it is intact.
                return
            raise LedgerError(f"{path}: malformed record on line {i + 1}: {exc}") from exc
        yield parsed


def records_of_type(path: Path, record_type: str) -> list[dict[str, Any]]:
    """Every record of one type, in write order."""
    return [r for r in read_ledger(path) if r.get("type") == record_type]


def _fallback_encoder(value: Any) -> Any:
    """Serialise the few non-JSON types that reach the ledger.

    Deliberately narrow. Anything not listed here raises, rather than being
    stringified into a blob that looks like data but cannot be read back — a
    ledger you cannot parse is a ledger you do not have.

    Sets are sorted so two runs with the same content produce identical bytes.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, frozenset | set):
        return sorted(str(v) for v in value)
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"{type(value).__name__} is not JSON-serialisable")
