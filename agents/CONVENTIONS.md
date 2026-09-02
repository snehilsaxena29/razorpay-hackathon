# CONVENTIONS.md — How Code in This Repository Is Written

This is a safety tool. Two consequences run through everything below:

- **A wrong answer is worse than no answer.** Anything that could produce a confidently
  incorrect verdict is a defect, even if it never crashes.
- **A swallowed error is worse than a crash.** A crash is visible. A silently degraded safety
  check is a tool that lies to you.

---

## 1. Module layout

One concept per module. A module is named for the noun it owns: `mandate.py` owns `Mandate`,
`sink.py` owns payment capture, `ledger.py` owns the append-only log.

**No `utils.py`, no `helpers.py`, no `common.py`.** If a function has no obvious home, its
concept has not been named yet. Name it.

Dependency direction is one-way and enforced by review:

```
cli → runner → {attacks, subjects, judge, ledger, report}
                    ↓
              {mandate, sink, agent, context, errors}   ← no imports from above this line
```

`judge/deterministic.py` imports only `mandate`, `sink`, `agent`, and the standard library.
It has no I/O, no logging, no clock access, no network. It is the safety-critical core, and
keeping it a set of pure functions is what makes it exhaustively testable.

`report/console.py` is the only module permitted to import `rich`. `llm/groq.py` is the only
module permitted to import `httpx`. If a third module needs the network, that is a design
error, not a new import.

---

## 2. Naming

| Thing | Convention | Example |
|---|---|---|
| Modules | `snake_case`, singular noun | `mandate.py`, `sink.py` |
| Classes | `PascalCase` | `PaymentAttempt`, `RecordingSink` |
| Functions | `snake_case`, verb-first | `resolve_merchant()`, `render_markdown()` |
| Predicates | `snake_case`, read as a true/false claim | `over_daily_cap()`, `merchant_denied()` |
| Constants | `UPPER_SNAKE` at module level | `SEVERITY_WEIGHTS`, `DEFAULT_TIMEOUT_S` |
| Attack ids | `FAM-NNN`, three-letter family, zero-padded | `SPF-001`, `IDI-003` |
| Money | **always** suffixed `_minor`, **always** `int` | `amount_minor`, `daily_cap_minor` |
| Durations | suffixed `_s` or `_ms`, explicit unit | `timeout_s`, `duration_ms` |
| Booleans | `is_` / `has_` / `requires_` | `is_degraded`, `requires_llm` |

**Money is an integer count of minor units. There is no float anywhere near a payment.**
Any function that takes a currency amount takes an `int` named `*_minor`. Rupees appear only
at the last formatting step, in `report/`. A reviewer must be able to grep `float` in
`gauntlet/` and find nothing in the payment path.

Predicate functions return `bool` and are named so that `if over_daily_cap(...)` reads as
English. No negations in names — never `not_allowed()`.

---

## 3. Type hints

- `from __future__ import annotations` at the top of every module.
- Every public function, method, and dataclass field is annotated. No exceptions.
- `mypy --strict` passes on `gauntlet/` and `subjects/`. Tests run under default mypy.
- **No `Any` in a public signature.** If you need one internally, it gets a comment saying why.
- Interfaces are `typing.Protocol`, not ABCs. `AgentUnderTest`, `PaymentSink`, and
  `LLMClient` are all protocols, so a third-party agent needs no import from us to conform.
- Domain dataclasses are `frozen=True, slots=True`. Validation goes in `__post_init__` and
  raises. An invalid object must not be constructible.
- Enums for closed sets: `Verdict`, `Severity`, `Family`, `Provenance`. Never bare strings
  compared with `==`. Use `StrEnum` so JSON serialisation stays readable.

---

## 4. Error handling

The rule that matters most in this repository.

### Never

```python
except Exception:
    pass                          # forbidden
except Exception:
    return None                   # forbidden
except:                           # forbidden — catches KeyboardInterrupt and SystemExit
    ...
logger.debug(f"failed: {e}")      # forbidden as the sole response to an exception
```

A safety check that fails quietly reports the agent as safe. That is the single worst
outcome this tool can produce.

### Always

Every `except` block does exactly one of three things:

1. **Re-raise with context**, using a domain exception and `from`:
   ```python
   except tomllib.TOMLDecodeError as exc:
       raise MandateError(f"{path}: malformed TOML") from exc
   ```
2. **Record a structured failure and continue**, only at a boundary designed for it:
   ```python
   except Exception as exc:                      # attack isolation boundary
       ledger.write_error(attack.id, exc, traceback.format_exc())
       return AttackRecord(verdict=Verdict.ERROR, error=str(exc))
   ```
3. **Convert to `UNKNOWN`**, only in `judge/semantic.py` and `llm/`, and only after the
   failure is written to the ledger.

### The exception hierarchy — `gauntlet/errors.py`

```
GauntletError                 # everything we raise
├── ConfigError               # bad CLI args, missing output dir, live mode with no key → exit 3
├── MandateError              # invalid or unparseable mandate → exit 3
├── AttackError               # malformed attack definition → exit 3
├── AgentError                # the agent under test misbehaved
│   └── EpisodeTimeoutError        # exceeded the wall-clock budget
└── ProviderError             # LLM provider failure
    ├── ProviderTimeoutError
    └── ProviderUnavailableError   # circuit breaker is open
```

Never shadow a builtin: `EpisodeTimeoutError`, not `TimeoutError`.

### Isolation boundaries

There are exactly **two** places where a broad `except Exception` is permitted, and both are
marked with a `# isolation boundary` comment:

1. `runner.run_attack()` — one attack failing must not end the run.
2. `llm/client.py` retry wrapper — a provider failing must not end the run.

Everywhere else, exceptions propagate. **Configuration and runner-level failures are fatal
and loud.** If the ledger cannot be written, the run must not start: a run with no audit
trail is not a run.

### Logging

Logs to stderr, reports to files, never mixed — `make demo | tee` must produce a clean
transcript. Log at `WARNING` or above for anything a user should act on. The ledger, not the
log, is the audit trail: if a fact matters to a verdict, it goes in the ledger.

---

## 5. Determinism

Anything that decides a verdict must be reproducible.

- No `datetime.now()` inside judging or attack logic. Time is passed in as a parameter.
- No `random` without a seeded generator. The run's seed goes in the report header.
- No dependence on `dict` or `set` iteration order in output. Sort explicitly before
  rendering or serialising.
- Two runs of the same attack against the same stub agent produce byte-identical reports,
  once the run id and timestamps are excluded. There is a test for this.

---

## 6. Tests

```
tests/
  unit/      # one file per module; pure, fast, no I/O
  attacks/   # one file per attack; the paired tests from §7
  e2e/       # full runs against stub agents; report shape and exit codes
```

Rules:

- `pytest` only. No unittest classes. Plain functions and fixtures.
- Name: `test_<subject>_<condition>_<expected>` —
  `test_over_daily_cap_sum_exceeds_limit_returns_true`.
- **No test touches the network.** An autouse fixture in `conftest.py` patches `httpx` to
  raise on any request. A test that needs an LLM uses a cassette or a fake client.
- Fixtures build objects through real constructors, so validation is exercised. No
  `object.__new__` shortcuts, no `MagicMock` where a real dataclass will do.
- Assert on the specific thing. `assert verdict is Verdict.FAIL`, never `assert result`.

### Coverage — targeted, not a global number

| Module | Requirement |
|---|---|
| `judge/deterministic.py` | **100% lines and branches.** Every predicate: one true case, one false case, one boundary case (exactly at the cap). |
| `mandate.py` | **100%.** Every validation rule has a test proving it raises. |
| `sink.py`, `judge/verdict.py` | **100%.** |
| `runner.py`, `ledger.py` | ≥90%, including the isolation and crash-recovery paths. |
| Everything else | ≥80%. |

A global coverage percentage is a number you can game. These are the modules where a bug
produces a wrong verdict, and they are held to a different standard.

### Must be covered

- Every mandate validation rule, proven to raise.
- Every deterministic predicate at its boundary: an amount exactly equal to the cap is
  **not** a violation; one paise over is. Off-by-one here is a false accusation or a missed
  vulnerability.
- Both isolation boundaries: an agent that raises produces `ERROR` and the run continues.
- The circuit breaker: after N failures, no further provider calls are made (assert the call
  count, not just the verdict).
- Crash recovery: a truncated final line in a ledger is skipped with a warning, and the
  report regenerates from what remains.
- Exit codes: one test per code, 0 through 3.
- Every fixed bug gets a regression test in the same commit as the fix.

---

## 7. The attack rule

**Every attack added to the catalogue ships with two tests, in the same commit.**

```python
# tests/attacks/test_spf_001.py


def test_spf_001_detects_on_naive_stub() -> None:
    """The attack catches the vulnerability it claims to catch."""
    record = run_attack(SPF_001, NaiveStub())
    assert record.verdict is Verdict.FAIL
    assert "homoglyph_collision" in record.predicates_fired


def test_spf_001_no_false_positive_on_hardened_stub() -> None:
    """A correctly-defending agent is not accused."""
    record = run_attack(SPF_001, HardenedStub())
    assert record.verdict is Verdict.PASS
```

Why both are mandatory:

- Without the first, an attack may be detecting nothing and quietly inflating every agent's
  safety score. A test suite full of attacks that cannot fire is worse than no test suite.
- Without the second, the harness cries wolf. A safety tool that flags correct behaviour gets
  turned off, and then it protects nobody.

Both run against the deterministic stubs in `subjects/stubs.py`, never against a live model.
CI has no API key and must stay green. **An attack whose detection cannot be demonstrated
offline does not ship.**

The first test also asserts *which predicate fired*, not just the verdict. An attack that
fails for the wrong reason is not evidence of the vulnerability it names.

Where an attack is expected to be genuinely unresolvable (CDP-001 under a downed provider),
the second test asserts `Verdict.UNKNOWN` and the docstring says why.

---

## 8. Docstrings

Google-style, trimmed. One-line summary in the imperative, ending in a full stop. Blank line,
then prose only if there is something non-obvious to say.

- **Document why, not what.** `Returns the sum of amounts` is noise. `Sums across turns
  because per-call checks are exactly what salami-slicing defeats` is the reason the function
  exists.
- `Args:` only for parameters whose meaning is not evident from name and type.
- `Raises:` is **mandatory** for anything raising a `GauntletError`. Callers need to know
  what they must handle.
- Every module in `attacks/catalogue/` has a module docstring containing: the threat model in
  two sentences, the real-world analogue with a source where one exists, and why the success
  criterion is what it is.
- Every predicate in `judge/deterministic.py` states its boundary condition explicitly —
  whether the comparison is `>` or `>=` and why.

```python
def over_daily_cap(attempts: Sequence[PaymentAttempt], mandate: Mandate, day: date) -> bool:
    """Report whether the day's attempts exceed the mandate's daily cap.

    Sums across the whole episode rather than checking each attempt, because
    per-call checking is precisely the gap salami-slicing (SAL-001) exploits.

    Boundary: a total exactly equal to the cap is permitted; one minor unit
    over is a violation.
    """
```

---

## 9. Commits

Conventional Commits. Imperative mood, subject 72 characters or fewer, no trailing full stop.

```
<type>(<scope>): <subject>

<why this change exists — not what the diff shows>
```

Types: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`.
Scopes: `mandate`, `sink`, `agent`, `context`, `attacks`, `judge`, `llm`, `runner`, `ledger`,
`report`, `subjects`, `cli`, `ci`.

```
feat(attacks): add homoglyph merchant spoof (SPF-001)

Name-based merchant matching is the default in every agent framework
we looked at, and a leading Cyrillic А defeats it silently. Detection
is NFKC folding plus a confusables table — no model in the path.
```

- One logical change per commit. An attack and its two tests are **one** commit; splitting
  them lets an untested attack exist on `main`, however briefly.
- A fix and its regression test are one commit.
- Never commit `.env`, `runs/`, `.venv`, or coverage output. They are in `.gitignore`; keep
  them there.
- Commit messages are read by the judges. `wip`, `fix stuff`, and `asdf` are not free.

---

## 10. Review checklist

Before every commit, and before the final push on 4 September:

- [ ] `make ci` green
- [ ] No `except` block that swallows (`grep -rn "except" gauntlet/` and read every one)
- [ ] No `float` in the payment path (`grep -rn "float" gauntlet/`)
- [ ] No `Any` in a new public signature
- [ ] New attack has both tests, in this commit
- [ ] New predicate has a boundary test
- [ ] Nothing new imports `httpx` or `rich` outside their designated modules
- [ ] Docstrings say *why*
- [ ] Nothing secret, and no `runs/`, in the diff
