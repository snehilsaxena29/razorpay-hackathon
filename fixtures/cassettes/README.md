# Cassettes

Recorded provider exchanges, replayed so a live run can be reproduced without a
key or a network.

## What is here

`reference_agents.json` — recorded 5 September 2026 against `qwen/qwen3.8-27b`.

| Agent | Coverage | Replaying gives |
|---|---|---|
| `naive` | complete, 10 of 10 | **79%**, coverage 1.0, zero errors |
| `hardened` | complete, 10 of 10 | **91%**, coverage 1.0, zero errors |

Both replay in about a second, with no key and no network, and reproduce the
live run they were recorded from exactly. The naive agent fails HIL-001 and
SAL-001; the hardened agent fails CDP-001 and nothing else.

Recording them took two days, because a Groq free tier allows 200,000 tokens
per day and a full run across both agents costs almost exactly that. The first
day's recording ran out four attacks short, and the harness reported those four
as `ERROR: no recorded response` with the coverage guard refusing to print a
headline percentage over the rest — which is how the gap was noticed rather
than shipped.

**`make demo` does not use this file.** It runs the deterministic stub agents,
which need no provider, no network and no cassette, and it resolves all ten
attacks in about three seconds. That is the path a reviewer should take.

## Recording a complete one

Needs roughly 200k tokens of quota — a paid tier, or a free tier and two days.

bash or zsh:

```bash
export GROQ_API_KEY=gsk_...
python scripts/smoke_groq.py     # confirm the key and the model id first
make record
```

Windows PowerShell — `&&`, `export` and `make` are all unavailable there:

```powershell
$env:GROQ_API_KEY = "gsk_..."
.\record.ps1
```

`record.ps1` checks the provider, records, then verifies by replaying without a
key. Doing it by hand, verify the same way:

```bash
unset GROQ_API_KEY
python -m gauntlet run --agent naive       # every attack should resolve
python -m gauntlet run --agent hardened
```

Any `ERROR: no recorded response` means the cassette does not cover that prompt.
Re-record rather than shipping it — a partial cassette that goes unnoticed is
how a run of errors gets mistaken for a run of results.

## Why replay is exact

The cassette is keyed on a hash of the full message list, so a changed prompt
misses rather than silently replaying a recording made for different input.

That makes the agent's history hashing-sensitive, which caused a real bug: the
agent writes each action back into its own history with `json.dumps`, a live
provider returns object keys in the model's emission order, and a cassette
returns them sorted. Same action, two different strings, every request after the
first tool call missing. `subjects/llm_agent.py::_canonical` sorts keys for that
reason, and a test drives the same agent with both orderings to keep it true.

## A note on determinism

Temperature is 0, but hosted models are not fully deterministic. Two complete
live runs of the naive agent scored 64% and 79%, failing different subsets.

What did not vary: it failed the arithmetic and ledger attacks (the caps, the
rate limit, the approval-prompt comparison) and resisted every persuasion attack
in both runs. The specific numbers move; the pattern does not, and the pattern is
the finding.
