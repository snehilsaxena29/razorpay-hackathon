"""End-to-end runs through the CLI.

Exit codes are part of the contract: CI gates on 1 and alerts on 2, and
conflating "this agent is unsafe" with "we could not tell" would defeat the
point of the tool. Each code gets a test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gauntlet.cli import main
from gauntlet.errors import ExitCode


@pytest.fixture(autouse=True)
def replay_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runs here never reach a provider, exactly as on a reviewer's machine."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("GAUNTLET_MODE", "replay")


def _run(args: list[str], out_dir: Path) -> int:
    return main([*args, "--out-dir", str(out_dir)])


def test_unsafe_agent_exits_one(tmp_path: Path) -> None:
    code = _run(["run", "--agent", "naive-stub", "--family", "merchant_spoofing"], tmp_path)
    assert code == ExitCode.UNSAFE


def test_clean_run_exits_zero(tmp_path: Path) -> None:
    code = _run(["run", "--agent", "hardened-stub", "--family", "merchant_spoofing"], tmp_path)
    assert code == ExitCode.CLEAN


def test_degraded_run_exits_two(tmp_path: Path) -> None:
    """CDP-001 with no provider is UNKNOWN, which is neither clean nor unsafe."""
    code = _run(["run", "--agent", "hardened-stub", "--attack", "CDP-001"], tmp_path)
    assert code == ExitCode.DEGRADED


def test_failures_dominate_unknowns(tmp_path: Path) -> None:
    """A run with both a FAIL and an UNKNOWN reports UNSAFE.

    "We found a vulnerability" is the more actionable of the two facts.
    """
    code = _run(["run", "--agent", "naive-stub"], tmp_path)
    assert code == ExitCode.UNSAFE


def test_unknown_agent_exits_three(tmp_path: Path) -> None:
    assert _run(["run", "--agent", "no-such-agent"], tmp_path) == ExitCode.CANNOT_START


def test_unknown_attack_exits_three(tmp_path: Path) -> None:
    assert _run(["run", "--agent", "naive-stub", "--attack", "XXX-999"], tmp_path) == (
        ExitCode.CANNOT_START
    )


def test_missing_mandate_exits_three(tmp_path: Path) -> None:
    code = main(
        ["run", "--agent", "naive-stub", "--mandate", "nope.toml", "--out-dir", str(tmp_path)]
    )
    assert code == ExitCode.CANNOT_START


def test_live_mode_without_a_key_refuses_rather_than_downgrading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A report whose header says LIVE when nothing was live is a report that lies."""
    monkeypatch.setenv("GAUNTLET_MODE", "live")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert _run(["run", "--agent", "naive-stub"], tmp_path) == ExitCode.CANNOT_START


# ---- artifacts -------------------------------------------------------------


def _only_run_dir(out_dir: Path) -> Path:
    dirs = [p for p in out_dir.iterdir() if p.is_dir()]
    assert len(dirs) == 1
    return dirs[0]


def test_run_writes_ledger_and_both_reports(tmp_path: Path) -> None:
    _run(["run", "--agent", "naive-stub", "--attack", "SPF-001"], tmp_path)
    run_dir = _only_run_dir(tmp_path)
    assert (run_dir / "ledger.jsonl").exists()
    assert (run_dir / "report.json").exists()
    assert (run_dir / "report.md").exists()


def test_json_report_has_the_documented_shape(tmp_path: Path) -> None:
    _run(["run", "--agent", "naive-stub", "--attack", "SPF-001"], tmp_path)
    payload = json.loads((_only_run_dir(tmp_path) / "report.json").read_text(encoding="utf-8"))

    assert payload["schema_version"] == "1.0"
    assert payload["run"]["mode"] == "REPLAY"
    assert payload["agent"]["name"] == "naive-stub"
    assert payload["summary"]["counts"]["failed"] == 1
    attack = payload["attacks"][0]
    assert attack["attack_id"] == "SPF-001"
    assert "homoglyph_collision" in attack["predicates_fired"]
    assert attack["transcript_excerpt"], "a failure with no excerpt is an assertion, not evidence"


def test_markdown_report_shows_the_turning_point(tmp_path: Path) -> None:
    _run(["run", "--agent", "naive-stub", "--attack", "IDI-001"], tmp_path)
    report = (_only_run_dir(tmp_path) / "report.md").read_text(encoding="utf-8")

    assert "Safety score" in report
    assert "Where it turned" in report
    assert ">>>" in report, "the excerpt must mark where the agent changed course"
    assert "AGENT INSTRUCTION" in report, "the injected payload must be visible"
    assert "Reproduce:" in report


def test_markdown_report_lists_unresolved_separately(tmp_path: Path) -> None:
    """UNKNOWN is never folded into the pass column."""
    _run(["run", "--agent", "hardened-stub", "--attack", "CDP-001"], tmp_path)
    report = (_only_run_dir(tmp_path) / "report.md").read_text(encoding="utf-8")
    assert "## Unresolved" in report
    assert "DEGRADED" in report
    assert "n/a" in report, "no resolved attacks means no score, not a zero"


def test_replay_mode_is_declared_in_the_report(tmp_path: Path) -> None:
    """A replayed run is never presented as a live one."""
    _run(["run", "--agent", "naive-stub", "--attack", "SPF-001"], tmp_path)
    report = (_only_run_dir(tmp_path) / "report.md").read_text(encoding="utf-8")
    assert "Mode: REPLAY" in report


def test_compare_runs_both_agents(tmp_path: Path) -> None:
    code = _run(
        ["compare", "--agents", "naive-stub,hardened-stub", "--family", "salami_slicing"],
        tmp_path,
    )
    assert code == ExitCode.UNSAFE
    assert len([p for p in tmp_path.iterdir() if p.is_dir()]) == 2


def test_demo_runs_without_a_key(tmp_path: Path) -> None:
    """The four-minute path, on a clean clone with no provider."""
    assert _run(["demo"], tmp_path) == ExitCode.UNSAFE


def test_report_command_regenerates_from_the_ledger(tmp_path: Path) -> None:
    """The report is a projection of the log, not the source of truth."""
    _run(["run", "--agent", "naive-stub", "--attack", "SPF-001"], tmp_path)
    run_id = _only_run_dir(tmp_path).name
    assert main(["report", run_id, "--out-dir", str(tmp_path)]) == ExitCode.CLEAN


def test_report_command_on_a_missing_run_exits_three(tmp_path: Path) -> None:
    assert main(["report", "run_nope", "--out-dir", str(tmp_path)]) == ExitCode.CANNOT_START


def test_list_commands_succeed(tmp_path: Path) -> None:
    assert main(["list", "attacks"]) == ExitCode.CLEAN
    assert main(["list", "agents"]) == ExitCode.CLEAN
