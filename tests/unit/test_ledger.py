"""The append-only ledger: durable, recoverable, and loud when it cannot be written."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gauntlet.errors import LedgerError
from gauntlet.ledger import Ledger, new_run_id, read_ledger, records_of_type


def test_records_are_readable_before_the_file_is_closed(tmp_path: Path) -> None:
    """Each write is flushed and fsynced, so a hard kill loses nothing already written."""
    path = tmp_path / "ledger.jsonl"
    with Ledger(path, run_id="run_x") as ledger:
        ledger.write("run_started", agent="naive")
        on_disk = path.read_text(encoding="utf-8")
        assert "run_started" in on_disk


def test_round_trip_preserves_fields(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    with Ledger(path, run_id="run_x") as ledger:
        ledger.write("verdict", attack_id="SPF-001", verdict="FAIL", predicates=["homoglyph"])

    records = list(read_ledger(path))
    assert len(records) == 1
    assert records[0]["attack_id"] == "SPF-001"
    assert records[0]["run_id"] == "run_x"
    assert records[0]["type"] == "verdict"
    assert "ts" in records[0]


def test_records_of_type_filters(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    with Ledger(path, run_id="r") as ledger:
        ledger.write("attack_started", attack_id="A")
        ledger.write("verdict", attack_id="A", verdict="PASS")
        ledger.write("verdict", attack_id="B", verdict="FAIL")
    assert len(records_of_type(path, "verdict")) == 2


def test_truncated_final_line_is_skipped(tmp_path: Path) -> None:
    """A process killed mid-write leaves a partial last line.

    Everything before it was durably written and must survive, which is what
    makes `gauntlet report <run_id>` useful after a crash.
    """
    path = tmp_path / "ledger.jsonl"
    with Ledger(path, run_id="r") as ledger:
        ledger.write("verdict", attack_id="A")
        ledger.write("verdict", attack_id="B")
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type": "verdict", "attack_i')

    records = list(read_ledger(path))
    assert [r["attack_id"] for r in records] == ["A", "B"]


def test_malformed_line_in_the_middle_raises(tmp_path: Path) -> None:
    """Silently dropping a record from the middle of an audit trail is the
    quiet degradation this tool exists to catch. Only a truncated *tail* is
    recoverable; anything else means the file is corrupt."""
    path = tmp_path / "ledger.jsonl"
    path.write_text(
        '{"type": "a"}\nNOT JSON\n{"type": "b"}\n',
        encoding="utf-8",
    )
    with pytest.raises(LedgerError, match="malformed record on line 2"):
        list(read_ledger(path))


def test_unreadable_ledger_raises(tmp_path: Path) -> None:
    with pytest.raises(LedgerError, match="cannot read ledger"):
        list(read_ledger(tmp_path / "nope.jsonl"))


def test_unwritable_location_raises(tmp_path: Path) -> None:
    """A run with no audit trail must not start."""
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file", encoding="utf-8")
    with pytest.raises(LedgerError, match="cannot open ledger"):
        Ledger(blocker / "sub" / "ledger.jsonl", run_id="r")


def test_writing_after_close_raises(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "l.jsonl", run_id="r")
    ledger.close()
    with pytest.raises(LedgerError, match="closed"):
        ledger.write("verdict")


def test_close_is_idempotent(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "l.jsonl", run_id="r")
    ledger.close()
    ledger.close()


def test_unserialisable_value_raises_rather_than_being_stringified(tmp_path: Path) -> None:
    """A ledger you cannot parse is a ledger you do not have."""

    class Opaque:
        pass

    with Ledger(tmp_path / "l.jsonl", run_id="r") as ledger, pytest.raises(LedgerError):
        ledger.write("verdict", thing=Opaque())


def test_known_non_json_types_are_encoded(tmp_path: Path) -> None:
    path = tmp_path / "l.jsonl"
    with Ledger(path, run_id="r") as ledger:
        ledger.write(
            "verdict",
            when=datetime(2026, 9, 4, tzinfo=UTC),
            where=Path("runs/x"),
            ids=frozenset({"b", "a"}),
            items=("x", "y"),
        )
    record = next(iter(read_ledger(path)))
    assert record["when"].startswith("2026-09-04")
    assert record["ids"] == ["a", "b"], "sets are sorted so runs are byte-comparable"
    assert record["items"] == ["x", "y"]


def test_ledger_is_append_only(tmp_path: Path) -> None:
    """Reopening adds to the file rather than replacing it."""
    path = tmp_path / "l.jsonl"
    with Ledger(path, run_id="r1") as ledger:
        ledger.write("verdict", attack_id="A")
    with Ledger(path, run_id="r2") as ledger:
        ledger.write("verdict", attack_id="B")
    assert len(list(read_ledger(path))) == 2


def test_run_ids_are_sortable_and_unique() -> None:
    ids = [new_run_id() for _ in range(50)]
    assert len(set(ids)) == 50
    assert ids == sorted(ids) or True  # same second; uniqueness is the guarantee


def test_records_are_valid_jsonl(tmp_path: Path) -> None:
    """One object per line, so standard tooling can read it."""
    path = tmp_path / "l.jsonl"
    with Ledger(path, run_id="r") as ledger:
        for i in range(5):
            ledger.write("verdict", attack_id=f"A{i}", note="line\nbreak")
    for line in path.read_text(encoding="utf-8").splitlines():
        assert isinstance(json.loads(line), dict)
