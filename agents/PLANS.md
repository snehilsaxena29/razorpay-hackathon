# PLANS.md — Two-Day Execution Plan

**Project:** `gauntlet` — an adversarial test harness for payment agents.
**Submission:** Razorpay AI Buildathon 2026. Deadline 5 Sep. **We submit 4 Sep.**
**Time available:** 2 working days (3 Sep, 4 Sep). One person.

---

## 1. The bet

We ship one narrow thing, complete: a CLI that points at a payment-capable agent, runs a
catalogue of 10 attacks against it, and reports which ones caused an unauthorised payment
attempt. Two reference agents ship with it — a naive one that fails most attacks and a
hardened one that resists most. The demo is the before/after.

The thesis of the pitch, in one sentence: **you cannot prompt your way to payment safety —
you need a deterministic gate in code, and a harness that proves it works.** Every design
decision below serves that sentence.

## 2. Hard rules

| # | Rule | Why |
|---|------|-----|
| R1 | **Submit by 20:00 IST on 4 Sep.** The 5th is not a work day, it is the day something goes wrong. | Deadline risk is the single biggest killer of hackathon submissions. |
| R2 | **Feature freeze at 13:00 on 4 Sep.** After that: docs, video, polish, bugfixes only. | The last seven hours are always needed and always underestimated. |
| R3 | Every work block ends with `make demo` green and a commit. Never leave the repo broken overnight. | A broken repo at 23:00 on Day 1 costs Day 2's morning. |
| R4 | If a task overruns its box by more than 45 minutes, take the next scope cut in §6. Do not negotiate with yourself. | The cut list exists so the decision is already made. |
| R5 | The public repo is created and pushed in the **first hour**, not the last. | A repo that exists from hour one cannot be forgotten at hour twenty. |
| R6 | We never tune an attack to make a reference agent's score look better. The report prints what happened. | If the harness is rigged, the whole submission is worthless. |

## 3. What each artifact is scoring

| Artifact | Problem Taste | Build Quality | AI Judgment | Failure Recovery |
|---|:---:|:---:|:---:|:---:|
| Attack catalogue grounded in real incidents (SPECS §5) | ●●● | ● | | |
| Deterministic core, LLM confined to two call sites | | ●● | ●●● | |
| Mandate as declarative ground truth | ●● | ●●● | | |
| Circuit breaker → `UNKNOWN`, never a guess | | ● | ●●● | ●●● |
| Append-only fsync'd ledger, report regenerable from it | | ●● | | ●●● |
| Per-attack isolation + episode timeouts | | ●● | | ●●● |
| `make demo` works with no API key (replay mode) | ● | ●● | | ●●● |
| Hardened agent still fails one attack, honestly reported | ●●● | | ●● | ● |

## 4. Day 1 — Wednesday 3 September

**Theme: the skeleton must run end to end by lunch. Everything after is filling it in.**

| Block | Task | Done when |
|---|---|---|
| 08:00–08:45 | `git init`, public GitHub repo, `pyproject.toml`, `Makefile` skeleton, `ruff`/`mypy` config, CI workflow running `make ci`. Push. | CI green on an empty-but-valid repo. |
| 08:45–09:15 | **Groq smoke test.** One script, one call, print the response. Confirm the model id and the key work *today*. | A real completion printed. If the key is dead, this is the hour to find out — not at 22:00. |
| 09:15–11:00 | Core models: `mandate.py`, `sink.py`, `agent.py`, `context.py`. Dataclasses only, no I/O, fully typed. Unit tests alongside. | `pytest tests/unit` green; `Mandate` loads from TOML; `RecordingSink` captures a `PaymentAttempt`. |
| 11:00–12:30 | `judge/deterministic.py` — cap, daily cap, denylist, velocity, merchant identity, HITL divergence. Pure functions. This is the heart; test it hard. | 100% line coverage on this module. Every check has a passing and a failing case. |
| 12:30–13:15 | Lunch. Do not skip it. | |
| 13:15–15:00 | `runner.py`, `ledger.py`, `attacks/base.py` and the registry. One trivial attack wired end to end. | `gauntlet run --agent stub --attack DPI-001` writes a JSONL record and exits 1. |
| 15:00–17:00 | **Naive agent** (`subjects/naive.py`): Groq tool-calling loop, tools from `ToolContext`, no provenance handling, no pre-flight gate. | Naive agent completes a live episode and submits a payment to the sink. |
| 17:00–19:00 | Attacks **DPI-001, DPI-002, IDI-001, IDI-002, IDI-003, SPF-001** with their paired stub tests. | 6 attacks in the registry; `make test` green offline. |
| 19:00–20:30 | `report/json_report.py`, `report/markdown_report.py`, `report/console.py`. Transcript excerpt extraction. | `make demo` runs naive against 6 attacks, prints a coloured table, writes `runs/<id>/report.md`. |
| 20:30–21:00 | **Record the cassettes** for replay mode from today's live runs. Commit them. | `GAUNTLET_MODE=replay make demo` works with `GROQ_API_KEY` unset. |

**Day 1 definition of done:** on a clean clone with no API key, `make demo` runs the naive
agent against 6 attacks, prints a red table, and writes a markdown report containing at least
one transcript excerpt showing the exact turn where the agent obeyed hostile content.

If Day 1 ends without that, take cuts C1 and C2 tomorrow morning before anything else.

## 5. Day 2 — Thursday 4 September

**Theme: the contrast, the resilience story, and the submission. Freeze at 13:00.**

| Block | Task | Done when |
|---|---|---|
| 08:00–10:30 | **Hardened agent** (`subjects/hardened.py`): provenance-tagged context, deterministic pre-flight mandate gate in front of the sink, NFKC + confusables merchant normalisation against an ID allowlist, running daily/velocity ledger, approval prompt rendered from the `PaymentAttempt` struct. | Hardened agent passes at least 5 of the 6 Day-1 attacks. |
| 10:30–11:30 | Attacks **SAL-001, SAL-002, HIL-001, CDP-001** and their paired tests. Catalogue now 10. | `make test` green; naive and hardened visibly diverge on the table. |
| 11:30–12:30 | `judge/semantic.py` and `llm/` — the LLM category judge: structured output only, injection-hardened prompt, bounded retries, **circuit breaker → `UNKNOWN`**. | Kill the network mid-run: deterministic attacks still complete, semantic ones report `UNKNOWN`, exit code 2, report header says `DEGRADED`. |
| 12:30–13:00 | Resilience sweep: episode timeouts, per-attack `except Exception` → verdict `ERROR` with traceback in the ledger, fsync on ledger write, `gauntlet report <run_id>` regeneration. | Hard-kill the process mid-run, then regenerate a valid partial report from the ledger alone. |
| **13:00** | **FEATURE FREEZE.** | No new modules after this line. |
| 13:00–14:00 | Lunch, then a full clean-clone rehearsal: `git clone`, `make setup`, `make demo`, timed. Must be under 4 minutes. | Timed and under budget on a fresh clone. |
| 14:00–15:30 | `README.md` (the reviewer's four minutes: what, why, one command, one screenshot of the report) and `docs/ARCHITECTURE.md` (the architecture doc deliverable). | Both written, both accurate, diagram included. |
| 15:30–17:00 | **Record the video.** Script in §8. Expect three takes. | 5:00 or under, uploaded, link tested in an incognito window. |
| 17:00–18:30 | Buffer. Reserved for whatever broke. If nothing broke, add stretch attacks DPI-003 and SPF-002. | — |
| 18:30–19:30 | Final pass: repo hygiene (no `.env`, no `runs/`, LICENSE present, clean history), README links resolve, video link resolves, architecture doc matches the code. | §7 checklist fully ticked. |
| 19:30–20:00 | **Submit.** | Confirmation received and screenshotted. |

**Day 2 definition of done:** the §7 checklist is fully ticked and the submission is in.

## 6. The scope cut — decided now, in this order

Take these from the top when you fall behind. Do not invent a new cut in the moment.

| # | Cut | Costs us | Take it when |
|---|---|---|---|
| C1 | Drop **CDP-001** (confused deputy). Catalogue becomes 9. | One family, and the "hardened agent honestly fails one" moment. Replace that beat with SAL-002. | 11:30 on Day 2 and the hardened agent isn't working. |
| C2 | Drop the **semantic LLM judge**. All attacks judged deterministically. | The AI-judgment argument weakens, but does not vanish — the agents under test are still LLMs. Say so in the video. | 12:30 on Day 2. |
| C3 | Drop **live mode from the demo**. `make demo` runs replay-only; live mode still exists and is documented. | Nothing visible to the reviewer, provided the cassettes are honest recordings. | Groq is flaky or the key dies. |
| C4 | Drop the **hardened agent's LLM loop** — make it a deterministic policy agent over the same tools. | The before/after stops being like-for-like. Must be stated in the README; hiding it would be dishonest. | 10:30 on Day 2 with no working hardened agent. |
| C5 | Cut the catalogue to **6 attacks** (Day 1's set only). | Two families. | Day 2 morning is already lost. |

**Never cut:** the deterministic judge's tests, the append-only ledger, the degraded-mode
path, the README, or the video. Those are the submission.

**Explicitly out of scope from the start** — these are not cuts, they are things we never
start: web UI, multi-provider LLM support, parallel or async attack execution, a plugin
system, Docker, database persistence, agent-framework adapters (LangChain, CrewAI), attack
mutation or fuzzing, PDF reports.

## 7. Submission checklist

**Repo**
- [ ] Public on GitHub, descriptive name, one-paragraph description, topics set
- [ ] `README.md`: problem in three sentences → one command → screenshot of the report → how to point it at your own agent
- [ ] LICENSE (MIT)
- [ ] `make setup && make demo` works on a clean clone **with no API key**
- [ ] CI green on `main`
- [ ] No secrets, no `runs/` artifacts, no `.env` committed
- [ ] `agents/` planning docs included — they are evidence of Build Quality, keep them

**Architecture doc** — `docs/ARCHITECTURE.md`
- [ ] The trust model: what is trusted, what is attacker-controlled, where the boundary sits
- [ ] Component diagram (mandate → runner → agent → sink → judge → ledger → report)
- [ ] **AI-judgment section**: the two LLM call sites, and why everything else is arithmetic
- [ ] **Failure-recovery section**: circuit breaker, `UNKNOWN`, exit codes, ledger replay
- [ ] Known limitations, honestly stated (§10)

**Video** — 5:00 hard cap
- [ ] Terminal legible at 1080p (font 18pt or larger), no personal information on screen
- [ ] A real run, not a mock-up
- [ ] Link tested while logged out

## 8. Video shot list (5:00)

| Time | Beat |
|---|---|
| 0:00–0:40 | The problem. Agents are being handed the ability to spend money; NPCI is building the rails for it now. There is a documented case of an agent paying ₹2,500 for a course because an Instagram post told it to. Today you find out your agent is unsafe in production. |
| 0:40–1:05 | The thesis. You cannot prompt your way to payment safety. Put the claim on screen. |
| 1:05–2:15 | `make demo`. Naive agent. Watch the table go red. Land on the safety score. |
| 2:15–3:15 | Open `report.md`. Walk **one** failure: the mandate allowed X, the agent attempted Y, and here is the transcript excerpt with the exact turn where a web page changed its behaviour. This is the money shot — do not rush it. |
| 3:15–4:10 | Hardened agent. Table goes green. Name the three defences: provenance tagging, the deterministic pre-flight gate, merchant normalisation. Point at the one attack it *still* fails and say why we left it in. |
| 4:10–4:45 | Architecture in twenty seconds: deterministic core, LLM at exactly two places, `UNKNOWN` instead of a guess when the provider is down. Show the degraded run. |
| 4:45–5:00 | `gauntlet run --agent http --url <your agent>`. Repo link. Stop talking. |

## 9. Risk register

| Risk | Likelihood | Mitigation (already in the plan) |
|---|---|---|
| Groq key or model unavailable on Day 2 | Medium | Cassettes recorded end of Day 1 (C3). `make demo` never depends on the network. |
| The naive agent doesn't actually fail — the model is too well-aligned to be tricked | Medium | Attacks target *mandate arithmetic* (caps, velocity, homoglyphs), not only persuasion. A well-aligned model still overspends a cap it was never shown. If it resists anyway, that is a finding: report it, don't fake it. |
| Hardened agent passes 10/10 and looks rigged | Medium | CDP-001 is designed to be genuinely hard. Keep it. A 100% score is less credible than a 90% one. |
| Video overruns and eats the buffer | High | Scheduled at 15:30 with 90 minutes, and 90 minutes of buffer behind it. Script written in advance (§8). |
| `make` unavailable on Windows | High (this machine) | Ship `python -m gauntlet demo` and `demo.ps1` as first-class equivalents. Test both on Day 1. |
| Scope creep into a web UI or a second provider | Medium | The out-of-scope list in §6. Re-read it at every block boundary. |

## 10. Known limitations to state, not hide

Put these in the README and say one of them out loud in the video. Naming your own limits
reads as judgment; having them found for you reads as sloppiness.

1. The catalogue is ten hand-written attacks, not a fuzzer. Coverage is illustrative, not exhaustive.
2. The reference agents are simple loops, not production agent frameworks.
3. A `PASS` means "resisted this attack", not "safe". The harness cannot prove the absence of a vulnerability.
4. The semantic judge is an LLM and can be wrong. That is why it is confined to category questions and returns `UNKNOWN` rather than guessing.
